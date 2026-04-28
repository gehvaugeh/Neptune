# Neptune Client

The client (`client.py`) provides the Textual-based terminal user interface.

## Interaction Modes

Neptune uses a modal system inspired by Vim to maximize productivity in a terminal environment:

- **NORMAL:** The default state. Used for viewing the notebook.
  - `!`: Switch to BASH input.
  - `:`: Switch to Internal Command input.
  - `;`: Switch to Markdown Note input.
  - `s`: Enter **SELECTION** mode.
  - `Ctrl+F`: Toggle block filtering.
- **BASH / CMD / NOTE:** Input modes for creating new blocks. Supports Autocomplete via `Tab`.
- **SELECTION:** Navigate and manipulate existing blocks.
  - `j` / `k` (or arrows): Navigate blocks. Supports numeric counts (e.g., `3j`).
  - `x`: Delete block.
  - `e`: Enter **BLOCKEDIT** mode for the focused block.
  - `i`: Enter **CONTROL** mode for interactive terminal sessions.
  - `y` / `p`: Yank and Paste blocks.
  - `Alt+Up/Down`: Reorder blocks.
  - `Ctrl+J` / `Enter`: Execute command block.
- **BLOCKEDIT:** Inline editing of a block's content.
- **CONTROL:** Raw terminal interaction. Keystrokes are streamed directly to the server.

## Terminal Emulation

Neptune implements a custom terminal renderer for `CommandBlock`s:
- **Pyte Integration:** Each command block has its own `pyte.HistoryScreen`. Output from the server is fed into this screen to handle ANSI escape codes, colors, and cursor movements.
- **Rich Rendering:** The Pyte buffer is translated into `rich.text.Text` objects. This allows Neptune to display complex TUI applications like `top` or `vim` directly inside a notebook block.
- **Fixed-Size Terminal & Adaptive Height:** To ensure stability for TUI applications, Neptune uses a fixed TTY size (e.g., 24 rows). This prevents layout shifts and rendering artifacts during dynamic resizing. The UI intelligently shrinks blocks with small output while capping larger outputs at the fixed TTY height with scrollable overflow.

## Collaborative Features
- **Remote Cursors:** (Visualized as block locks) Shows who is editing which block.
- **Real-time Streaming:** Output is broadcast to all clients simultaneously as it is produced by the shell.
