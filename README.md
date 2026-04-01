# Neptune: Collaborative Notebook Shell

Neptune is a notebook-style terminal and collaborative editor designed for Termux and local development. It features a client-server architecture, allowing multiple users to work in the same shell session.

## Features

- **Collaborative Notebook**: Multiple users can connect to the same session over Unix Domain Sockets.
- **Block Locking**: Blocks being edited by others are visually locked (indicated by a color-coded right border).
- **Persistent Sessions**: The server keeps the session state even if all clients disconnect.
- **Notebook Export/Import**: Save and load your shell sessions as Markdown files.
- **Interactive Palette**: Enhanced command and path completion.
- **Block Reordering**: Move commands and notes up or down.
- **Real-time Filtering**: Search and filter blocks by content (Ctrl+F).
- **Selection Mode**: Navigate and manipulate blocks with Vim-like shortcuts.

## Getting Started

### Using the Launcher (Recommended)
The launcher can start both server and client at once, or either one individually.
```bash
python3 main.py all [-s /path/to/socket]
```
- `all`: Starts server in background and client in foreground.
- `server`: Starts only the server.
- `client`: Starts only the client.

### Manual Start
1. **Start the Server**
   ```bash
   python3 server.py [-s /path/to/socket]
   ```
2. **Start the Client**
   ```bash
   python3 client.py [-s /path/to/socket]
   ```
*Default socket: `/tmp/gemmi_shell.sock`*

## Keyboard Shortcuts

### Navigation & Modes (NORMAL Mode)
- **!**: Enter **BASH** input mode.
- **:**: Enter **CMD** (Internal Command) mode.
- **;**: Enter **NOTE** (Markdown) mode.
- **s**: Enter **SELECTION** mode.
- **Ctrl+F**: Toggle block filtering.
- **Ctrl+Q**: Exit the client.
- **Esc**: Return to NORMAL mode / Clear current action.

### Input Modes (BASH, CMD, NOTE)
- **Enter**: Submit command or save note.
- **Ctrl+J** or **Ctrl+Enter**: Insert newline (multiline input).
- **Tab** or **Ctrl+P**: Open autocomplete palette.
- **Up / Down**: Navigate autocomplete suggestions (when open).
- **Esc**: Cancel input and return to NORMAL mode.

### Selection Mode
- **j / k** or **Down / Up**: Navigate between blocks.
- **Numeric Prefix**: Repeat navigation (e.g., `5j` moves down 5 blocks).
- **x**: Delete the focused block.
- **y**: Yank (copy) the focused block.
- **p / P**: Paste yanked block after/before focused block.
- **e**: Edit the focused block.
- **j** (on Command Block): Re-run the command.
- **Ctrl+Up / Ctrl+Down**: Move the focused block up or down.
- **! / : / ;**: Directly enter input modes from selection.

### Block Editing
- **Ctrl+J**: Save changes and return to NORMAL mode.
- **Esc**: Discard changes and return to NORMAL mode.

## Internal Commands (CMD Mode)
Access by pressing `:` in NORMAL mode:
- **export [file.md]**: Export notebook to a Markdown file.
- **import [file.md]**: Import blocks from a Markdown file.
- **save_wf**: Save the current input as a reusable Workflow.
- **clear**: Clear all blocks and reset shell state.
- **help**: Show available internal commands.
- **exit**: Exit Gemmi-Shell.

## Multi-User Collaboration
Each user is assigned a random color. When a block is being edited, a colored border appears on the right, and it is locked for other users. All changes (edits, reordering, command execution) are synchronized in real-time.

## Requirements
- Python 3.10+
- `textual`, `rich` libraries
- Termux (optional, but optimized for it)
