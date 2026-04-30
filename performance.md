# Neptune Performance Profile

This document tracks performance bottlenecks identified during profiling and provides recommendations for optimization.

## Summary of Findings

The primary performance bottleneck in Neptune is the **terminal rendering logic** within the `CommandBlock` class. When a command generates significant output or when many blocks are present, the client experiences noticeable lag. This is primarily due to cell-by-cell processing of the terminal buffer and inefficient handling of terminal history during every UI update.

## Client-Side Performance

### Identified Bottlenecks

1. **Cell-by-Cell Terminal Rendering (`render_terminal`)**
   - **Description**: The `render_terminal` method iterates over every character in every row of the `pyte` screen buffer to build a `rich.text.Text` object.
   - **Impact**: For a standard 80x24 terminal, this is 1,920 iterations per render call. If history is included, it can be up to 80,000+ iterations.
   - **Profiling Data**: In a test with 100 small updates, `render_terminal` and its helper `append_line` accounted for over 90% of execution time, with hundreds of thousands of calls to `_get_rich_style`.

2. **Excessive History Rendering**
   - **Description**: `render_terminal` prepends the entire `pyte` history (up to 1,000 lines) to the output widget on every update when not in `CONTROL` mode.
   - **Impact**: This causes linear performance degradation as the command output grows. Rendering a block with 1,000 lines of history is significantly slower than rendering a fresh one.
   - **Recommendation**: Implement a virtualized scrollback or only render the visible portion of the history. Alternatively, cache the rendered history chunks.

3. **High Frequency of UI Updates**
   - **Description**: `append_output` triggers `render_terminal` immediately upon receiving any data.
   - **Impact**: Rapidly streaming data (e.g., `yes` or `cat large_file`) causes the TUI to choke on render calls, many of which are redundant if they occur faster than the screen's refresh rate.
   - **Recommendation**: Throttling or debouncing `render_terminal` calls (e.g., using a minimum interval like 50ms).

4. **Style Object Creation overhead**
   - **Description**: Although `_get_rich_style` uses a cache, the overhead of creating the cache key (a 6-element tuple) and performing the lookup for every single character is significant.
   - **Impact**: Millions of tuple creations and lookups during heavy output.
   - **Recommendation**: Process "runs" of characters with identical attributes together rather than cell-by-cell.

5. **Textual Layout Overhead with Many Blocks**
   - **Description**: Having 500+ blocks in a `ScrollableContainer` slows down operations like filtering or reordering because Textual has to manage a large widget tree.
   - **Impact**: UI feels "heavy" and slow to respond to inputs.
   - **Recommendation**: Use a more dynamic "virtual list" approach for blocks if possible, or optimize block widget complexity.

### Stress Test Results (on Linux, Python 3.12)

| Scenario | Metric | Result |
|----------|--------|--------|
| Import 500 blocks | Time (s) | ~0.1s |
| Filter 500 blocks (logic only) | Latency (ms) | < 5ms |
| Append & Render 1,000 lines | Total Time | ~0.25s |
| 100 small output updates | Total Time | ~2.8s |

## Recommendations for Optimization

1. **Chunk-based Rendering**: Modify `render_terminal` to group characters with the same style into chunks before calling `rich_text.append`. This drastically reduces the number of calls to `append` and style lookups.
2. **Throttled Rendering**: Use an asyncio task to batch output updates and only re-render the terminal at most 20-30 times per second.
3. **Lazy History Rendering**: Don't re-render the entire history every time. Keep a separate `rich.text.Text` for the history and only append new "committed" lines from the `pyte` buffer to it.
4. **Optimize Style Cache**: Simplify the style cache or use a more efficient way to detect attribute changes between cells.
5. **Rust/C for Terminal Emulation**: If Python optimizations aren't enough, the entire `render_terminal` loop (converting `pyte` buffer to `Rich` segments) could be moved to a Rust extension (using `PyO3`).
