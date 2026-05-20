# Neptune Testing Guide: Using the Oracle

This guide explains how to write and run test cases using the `neptune-oracle` framework. Following this guide for every new feature will ensure stability and help avoid regressions in the Neptune TUI.

## Overview

The `neptune-oracle` framework provides two ways to test Neptune:
1. **Markdown Notebooks**: Define steps in a simple `.md` or `.neptune` file. Great for defining manual-like workflows.
2. **Python Library**: Use the `NeptuneOracle` class in Python scripts for advanced programmatic control and complex assertions.

---

## 1. Writing Markdown-Based Tests

Test notebooks are standard Markdown files that use special triggers to interact with the Neptune process.

### Syntax Triggers

| Trigger | Description | Example |
|---------|-------------|---------|
| `Action:` | Simulates keystrokes. Supports `<key>` tags. | `Action: !ls <return>` |
| `Command:` | Types text and appends `<return>`. | `Command: help` |
| `Expect:` | Verifies that a string or regex exists on screen. | `Expect: MODE: NORMAL` |
| ` ```bash ` | Executes a block of bash code instantly. | See example below. |

### Example Test Case (`my_feature.md`)

```markdown
# Test Feature: Note Creation

Expect: Neptune Multi-User

Action: ;# This is a new note <return>
Expect: This is a new note

Action: s
Expect: MODE: SELECTION

Action: x
Expect: [No longer contains the note content]
```

### Running the Notebook

```bash
python3 test_driver.py my_feature.md
```

---

## 2. Programmatic Testing (Python Library)

For complex features (like block reordering or multi-step logic), it is recommended to use the `NeptuneOracle` class directly in a Python script.

### Basic Setup

```python
from test_driver import NeptuneOracle
import time

def test_my_feature():
    # Start Neptune with a clean state
    oracle = NeptuneOracle("python3 main.py all --clean-history")
    try:
        oracle.wait_for_idle(5.0) # Allow Neptune to start

        # 1. Send input
        oracle.send_input("!echo 'Regression Test' <return>")

        # 2. Assert screen state (use a loop to avoid flakiness)
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

## 3. Interaction Best Practices

### Key Sequences
In `Action:`, you can mix literal text and key tags:
- `Action: !ls -la <return>`
- `Action: s<ctrl+up>`
- `Action: <esc>:` (Return to normal, enter CMD mode)

### Avoiding Flakiness
TUI testing is sensitive to timing because rendering is asynchronous.
- **Always** use `wait_for_idle()` after complex inputs.
- **Prefer** retry loops for expectations (like the `assert_screen` helper in `run_blackbox_tests.py`).
- **Use unique identifiers**: When testing `echo`, use a unique string like `echo "TEST-ID-99"` to ensure you aren't matching a previous command's output.

### Regression Prevention checklist
Whenever you implement a new feature:
1. [ ] Add a new `.md` test case in `tests/notebooks/`.
2. [ ] If the feature is complex, add a case to `run_blackbox_tests.py`.
3. [ ] Run `python3 run_blackbox_tests.py` and verify all cases pass.
4. [ ] Check `blackbox_test_results.md` to confirm the feature is documented as verified.

---

## 4. Debugging Tests

If a test fails, the Oracle will provide:
1. **The Line Number** of the failure.
2. **A Snapshot** of the 80x24 terminal screen at the moment of failure.
3. **A Unified Diff** between the expected string and the actual screen content.

You can also use the **Interactive REPL** to develop tests:
```bash
python3 test_driver.py --repl
```
In the REPL, you can type actions and see the screen update in real-time, helping you find the exact sequence of keys needed for your test case.
