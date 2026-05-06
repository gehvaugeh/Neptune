# Neptune Test Suite (Manual)

This document contains a series of manual test cases to verify the core functionality of the Neptune collaborative notebook shell. These tests are designed to be performed by a human to ensure no regressions occur after code changes.

---

## 1. Session Persistence & Shared State

**Objective:** Verify that the environment state is preserved across different command blocks.

1. **Working Directory Persistence**

```bash
mkdir -p test_dir && cd test_dir
```

```bash
pwd
```
- **Expected Result:** The second block should output a path ending in `/test_dir`.

2. **Environment Variable Persistence**

```bash
export NEPTUNE_TEST=123
```

```bash
echo $NEPTUNE_TEST
```
- **Expected Result:** The second block should output `123`.

---

## 2. Command Queueing & Execution

**Objective:** Verify that commands are executed sequentially and status updates are broadcast.

1. **Sequential Execution**

```bash
sleep 5 && echo "First Done"
```

```bash
echo "Second Done"
```
- **Expected Result:**
  - Block 1 shows status "running".
  - Block 2 shows status "queued(1)".
  - After 5 seconds, Block 1 finishes, then Block 2 executes immediately.

2. **Queue Deletion**

```bash
sleep 10
```

```bash
echo "Hidden"
```

```bash
echo "Third"
```
- **Instructions:** While Block 1 is "running", enter Selection Mode (`s`), highlight the "Hidden" block, and delete it (`x`).
- **Expected Result:**
  - The "Hidden" block is removed from the UI and the server queue.
  - When Block 1 finishes, the "Third" block executes next.

---

## 3. Interactive PTY & CONTROL Mode

**Objective:** Verify that interactive terminal applications work correctly within Neptune.

1. **`top` Interaction**

```bash
top
```
- **Instructions:** Enter Selection Mode (`s`), highlight the `top` block, and press `i` to enter **CONTROL** mode. Press `q` to quit `top`.
- **Expected Result:** The application should respond to the keypress and exit, returning the block to a finished state.

2. **`less` Scrolling**

```bash
man bash
```
- **Instructions:** Enter **CONTROL** mode. Use `Up/Down` arrow keys to scroll. Press `q` to exit.
- **Expected Result:** Scrolling should be smooth and the PTY should capture all escape sequences.

3. **`nano` Editing**

```bash
nano test_file.txt
```
- **Instructions:** Enter **CONTROL** mode. Type some text, then `Ctrl+O`, `Enter`, `Ctrl+X`.
- **Expected Result:** The file should be saved and `nano` should exit.

---

## 4. Block Termination & Signal Handling

**Objective:** Verify that Neptune can gracefully stop running processes.

1. **Manual Stop (SIGTERM)**

```bash
sleep 100
```
- **Instructions:** In Selection Mode (`s`), highlight the block and press `x` (Delete).
- **Expected Result:** The process is killed and the block is removed.

2. **Broken Pipe / Syntax Error Recovery**

```bash
for i in {1..5} do echo $i
```
- **Expected Result:** The shell should report a syntax error (missing semicolon), but the session should remain alive for subsequent blocks.

---

## 5. Collaboration & Locking

**Objective:** Verify real-time synchronization and concurrency control between multiple clients.

### Creative Setup: Multi-Client testing via `tmux`
You can test multi-client behavior inside a single Neptune session!

```bash
tmux
```
- **Instructions:**
  1. Enter **CONTROL** mode in the tmux block.
  2. Split the window (`Ctrl+B`, `"`).
  3. In the top pane, run a Neptune client: `python3 client.py`
  4. In the bottom pane, run another Neptune client: `python3 client.py`
  5. Now you have two clients connected to the same server, visible at once.

1. **Real-time Synchronization**
   - Press `;` in Client A to enter NOTE mode and type some text.
   - **Expected Result:** The note appears in Client B.

2. **Editing Lock**
   - In Client A, enter Selection Mode (`s`) and press `e` to edit a block.
   - **Expected Result:**
     - Client B sees a colored right border on that block, indicating it is **LOCKED**.
     - If Client B tries to edit the same block, they should see a "Locked" notification.

3. **Global Reordering**
   - In Client A, move a block up (`Ctrl+Up`).
   - **Expected Result:** The block moves up in the UI of both Client A and Client B.

---

## 6. Cleanup

**Objective:** Ensure the test environment is reset.

- Press `:` to enter CMD mode and type `clear`.
- **Expected Result:** All blocks are removed and the session is reset to a blank state.

---

## 7. Filtering & Navigation

**Objective:** Verify that the filtering system and navigation modes work correctly with large amounts of data.

1. **Fuzzy Filtering**
   - **Instructions:**
     1. Create several Note and Command blocks with varying content.
     2. Press `Ctrl+F` to open the filter bar.
     3. Type a query that matches only a few blocks (e.g., a specific word).
   - **Expected Result:**
     - Only matching blocks remain visible.
     - Filtering is snappy and doesn't lag (due to debouncing and caching).
     - Press `Enter` in the filter bar to commit the filter and return to focus the bottom dock.
     - Press `Ctrl+G` to clear the filter and hide the bar immediately.

2. **Selection Mode Navigation with Filtering**
   - **Instructions:**
     1. Apply a filter so some blocks are hidden.
     2. Enter Selection Mode (`s`).
     3. Use `j/k` to navigate.
   - **Expected Result:** The focus should only move between **visible** blocks, skipping the hidden ones.

3. **Block Insertion (Selection Mode)**
   - **Instructions:**
     1. Enter Selection Mode (`s`).
     2. Highlight a block in the middle of the notebook.
     3. Press `!` to enter BASH mode.
     4. Type a command and press `Enter`.
   - **Expected Result:** The new block is inserted **directly below** the previously highlighted block, not at the end.

---

## 8. Performance & UI Stability

**Objective:** Verify that optimizations don't break UI correctness.

1. **Dynamic Resizing**
   - **Instructions:** Run a command that produces output line-by-line (e.g., `for i in {1..10}; do echo $i; sleep 0.5; done`).
   - **Expected Result:** The block should grow vertically to fit the new lines (up to the max-height limit).

2. **History Hiding (Lazy Rendering)**
   - **Instructions:**
     1. Generate a large amount of output in a block (e.g., `seq 1 200`).
     2. Create another block and focus it.
   - **Expected Result:**
     - The first block should show a hint like "... lines of history hidden ...".
     - When you focus the first block again (via Selection Mode or click), the full history should become visible.

3. **Rapid Output Stress**
   - **Instructions:** Run `cat /dev/urandom | base64 | head -c 10000`.
   - **Expected Result:** The TUI should remain responsive during the burst. You should still be able to switch modes or type in the input bar.
