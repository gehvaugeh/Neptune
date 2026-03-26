# Gemmi-Shell: Collaborative Notebook Shell

Gemmi-Shell is a notebook-style terminal and collaborative editor designed for Termux and local development. It features a client-server architecture, allowing multiple users to work in the same shell session.

## Features

- **Collaborative Notebook**: Multiple users can connect to the same session over Unix Domain Sockets.
- **Block Locking**: Blocks being edited by others are visually locked (indicated by a color-coded right border).
- **Persistent Sessions**: The server keeps the session state even if all clients disconnect.
- **Notebook Export/Import**: Save and load your shell sessions as Markdown files.
- **Interactive Palette**: Enhanced command and path completion.
- **Block Reordering**: Move commands and notes up or down.

## Getting Started

### 1. Start the Server
The server manages the session state and executes commands.
```bash
python3 server.py [-s /path/to/socket]
```
*The server listens on `/tmp/gemmi_shell.sock` by default.*

### 2. Start the Client
Open a new terminal and start the client. You can start multiple clients to collaborate.
```bash
python3 client.py [-s /path/to/socket]
```

### Alternatively, use the Launcher
```bash
python3 main.py all [-s /path/to/socket]
```

## Keyboard Shortcuts

- **Ctrl+N**: Toggle between **Command (CMD)** and **Note (NOTE)** mode.
- **Ctrl+J**: Execute the command or save the note.
- **Ctrl+S**: Save the current input as a Workflow.
- **Ctrl+P**: Open the command/path completion palette.
- **Ctrl+E**: Export the current notebook to a `.md` file.
- **Ctrl+I**: Import a notebook from a `.md` file.
- **Shift+Up / Shift+Down**: Move the currently focused block up or down.
- **e**: Edit the focused block (if not locked by someone else).
- **Ctrl+Q**: Exit the client.

## Multi-User Collaboration
Each user is assigned a random bright color on startup. When you or another user starts editing a block, a border in that user's color appears on the right side of the block, and the block is locked for everyone else until the edit is saved (Ctrl+J) or canceled.

## Requirements
- Python 3.10+
- `textual`, `rich` libraries
- Termux (optional, but optimized for it)
