# Neptune Server

The server (`server.py`) is the backbone of the Neptune system. It manages the persistent shell session and coordinates multiple clients.

## Key Responsibilities

### 1. Master Shell Management
The server maintains a persistent PTY-connected shell.
- **PGID Tracking:** It uses `os.tcgetpgrp(master_fd)` to monitor the foreground process group. This allows the server to reliably detect when a command has finished, even if it was interrupted by Ctrl+C or failed with a syntax error.
- **Silent Status Retrieval:** After a command finishes, the server automatically executes a hidden `printf` to capture the exit code (`$?`) and the updated current working directory (`pwd`).
- **Signal Handling:** Signals like `SIGINT` (Ctrl+C) are delivered to the entire process group of the foreground task using `os.killpg`.

### 2. Sequential Command Execution
Commands submitted by clients are placed in a `command_queue`.
- An `asyncio.Condition` manages the execution loop.
- Only one command block is "active" at a time.
- Queue positions (e.g., `queued(2)`) are broadcast to all clients in real-time.

### 3. Collaborative State & Locking
To prevent edit conflicts, the server implements a simple locking mechanism:
- When a user starts editing a block, they acquire a `locked_by` status.
- Other users see the block as locked and cannot edit it.
- Locks are automatically released if a client disconnects.

### 4. Interactive Mode Support
When a client enters `CONTROL` mode:
- Raw keystrokes are forwarded to the master PTY via `terminal_input` messages.
- PTY output is streamed back to all clients.
- The server handles terminal resizing and toggles `ECHO` state on the TTY as requested by clients.

## Implementation Details
- **PTY Handling:** Uses `pty.openpty()` and `asyncio.create_subprocess_exec`.
- **Concurrency:** Built entirely on `asyncio` for non-blocking I/O with multiple clients and the PTY.
- **Environment:** Sets `TERM=xterm-256color` and `COLORTERM=truecolor` to ensure full ANSI support.
