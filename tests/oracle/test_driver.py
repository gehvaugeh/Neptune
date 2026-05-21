import pexpect
import pyte
import time
import sys
import re
import os
import difflib
from typing import List, Optional, Union

class NeptuneOracle:
    def __init__(self, command: str, rows: int = 24, cols: int = 80, cwd: Optional[str] = None):
        self.rows = rows
        self.cols = cols
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.Stream(self.screen)
        # We use a larger timeout for pexpect to avoid flaky tests
        # We also need to set the TERM environment variable to something standard
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        # Force a reasonable PYTHONPATH if we are running from a subdir
        if cwd:
            env["PYTHONPATH"] = cwd + (":" + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else "")

        self.child = pexpect.spawn(command, dimensions=(rows, cols), encoding='utf-8', timeout=15, env=env, cwd=cwd)

    def feed_stream(self):
        """Reads all available output from the process and feeds it to pyte."""
        try:
            # Non-blocking read
            while True:
                data = self.child.read_nonblocking(size=4096, timeout=0.1)
                if data:
                    self.stream.feed(data)
                else:
                    break
        except (pexpect.TIMEOUT, pexpect.EOF):
            pass

    def wait_for_idle(self, timeout=0.5):
        """Wait a bit for the output to settle."""
        time.sleep(timeout)
        self.feed_stream()

    def get_screen_snapshot(self) -> str:
        """Returns the current screen as a string with newlines."""
        if not isinstance(self.rows, int) or not isinstance(self.cols, int):
            raise TypeError("rows and cols must be integers")
        self.feed_stream()
        lines = []
        for y in range(self.rows):
            line = "".join(self.screen.buffer[y][x].data for x in range(self.cols))
            lines.append(line.rstrip())
        return "\n".join(lines)

    def send_input(self, action: str) -> None:
        """Translates human-readable action strings into ANSI sequences and sends them."""
        if not isinstance(action, str):
            raise TypeError(f"action must be a string, got {type(action)}")

        # Handle comma-separated sequences first for backward compatibility
        # e.g., "ctrl+p, 'test', enter"
        if "," in action:
            parts = [p.strip() for p in action.split(",")]
            for part in parts:
                self._send_single_action(part)
                time.sleep(0.1)
                self.feed_stream()
        else:
            self._send_single_action(action)
            time.sleep(0.1)
            self.feed_stream()

    def _send_single_action(self, action: str) -> None:
        """Processes a single action part, which could be a known key, quoted text, or <key> sequence."""
        # 1. Quoted literal
        if (action.startswith("'") and action.endswith("'")) or (action.startswith('"') and action.endswith('"')):
            self.child.send(action[1:-1])
            return

        # 2. Known single key (e.g., "esc", "enter", "ctrl+b")
        seq = self._map_key(action.lower())
        if seq:
            self.child.send(seq)
            return

        # 3. Sequence with <key> tags or pure literal text
        i = 0
        while i < len(action):
            if action[i] == '<':
                end = action.find('>', i)
                if end != -1:
                    key = action[i+1:end].lower()
                    seq = self._map_key(key)
                    if seq:
                        self.child.send(seq)
                        i = end + 1
                        time.sleep(0.1)
                        continue

            char = action[i]
            self.child.send(char)
            i += 1

            # If it's a mode trigger, wait a bit for Neptune to focus the input field
            if char in ("!", ":", ";", "s"):
                time.sleep(0.5) # Increased for Termux stability
            elif char == "\x1b": # Escape
                time.sleep(0.2)
            else:
                time.sleep(0.05) # Slower typing for stability

    def _map_key(self, key: str) -> str:
        key_map = {
            "enter": "\r",
            "return": "\r",
            "backspace": "\x7f",
            "tab": "\t",
            "esc": "\x1b",
            "escape": "\x1b",
            "up": "\x1b[A",
            "down": "\x1b[B",
            "right": "\x1b[C",
            "left": "\x1b[D",
            "home": "\x1b[H",
            "end": "\x1b[F",
            "pageup": "\x1b[5~",
            "pagedown": "\x1b[6~",
            "delete": "\x1b[3~",
            "space": " ",
            # Enhanced navigation keys (matches common terminal expectations)
            "ctrl+up": "\x1b[1;5A",
            "ctrl+down": "\x1b[1;5B",
            "alt+up": "\x1b[1;3A",
            "alt+down": "\x1b[1;3B",
        }

        if key in key_map:
            return key_map[key]

        # Handle ctrl+<key>
        ctrl_match = re.match(r"ctrl\+([a-z])", key)
        if ctrl_match:
            char = ctrl_match.group(1)
            return chr(ord(char) - ord('a') + 1)

        # Handle alt+<key>
        alt_match = re.match(r"alt\+([a-z])", key)
        if alt_match:
            char = alt_match.group(1)
            return "\x1b" + char

        return ""

    def run_notebook(self, filepath: str):
        print(f"--- Starting Notebook: {filepath} ---")
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            return

        with open(filepath, "r") as f:
            content = f.read()

        lines = content.splitlines()
        in_bash_block = False
        bash_content = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped and not in_bash_block:
                continue

            # Handle Bash Code Blocks
            if stripped.startswith("```bash"):
                in_bash_block = True
                bash_content = []
                continue
            elif stripped.startswith("```") and in_bash_block:
                in_bash_block = False
                command = "\n".join(bash_content)
                print(f"[Line {i+1}] Executing Bash Block:\n{command}")
                # Enter Bash mode
                self.send_input("!")
                time.sleep(0.1)
                self.child.send(command + "\r")
                self.wait_for_idle(1.5) # Commands can take longer
                continue

            if in_bash_block:
                bash_content.append(line)
                continue

            # Handle Actions
            if stripped.startswith("Action:"):
                action = stripped[len("Action:"):].strip()
                print(f"[Line {i+1}] Action: {action}")
                self.send_input(action)
                self.wait_for_idle(0.3)

            # Handle Commands
            elif stripped.startswith("Command:"):
                cmd = stripped[len("Command:"):].strip()
                print(f"[Line {i+1}] Command: {cmd}")
                self.child.send(cmd + "\r")
                self.wait_for_idle(0.5)

            # Handle Expectations
            elif stripped.startswith("Expect:"):
                expected = stripped[len("Expect:"):].strip()
                print(f"[Line {i+1}] Expect: {expected}")
                # We might need to wait a bit more for some UI updates
                success = False
                for _ in range(10): # Retry for up to 5 seconds
                    self.feed_stream()
                    snapshot = self.get_screen_snapshot()

                    # Try as Regex first, fallback to literal string
                    try:
                        if re.search(expected, snapshot, re.DOTALL):
                            success = True
                            break
                    except re.error:
                        if expected in snapshot:
                            success = True
                            break

                    time.sleep(0.5)

                if not success:
                    snapshot = self.get_screen_snapshot()
                    print(f"\nERROR: Expectation failed at line {i+1}!")
                    print(f"Expected: '{expected}'")
                    print("\n--- CURRENT SCREEN SNAPSHOT ---")
                    print(snapshot)
                    print("--- END OF SNAPSHOT ---")

                    print("\n--- DIFF (Approximate) ---")
                    # Full screen diff is huge, but we can show lines that are close or just the raw snapshot
                    # Let's show which lines contain what
                    exp_lines = expected.splitlines()
                    snap_lines = snapshot.splitlines()

                    diff = difflib.unified_diff(
                        exp_lines,
                        snap_lines,
                        fromfile="Expected",
                        tofile="Actual Screen",
                        lineterm=""
                    )
                    for dline in diff:
                        print(dline)

                    # Terminate process and exit with error
                    self.child.terminate(force=True)
                    sys.exit(1)
                else:
                    print("SUCCESS: Match found.")

        print(f"--- Notebook {filepath} completed successfully ---")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Neptune Oracle TUI Testing Framework")
    parser.add_argument("target", nargs="?", help="Notebook path OR Command (if --repl is used)")
    parser.add_argument("cmd", nargs="?", help="Command to start Neptune (if target is a notebook)")
    parser.add_argument("--repl", action="store_true", help="Start in interactive REPL mode")

    args = parser.parse_args()

    if args.repl:
        # In REPL mode, 'target' is the command if provided, else use default
        cmd = args.target if args.target else "python3 main.py all --clean-history"
        print(f"--- Starting Interactive Oracle REPL (Target: {cmd}) ---")
        oracle = NeptuneOracle(cmd)
        try:
            oracle.wait_for_idle(3.0)
            while True:
                print("\n" + "="*80)
                print(oracle.get_screen_snapshot())
                print("="*80)
                try:
                    user_input = input("\nOracle Action (or 'exit'): ").strip()
                    if user_input.lower() == 'exit':
                        break
                    if not user_input:
                        oracle.feed_stream()
                        continue

                    oracle.send_input(user_input)
                    oracle.wait_for_idle(0.5)
                except (EOFError, KeyboardInterrupt):
                    break
        finally:
            oracle.child.terminate(force=True)
            print("\nOracle session terminated.")
    elif args.target:
        notebook_path = args.target
        cmd = args.cmd if args.cmd else "python3 main.py all --clean-history"
        oracle = NeptuneOracle(cmd)
        try:
            # Give Neptune some time to initialize
            oracle.wait_for_idle(3.0)
            oracle.run_notebook(notebook_path)
        finally:
            oracle.child.terminate(force=True)
    else:
        parser.print_help()
        sys.exit(1)
