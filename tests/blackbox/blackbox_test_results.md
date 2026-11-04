# Neptune Blackbox Test Results

**Automated Verification Run:** Wed Nov  4 14:32:17 2026

| Feature Test | Result | Details |
|--------------|--------|---------|
| Verify Startup via Echo | ✅ PASS |  |
| Execute BASH Echo | ✅ PASS |  |
| Internal Help Command | ✅ PASS |  |
| Create Note | ✅ PASS |  |
| Setup AAA | ✅ PASS |  |
| Enter Selection Mode | ✅ PASS |  |
| Delete block via Selection Mode | ✅ PASS |  |
| Setup MoveMe | ✅ PASS |  |
| Reorder block (Ctrl+Up) | ✅ PASS |  |
| Path Autocomplete Visibility | ✅ PASS |  |
| Autocomplete Append - palette opens | ✅ PASS |  |
| Autocomplete Append - palette closed | ✅ PASS |  |
| Autocomplete Append - command preserved | ✅ PASS |  |
| Autocomplete Append - command executes | ✅ PASS |  |
| Setup YankMe | ✅ PASS |  |
| Yank and Paste block | ✅ PASS |  |
| CMD File Completion - PATH entries visible | ✅ PASS |  |
| CMD File Completion - palette closes after selection | ✅ PASS |  |
| NOTE Toolbox - entries visible | ✅ PASS |  |
| NOTE Toolbox - closes after selection | ✅ PASS |  |
| NOTE Toolbox with text - entries visible | ✅ PASS |  |
| NOTE Toolbox with text - closes | ✅ PASS |  |
| NOTE Toolbox - original text preserved | ✅ PASS |  |
| NOTE Toolbox arrows - entries visible | ✅ PASS |  |
| NOTE Toolbox arrows - toolbox closes after navigation | ✅ PASS |  |
| Duplicate ID - palette opens without crash | ✅ PASS |  |
| Duplicate ID - history entry visible | ✅ PASS |  |
| Duplicate ID - workflow entry visible | ❌ FAIL | Expected 'WORKFLOW:' not found |
| Import+Scroll - top blocks render after scroll up | ✅ PASS |  |
| Import+Scroll - bottom output preserved after scroll down | ✅ PASS |  |
| Autosave - change-driven file created with content | ✅ PASS |  |
| Autosave - :clear does not clobber last autosave | ✅ PASS |  |
| Autosave - file refreshes to newest state | ✅ PASS |  |
| PTY Frontmatter - export writes neptune.ptys registry | ✅ PASS |  |
| PTY Frontmatter - fence carries (pty:<name>) token | ✅ PASS |  |
| PTY Frontmatter - import restores bound block | ✅ PASS |  |
| PTY Remote Reconnect - remote created | ✅ PASS |  |
| PTY Remote Reconnect - command ran | ✅ PASS |  |
| PTY Remote Reconnect - persists host/user/key | ✅ PASS |  |
| PTY Remote Reconnect - reconnects on import | ✅ PASS |  |
| PTY Remote Reconnect - clear auth error | ✅ PASS | 0.0.
                                       ▌ 1: Permission denied
───────────────────────────────────────▌ (publickey,password).                ──
 MODE: NORMAL                          ▌
   User: Me |
