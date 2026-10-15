# PTY Bindings via YAML Frontmatter — Concept & Plan

**Status:** Proposal (not yet implemented)
**Goal:** When a notebook is opened (imported), PTY bindings of its code blocks are
restored automatically instead of requiring manual re-assignment in the PTY Manager.

---

## 1. Problem

- Block-to-PTY binding today is a **numeric UID** (`pty_uid`) assigned by the server's
  `PTYManager` (`pty_manager.py`, `uid_counter`), e.g. `0` = `local-0`, `3` = a remote.
- UIDs are **ephemeral per server run**. Export writes ` ```bash (uid:N) `.
- Import (`client.py:import_notebook`) reads `(uid:N)` but treats any non-zero UID as
  `pty_uid = None` (`client.py:1987`). Remote bindings are therefore **silently lost**.
- The user must re-create the remote PTY and re-bind blocks via `ctrl+t` (PTY Manager)
  every time a notebook is opened. This is "on purpose" today — but it is manual and
  error-prone.
- The client never persists the remote `ssh_config`; the server keeps it only in the
  live `RemotePTY` object (password masked, then removed).

## 2. Solution Overview

Make the exported Markdown self-describing:

1. **YAML frontmatter** at the top of the notebook file (parsed only when present;
   old files keep working) carrying:
   - a **symbolic PTY registry** (`ptys:`): stable, human-readable names
     (`local-0`, `prod-db`) instead of ephemeral UIDs, with `type: local|remote`
     and remote connection data (`host`, `user`, `port`, `key`).
   - a **block → PTY map** (`blocks:`): stable block IDs to symbolic PTY names.
2. **Stable block IDs** in the code-block info string (`(id:blk-ab12)`), Markdown-
   conform (CommonMark info strings are free-form text after the language).
3. On import, Neptune **reconciles** the frontmatter against the live session:
   reuses same-named PTYs, creates missing ones (local instantly, remote with the
   saved config, prompting only for password), and rebinds every block.

## 3. File Format

```markdown
---
neptune:
  version: 1
  ptys:
    local-0:
      type: local
    prod-db:
      type: remote
      host: db.example.com
      user: deploy
      port: 22
      key: ~/.ssh/id_ed25519
  blocks:
    blk-ab12:
      pty: prod-db
      cwd: /srv/app
    blk-cd34:
      pty: local-0
---
# Shell Notebook Export - 2026-10-09 22:00:00

```bash (uid:0) (id:blk-ab12)
git pull && ./deploy.sh
```

```text
[...output...]
```
```

Notes:
- `neptune:` namespacing avoids collisions with Jekyll/Hugo/etc. frontmatter.
- The fence keeps `(uid:N)` for backward compatibility; **frontmatter is
  authoritative when present**.
- **Passwords and private-key contents are never written to disk.**
- `cwd` per block is optional (restored after reconnect for remote shells).

## 4. Component Changes

### 4.1 `frontmatter.py` (new, shared module)

A small, dependency-free frontmatter reader/writer:

- `parse_frontmatter(text) -> (dict | None, body)`: extracts `---\n...\n---` header,
  parses a **strict YAML subset** (nested maps, scalar strings/ints/bools, `#` comments
  outside scalars). Unsupported/malformed → `None` (treat as legacy file).
- `build_frontmatter(ptys, blocks) -> str`: emits exactly the subset the parser reads
  (we control the writer, so the subset is closed).
- Optional: if `import yaml` is available at runtime, use PyYAML for parsing instead
  (more robust); otherwise fall back to the subset parser. **PyYAML is not currently
  installed** — decide in Phase 1 whether to add it as a dependency or keep the
  subset parser (recommended: subset parser, zero deps; PyYAML as optional).

### 4.2 Fence info-string tokenizer (client.py)

Replace the single `(uid:\d+)` regex with a tokenizer for parenthesized KV pairs
arriving in the info string:

- ` ```bash (uid:0) (id:blk-ab12) ` → `{uid: 0, id: "blk-ab12"}`
- Unknown tokens ignored, old format ` ```bash (uid:N) ` still parses.
- `text` fences stay output-only (no id/pty semantics).

