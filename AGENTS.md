# Neptune Agent Onboarding & Development Guide

Welcome to the Neptune project. This document serves as the primary technical guide for autonomous agents and developers working on this codebase.

## 1. Project Philosophy
- **No Vibe-Coding**: Always use explicit type hints and type checks.
- **Robustness First**: Neptune operates in a multi-user, multi-process environment. Handle exceptions gracefully and use adaptive timing for UI interactions.
- **Environment Isolation**: Always use specific socket paths (e.g., `test.sock`) for testing to avoid clashing with other instances.

## 2. Testing Framework: Neptune Oracle

Neptune uses the **Neptune Oracle** system for automated TUI verification. It leverages `pyte` for virtual terminal emulation and `pexpect` for process control.

### Core Testing Workflow
Whenever you implement a new feature or refactor existing logic, you **MUST** verify it using the blackbox suite.

#### Running Blackbox Tests
Execute the autonomous verification suite from the root directory:
```bash
python3 tests/blackbox/run_blackbox_tests.py
```
This script validates core features (BASH, CMD, NOTE, SELECTION, etc.) and generates a report in `tests/blackbox/blackbox_test_results.md`.

#### Adding New Test Cases
Add your feature verification logic to `tests/blackbox/run_blackbox_tests.py` using the `NeptuneOracle` library.

**Example Pattern:**
```python
import sys
import os
sys.path.append("tests/oracle")
from test_driver import NeptuneOracle
import time

def test_new_feature():
    # 1. Spawn Neptune with a clean state and local socket
    oracle = NeptuneOracle("python3 main.py all --clean-history -s test.sock")
    try:
        oracle.wait_for_idle(5.0)

        # 2. Simulate interaction
        oracle.send_input("!echo 'Verifying Feature' <return>")

        # 3. Assert screen state with a retry loop (Critical for TUI stability)
        found = False
        for _ in range(10):
            oracle.feed_stream()
            if "Verifying Feature" in oracle.get_screen_snapshot():
                found = True
                break
            time.sleep(0.5)

        assert found, "Feature verification failed!"
    finally:
        oracle.child.terminate(force=True)
```

### Interaction Best Practices
- **Key Sequences**: Use `<key>` tags in `oracle.send_input()` (e.g., `!ls <tab>`, `s<ctrl+up>`, `<esc>:`).
- **Escape often**: Prepend your sequences with `<esc><esc>` to ensure you start from a known state (NORMAL mode).
- **Clear State**: Use the `:clear` command between complex test steps to keep the terminal buffer readable.

### Debugging Tests
If a test fails or you need to find the correct key sequence, use the **Interactive Oracle REPL**:
```bash
python3 tests/oracle/test_driver.py --repl
```
This allows you to type actions and see the exact terminal screen snapshots in real-time.

---

## 3. Directory Structure
- `tests/oracle/`: The `NeptuneOracle` driver engine.
- `tests/blackbox/`: Automated system-level verification scripts and reports.
- `doc/`: Detailed architectural documentation for server, client, and protocol.

## 4. Regression Prevention Checklist
Before submitting any code change:
1. [ ] Run `python3 tests/blackbox/run_blackbox_tests.py`.
2. [ ] Verify that all 11+ test cases in the report are marked as `PASS`.
3. [ ] If you added a feature, ensure it has a corresponding case in the suite.
4. [ ] Ensure no temporary files (`test.sock`, `history.txt`, `.log` files) are left in the repository.
