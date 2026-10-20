# PTY Bindings via YAML Frontmatter

**Status:** Implemented (`0d0afc6`, extended for remote `ssh_config` persistence)
**Goal:** When a notebook is imported, PTY bindings of its code blocks are restored
automatically — including reconnecting remote PTYs — instead of requiring manual
re-assignment in the PTY Manager.

---

## 1. Problem

- Block-to-PTY binding was a **numeric UID** (`pty_uid`) assigned by the server's
  `PTYManager`, e.g. `0` = `local-0`, `3` = a remote. UIDs are **ephemeral per
  server run**.
- Export wrote ` ```bash (uid:N) `; import treats any non-zero UID as
  `pty_uid = None`, so remote bindings were silently lost.
- The client never persisted the remote `ssh_config`; the server keeps it only in
  the live `RemotePTY` object (password masked, then removed). Exports therefore
  contained `type: remote` without `host`/`user`, and re-creation crashed with
  `TypeError: expected str, bytes or os.PathLike object, not NoneType`.

## 2. Solution Overview

1. **Symbolic PTY names** replace ephemeral UIDs. Named PTYs are stable enough to
   survive a server restart (`local-0`, `t1-app-01.hio.rub.de-1`, ...).
2. **YAML frontmatter** at the top of the notebook carries a `neptune.ptys`
   registry: name → `{type: local|remote, host, user, port, key}`.
3. **No block IDs / no block→PTY map.** Binding is encoded inline in each code
   fence as a `(pty:<name>)` token, so reordered fences stay correct.
4. On import, Neptune **reconciles** the registry against the live session:
   reuses same-named PTYs, creates missing ones, and rebinds each block to the
   PTY named in its fence. Failed remotes leave their blocks unassigned.
5. **Passwords and private-key contents are never written to disk.**

## 3. File Format

````markdown
---
neptune:
  version: 1
  ptys:
    local-0:
      type: local
    t1-app-01.hio.rub.de-1:
      type: remote
      host: t1-app-01.hio.rub.de
      user: myuser
      port: 22
      key: /home/me/.ssh/id_ed25519
---
# Shell Notebook Export - 2026-10-20 12:00:00

```bash (pty:local-0)
git status
```

```bash (pty:t1-app-01.hio.rub.de-1)
sudo systemctl status tomcat
```
````

Notes:
- The first token after the language (`bash`) is the fenced-code info string; the
  `(pty:name)` token is valid CommonMark info-string text and is ignored by other
  renderers. Keeping `bash` preserves syntax highlighting.
- Legacy `(uid:N)` fences and files without frontmatter still import as before
  (unassigned unless UID 0).
- `key` is a path, never key material.

## 4. Component Changes

### 4.1 `frontmatter.py` (new, shared module)

Dependency-free parser/writer for the closed YAML subset we emit (nested maps +
scalars). Malformed or absent frontmatter → `None`, so legacy files import
unchanged. PyYAML is intentionally not required.

### 4.2 Fence tokenizer (client.py)

Fences are matched and the optional `(pty:<name>)` token is extracted. The
language token remains (`bash` / `text`), so block type detection is unchanged.
`text` fences remain output-only.

### 4.3 Server exposes sanitized `ssh_config`

`PTYManager` now publishes connection metadata for remote PTYs:

- `list_ptys()` includes `ssh_config: {host, user, port, key}` (sanitized).
- `pty.created` does the same.
- `_sanitized_ssh_config()` drops the password unconditionally.

This makes the **server the source of truth**, so PTYs created before this feature,
by another client, or via the UI can all be exported correctly.

### 4.4 Client caching

`ClientApp.ptys[uid]["ssh_config"]` is populated from `init`, `pty.created`, and
`pty.list` (server value first, then the import-time `_pending_remote_cfg`, then a
previously cached value). Passwords are popped before caching.

### 4.5 Export (`export_notebook` + autosave + crash autosave)

Shares `_build_notebook_markdown()`:

1. Emit frontmatter from cached PTY configs (`type`, `host`, `user`, `port`, `key`).
2. Emit each command fence with `(pty:<resolved name>)`.
3. Autosave and crash-recovery files use the same format and are round-trip
   importable.

### 4.6 Import (`import_notebook`)

1. Parse frontmatter (optional) + fences (`pty:` token, legacy `uid:` token).
2. Reconcile PTYs by name:
   - `local` → `pty.create.local` with the file's name.
   - `remote` → validate/infer config, then `pty.create.remote`.
   - wait up to 15 s for creation; `pty.error` names are matched and reported.
3. Apply `(pty:name)` bindings to the imported blocks. If a PTY could not be
   created/connected, its blocks stay unassigned (`pty_uid=None`) — never silently
   fall back to `local-0`.
4. One summarized warning toast lists the failed names and reasons.

#### Legacy recovery (frontmatter with `type: remote` but no host/user)

Older exports only contain `type: remote`. On import Neptune performs a
best-effort recovery:

- **host** is derived from the server's default name pattern `<host>-<uid>`
  (e.g. `t1-app-01.hio.rub.de-1` → `t1-app-01.hio.rub.de`);
- **user** is looked up in the saved remote-host history (`remote_hosts.txt`);
- if no user is known, ssh falls back to the local username / agent;
- `key`/`password` cannot be recovered. If auth still fails, the user gets a clear
  `Permission denied ...`-style message and can re-create the PTY.

### 4.7 Remote connect robustness (`pty_remote.py`)

- `host` is validated before spawning anything; a missing host raises a clear
  `ValueError` instead of reaching `create_subprocess_exec(None)`.
- `BatchMode=yes` is used when no password is supplied, so ssh fails fast instead
  of blocking on an interactive prompt.
- ssh's stderr is captured and included in the failure message
  (`ControlMaster socket failed to initialize: <reason>`).
- A half-open master process is killed on failure; on success stderr is drained in
  the background to avoid pipe back-pressure.

## 5. UX

- `:import notebook.md` → PTYs are created/reconnected and blocks are rebound
  automatically.
- Missing/failed remote → warning toast naming the PTY and the reason; affected
  blocks remain unassigned and can be re-bound via `ctrl+t`.
- Remote PTYs created through the UI (`!!` → PTY target bar) now persist their
  host/user/port/key on the next export.

## 6. Remaining / Future Work

- Optional pre-filled auth modal on import when a key/password is required
  (currently the failure is reported and the user re-creates the PTY).
- Re-resolve PTY names at `run_block` time to survive mid-session destruction.
- Restore per-block `cwd` for remote shells.
- Queue auth prompts instead of a single summarized failure.
- Collision handling for two same-named remote configs in one file.
- Decide whether to add PyYAML as an optional parser backend.
