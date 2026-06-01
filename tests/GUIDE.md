# Neptune Testing Guide: Using the Oracle

This guide explains how to write and run automated TUI tests using the `neptune-oracle` framework. Following this guide for every new feature will ensure stability and help avoid regressions in the Neptune TUI.

## Overview

The `neptune-oracle` framework provides a powerful way to test Neptune programmatically:
- **Python Library**: Use the `NeptuneOracle` class in Python scripts (like `tests/blackbox/run_blackbox_tests.py`) for full programmatic control and complex assertions.

---

## 1. Programmatic Testing (Python Library)

For every new feature, you should add a test case to the blackbox verification suite.

### Basic Setup

```python
import sys
import os
sys.path.append("tests/oracle")
from test_driver import NeptuneOracle
import time

def test_my_feature():
    # Start Neptune with a clean state and local socket
    oracle = NeptuneOracle("python3 main.py all --clean-history -s test.sock")
    try:
        oracle.wait_for_idle(5.0) # Allow Neptune to start

        # 1. Send input
        oracle.send_input("!echo 'Regression Test' <return>")

        # 2. Assert screen state (use a retry loop to avoid flakiness)
        found = False
        for _ in range(10):
            oracle.feed_stream()
            if "Regression Test" in oracle.get_screen_snapshot():
                found = True
                break
            time.sleep(0.5)

        assert found, "Regression Test string not found on screen!"
        print("Feature Test PASSED")

    finally:
        oracle.child.terminate(force=True)
```

---

## 2. Interaction Best Practices

### Key Sequences
Using `oracle.send_input()`, you can mix literal text and key tags:
- `!ls -la <return>`
- `s<ctrl+up>`
- `<esc>:` (Return to normal, enter CMD mode)

### Avoiding Flakiness
TUI testing is sensitive to timing because rendering is asynchronous.
- **Always** use `wait_for_idle()` after complex inputs.
- **Prefer** retry loops for expectations.
- **Use unique identifiers**: When testing commands, use unique strings to ensure you aren't matching a previous command's output.

### Regression Prevention workflow
Whenever you implement a new feature:
1. Add a new test case to `tests/blackbox/run_blackbox_tests.py`.
2. Run `python3 tests/blackbox/run_blackbox_tests.py`.
3. Verify that the result is correctly recorded in `tests/blackbox/blackbox_test_results.md`.

---

## 3. Debugging Tests

If a test fails, the Oracle can be used in **Interactive REPL** mode to find the correct key sequences:
```bash
python3 tests/oracle/test_driver.py --repl
```
In the REPL, you can type actions and see the screen update in real-time.
