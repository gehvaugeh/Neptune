# Neptune Test Suite (Manual)

This document contains a series of manual test cases to verify the core functionality of the Neptune collaborative notebook shell. These tests are designed to be performed by a human to ensure no regressions occur after code changes.

---

## 1. Session Persistence & Shared State

**Objective:** Verify that the environment state is preserved across different command blocks.

1. **Working Directory Persistence**
   - Create a BASH block: `mkdir -p test_dir && cd test_dir`
   - Create a second BASH block: `pwd`
   - **Expected Result:** The second block should output a path ending in `/test_dir`.

2. **Environment Variable Persistence**
   - Create a BASH block: `export NEPTUNE_TEST=123`
   - Create a second BASH block: `echo $NEPTUNE_TEST`
   - **Expected Result:** The second block should output `123`.

---

## 2. Command Queueing & Execution

**Objective:** Verify that commands are executed sequentially and status updates are broadcast.

1. **Sequential Execution**
   - Create a BASH block: `sleep 5 && echo "First Done"`
   - Immediately create a second BASH block: `echo "Second Done"`
   - **Expected Result:**
     - Block 1 shows status "running".
     - Block 2 shows status "queued(1)".
     - After 5 seconds, Block 1 finishes, then Block 2 executes immediately.

2. **Queue Deletion**
   - Create three BASH blocks:
     1. `sleep 10`
     2. `echo "Hidden"`
     3. `echo "Third"`
   - While Block 1 is "running", enter Selection Mode (`s`), highlight Block 2, and delete it (`x`).
   - **Expected Result:**
     - Block 2 is removed from the UI and the server queue.
     - When Block 1 finishes, Block 3 executes next.

---

## 3. Interactive PTY & CONTROL Mode

**Objective:** Verify that interactive terminal applications work correctly within Neptune.

1. **`top` Interaction**
   - Create a BASH block: `top`
   - Enter Selection Mode (`s`), highlight the `top` block, and press `i` to enter **CONTROL** mode.
   - Press `q` to quit `top`.
   - **Expected Result:** The application should respond to the keypress and exit, returning the block to a finished state.

2. **`less` Scrolling**
   - Create a BASH block: `man bash` (or any long file piped to `less`)
   - Enter **CONTROL** mode.
   - Use `Up/Down` arrow keys to scroll.
   - Press `q` to exit.
   - **Expected Result:** Scrolling should be smooth and the PTY should capture all escape sequences.

3. **`nano` Editing**
   - Create a BASH block: `nano test_file.txt`
   - Enter **CONTROL** mode.
   - Type some text, then `Ctrl+O`, `Enter`, `Ctrl+X`.
   - **Expected Result:** The file should be saved and `nano` should exit.

---

## 4. Block Termination & Signal Handling

**Objective:** Verify that Neptune can gracefully stop running processes.

1. **Manual Stop (SIGTERM)**
   - Create a BASH block: `sleep 100`
   - In Selection Mode (`s`), highlight the block and press `x` (Delete) or use the stop command if implemented.
   - **Expected Result:** The process is killed (server logs should show SIGTERM/SIGKILL) and the block is removed.

2. **Broken Pipe / Syntax Error Recovery**
   - Create a BASH block with invalid syntax: `for i in {1..5} do echo $i` (missing semicolon)
   - **Expected Result:** The shell should report the syntax error, but the session should remain alive for subsequent blocks.

---

## 5. Collaboration & Locking

**Objective:** Verify real-time synchronization and concurrency control between multiple clients.

### Creative Setup: Multi-Client testing via `tmux`
You can test multi-client behavior inside a single Neptune session!
1. Create a BASH block: `tmux`
2. Enter **CONTROL** mode.
3. Split the window (`Ctrl+B`, `"`).
4. In the top pane, run a Neptune client: `python3 client.py`
5. In the bottom pane, run another Neptune client: `python3 client.py`
6. Now you have two clients connected to the same server, visible at once.

1. **Real-time Synchronization**
   - Type a NOTE in Client A.
   - **Expected Result:** The note appears character-by-character in Client B (if live sync is enabled) or upon submission.

2. **Editing Lock**
   - In Client A, enter Selection Mode (`s`) and press `e` to edit a block.
   - **Expected Result:**
     - Client A enters edit mode.
     - Client B sees a colored right border on that block, indicating it is **LOCKED**.
     - If Client B tries to edit the same block, they should receive a notification: "Locked by [User]".

3. **Global Reordering**
   - In Client A, move a block up (`Ctrl+Up`).
   - **Expected Result:** The block moves up in the UI of both Client A and Client B simultaneously.

---

## 6. Cleanup

**Objective:** Ensure the test environment is reset.

- Create a CMD block: `:clear`
- **Expected Result:** All blocks are removed and the session is reset to a blank state.
