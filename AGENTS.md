# Neptune Development Guidelines

## Testing and Quality Assurance

*   **Zero Regression Policy**: Every new feature, bug fix, or behavioral change MUST be accompanied by a corresponding test case in the blackbox test suite (`tests/blackbox/run_blackbox_tests.py`). This is mandatory to prevent regressions in the TUI environment.
*   **Blackbox Verification**: Automated verification using the `NeptuneOracle` is the primary method for ensuring system integrity. If a change modifies the UI, focus behavior, or process lifecycle, it must be reflected in the oracle assertions.
*   **Terminal Statefulness**: Ensure that changes to PTY management do not break the persistence of the shell environment (directory changes, environment variables) across command blocks.
*   **Process Lifecycle**: Always verify that processes are correctly terminated on block deletion and PTY destruction. Use the SIGTERM-SIGKILL sequence for reliability.

## PTY Management

*   **Numeric UIDs**: All PTYs must be managed using stable numeric UIDs starting from 0. `UID 0` is reserved for the permanent local master shell.
*   **Encapsulation**: PTY UI logic (modals, pickers) should reside in `pty_manager_ui.py`.
*   **Control Mode**: Interactive terminal input (CONTROL mode) must support standard ANSI sequences and signal generation (e.g., Ctrl+C for SIGINT).

## UI and Focus

*   **Modal Behavior**: Modals should handle their own key events (like Escape for dismissal) and allow standard Textual focus navigation (Tab/Shift+Tab) without interference from the main App key handlers.