### 4.3 Client caching of `ssh_config`

- `ClientApp` caches the config it already sends in `pty.create.remote`
  (`client.py:~2272`) as `self.ptys[uid]["ssh_config"]` (host/user/port/key — the
  password is entered on the modal and stays out of the cache in plain form after
  connect; keep the existing masking/`del` behavior server-side).
- This cache is the export source for `ptys:`.

### 4.4 Export (`export_notebook` + autosave + crash autosave)

1. Assign stable IDs: reuse a block's persisted `stable_id` if present, else
   generate `blk-<4hex>` (unique within the file).
2. Write frontmatter from cached PTY configs + block→pty map.
3. Fences get `(uid:N) (id:blk-xxxx)`.
4. Autosave files become roundtrip-importable (same path as export).

### 4.5 Import (`import_notebook`)

1. Parse frontmatter (optional). Parse fences (uid + id).
2. Build **binding plan**:
   - for each `ptys[name]` missing in the live session →
     - `local` → `pty.create.local` with the name
     - `remote` → `pty.create.remote` with saved config + name; on `pty.error`
       (auth needed) → push `RemotePTYAuthModal` **prefilled** with
       host/user/port/key from the file
   - same-named live PTY → reuse its UID
3. Resolve each block: `blocks[id].pty` → session UID → set `pty_uid`/`pty_name`
   (plumbed through `import_blocks`/`add_block` server-side and reused by
   `create_block` client-side).
4. Restore `cwd` for remote blocks after connect (shadow `cd` + `_update_cwd`).
5. Unresolvable bindings → bind to `local-0`, notify warning.

### 4.6 Server (`server.py` / `pty_manager.py`)

- `add_block` / `import_blocks`: carry a passthrough `stable_id` on the block dict.
- No store of recipes server-side — the client drives reconnection (server stays
  stateless); `pty.create.local/remote` already accept a `name`.

## 5. UX

- `:import notebook.md` → "Restoring PTYs: local-0, prod-db (remote)" →
  auto-create + rebind. No manual re-binding.
- Missing password → one prefilled modal per remote host (user can use an SSH agent
  key instead; modal already supports both).
- `:import notebook.md --no-ptys` (optional) → import only, all blocks on `local-0`.
- PTY Manager (`ctrl+t`) continues to work as today; renames are picked up on the
  next export because export reads live names.

## 6. Implementation Plan

### Phase 1 — Foundation (core roundtrip)
1. `frontmatter.py` (subset parser + writer) and fence tokenizer; unit tests.
2. Export: stable IDs + frontmatter; client `ssh_config` cache on
   `pty.created`.
3. Import: reconcile PTYs, bind blocks, prefilled auth modal on `pty.error`.
4. Blackbox: export → `:clear` → import roundtrip preserves bindings;
   old-format files still import as today.

### Phase 2 — Polish
5. `resolve_pty(name)` re-resolution at `run_block` time (resilient to
   mid-session PTY destruction/recreation).
6. `cwd` restore for local + remote after reconnect.
7. `--no-ptys` flag; WARN summary listing missing/matched PTYs.
8. Collision handling: two same-named remote configs in one file.

### Phase 3 — Robustness
9. Queue auth prompts (don't block the whole import).
10. Multi-user: broadcast a notification when an auto-created PTY appears
    (already happens via `pty.created`).
11. Decide/add PyYAML if the subset parser proves insufficient.

## 7. Risks / Open Questions

- **Dependency:** PyYAML not installed. Preferred: closed subset parser (we are the
  only writer) + optional PyYAML upgrade path. *(decide in Phase 1)*
- **ID stability across sessions:** `stable_id` must survive server `add_block`
  round-trip; blocks created *within* a session without import get IDs at export
  time only — acceptable? Or persist on server block dict from creation?
- **Remote auth at import time:** password required only when the host is not
  reachable with existing keys — modal appears only in that case.
- **`cwd` semantics:** restore only for remote (local cwd is the client's spawn cwd
  today); confirm desired local behavior.
- **Migration:** keep writing `(uid:N)` forever for tools/older clients that read it.