# Neptune Performance Profile

This document tracks performance bottlenecks identified during profiling and provides recommendations for optimization.

## Summary of Findings

The primary performance bottleneck in Neptune was the **terminal rendering logic** within the `CommandBlock` class. Cell-by-cell processing of the terminal buffer and inefficient handling of terminal history during every UI update caused significant lag.

## Client-Side Performance

### Identified Bottlenecks (and Optimizations)

1. **Cell-by-Cell Terminal Rendering (`render_terminal`)**
   - **Status**: **Optimized** via Chunk-based Rendering.
   - **Optimization**: Instead of cell-by-cell `rich_text.append` and style lookups, the renderer now groups characters with identical attributes into chunks.
   - **Impact**: Reduced `render_terminal` overhead by ~35% in synthetic benchmarks (100 updates). Function call counts dropped significantly.

2. **Excessive History Rendering**
   - **Status**: **Optimized** via Lazy Rendering.
   - **Optimization**: History is now only rendered for the focused block or if the history size is small (<100 lines). A hint is displayed when history is hidden.
   - **Impact**: drastically improved scrolling and responsiveness when many blocks with large history are on screen.

3. **High Frequency of UI Updates**
   - **Status**: **Optimized** via Throttling.
   - **Optimization**: `append_output` now uses a throttled update mechanism (max 20 FPS). Redundant re-renders are skipped or batched.
   - **Impact**: Prevents TUI from choking on rapid data streams (e.g., `cat large_file`).

4. **Style Object Creation overhead**
   - **Status**: **Optimized** via Attribute-based Caching.
   - **Optimization**: The style cache now uses the raw `pyte` attribute tuple directly as a key, avoiding intermediate object creation in the hot loop.

5. **Textual Layout Overhead with Many Blocks**
   - **Status**: Investigated.
   - **Recommendation**: For notebooks with 1000+ blocks, a virtualized list or manual widget visibility management may be needed. Current optimizations provide enough headroom for typical usage (hundreds of blocks).

### Benchmark Results (after optimizations)

| Scenario | Metric | Result (Before) | Result (After) | Improvement |
|----------|--------|-----------------|----------------|-------------|
| Import 500 blocks | Time (s) | ~0.1s | ~0.1s | - |
| Filter 500 blocks | Latency | < 5ms | < 5ms | - |
| 100 small updates | Total Time | ~2.8s | ~1.8s | **~35%** |
| Render 1000 lines | Total Time | ~0.25s | ~0.18s | **~28%** |

## Future Recommendations for Optimization

1. **Virtualized History**: Implement a separate scrolling layer for history to allow viewing large histories without rendering the whole block content.
2. **Rust/C Extension**: Move the character run detection and segment building to Rust (using `PyO3`) if absolute performance is required for 100k+ lines.
3. **Async Output Handling**: Move terminal emulation (`pyte.feed`) to a separate thread or process if it blocks the TUI main loop for too long during massive output.
