# Neptune Development Guidelines

## Testing and Quality Assurance

*   **Zero Regression Policy**: Every new feature, bug fix, or behavioral change MUST be accompanied by a corresponding test case in the blackbox test suite (`tests/blackbox/run_blackbox_tests.py`).
*   **Blackbox Verification**: Automated verification using the `NeptuneOracle` is the primary method for ensuring system integrity. If a change modifies the UI or process lifecycle, it must be reflected in the oracle assertions.
*   **Terminal Statefulness**: Ensure that changes to PTY management do not break the persistence of the shell environment (directory changes, environment variables) across command blocks.
*   **Process Lifecycle**: Always verify that processes are correctly terminated on block deletion and PTY destruction. Use the SIGTERM-SIGKILL sequence for reliability.

## PTY Management

*   **Numeric UIDs**: All PTYs must be managed using stable numeric UIDs starting from 0. `UID 0` is reserved for the permanent local master shell.
*   **Encapsulation**: PTY UI logic (modals, pickers) should reside in `pty_manager_ui.py`.
*   **Control Mode**: Interactive terminal input (CONTROL mode) must support standard ANSI sequences and signal generation (e.g., Ctrl+C for SIGINT).
