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
