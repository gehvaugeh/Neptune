# Neptune Performance Analysis & Optimization Proposals

## 1. Findings

### Client-Side Bottlenecks
- **Terminal Rendering (`CommandBlock.render_terminal`)**:
  - The current renderer iterates through every cell in the `pyte` buffer.
  - It creates many small `Text` objects or appends characters one by one.
  - There is a style cache, but the overhead of `rich.Text` manipulation for every cell is high.
- **Large Notebooks**:
  - Having 100+ blocks in the `ScrollableContainer` causes layout and rendering lag in Textual.
  - Filtering iterates through all blocks and toggles CSS classes, which can be slow if not debounced or if many blocks match.
- **Message Handling**:
  - Every `output` message from the server triggers a `render_terminal` call on the client. High-frequency output can overwhelm the UI thread.

### Remote PTY Bottlenecks
- **Polling Latency**: `RemotePTY` previously used a 0.5s polling interval. This has been optimized to 0.25s to balance responsiveness and overhead.
- **`ps` Overhead**: Calling `ps` over SSH frequently is expensive.
- **Input Lag**: Typing in `CONTROL` mode (TUI) sends every key individually over the socket, then over SSH.

---

## 2. Optimization Proposals

### P1: Chunk-based Terminal Rendering (Client)
- **Concept**: Instead of cell-by-cell rendering, group contiguous characters with the same style into a single `rich.Text.append` call.
- **Implementation**: Modify `render_terminal` in `client.py` to scan for style changes and batch appends.

### P2: UI Update Throttling (Client)
- **Concept**: Limit the frequency of `render_terminal` calls and general UI refreshes to a maximum FPS (e.g., 20 FPS).
- **Implementation**: Use a timer or `asyncio.sleep` to debounce/throttle updates in `CommandBlock.append_output`.

### P3: Virtualized/Lazy Rendering for Blocks (Client)
- **Concept**: Only render or update the terminal buffer for blocks that are actually visible or recently focused.
- **Implementation**: Use `on_scroll` events or focus tracking to decide when to skip `render_terminal`.

### P4: Improve Remote PTY Command Monitoring (Server)
- **Concept**: Find a "sweet spot" for `ps` polling frequency that provides good responsiveness without overloading the system.
- **Implementation**:
  - Set polling interval to 0.25s.
  - Ensure robust sentinel handling when the command eventually finishes.

### P5: Output Batching (Server)
- **Concept**: Batch small chunks of output from PTYs before broadcasting to clients.
- **Implementation**: Buffer output for ~20ms in `PTYManager` before sending.

### P6: Optimized Filtering (Client)
- **Concept**: Cache the searchable text for blocks and use a faster fuzzy matching algorithm. Debounce the filter input.

---

## 3. Action Plan
1. Implement **P1** (Chunk-based rendering) and **P2** (Throttling) first as they have the highest impact on general responsiveness.
2. Implement **P4** (Remote PTY monitoring) to fix the input/completion lag.
3. Implement **P5** (Output batching) to reduce message overhead.
4. Update Blackbox tests to measure and report these improvements.
