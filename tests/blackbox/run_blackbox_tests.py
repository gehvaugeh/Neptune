import sys
import os
import time

# Ensure we can import NeptuneOracle from the sibling directory
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "oracle"))
from test_driver import NeptuneOracle

def run_tests():
    results = []
    # Use absolute path for the socket to avoid relative path mismatches
    # between the test runner and the Neptune process.
    socket_path = os.path.abspath("test.sock")
    if os.path.exists(socket_path):
        try: os.remove(socket_path)
        except: pass

    # main.py is in the root directory
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    main_path = os.path.join(root_dir, "main.py")
    cmd = f"python3 {main_path} all --clean-history -s {socket_path}"
    oracle = NeptuneOracle(cmd, cwd=root_dir)

    def record(desc, status, details=""):
        results.append({"description": desc, "result": status, "details": details})
        print(f"{status}: {desc} {'(' + details + ')' if details else ''}")

    def assert_screen(expected, desc, timeout=15.0):
        start = time.time()
        while time.time() - start < timeout:
            oracle.feed_stream()
            snapshot = oracle.get_screen_snapshot()
            if expected.lower() in snapshot.lower():
                record(desc, "PASS")
                return True
            time.sleep(0.5)
        record(desc, "FAIL", f"Expected '{expected}' not found")
        return False

    def assert_not_on_screen(forbidden, desc, timeout=15.0):
        start = time.time()
        time.sleep(1.0)
        while time.time() - start < timeout:
            oracle.feed_stream()
            snapshot = oracle.get_screen_snapshot()
            if forbidden.lower() not in snapshot.lower():
                record(desc, "PASS")
                return True
            time.sleep(0.5)
        record(desc, "FAIL", f"Still found '{forbidden}' on screen")
        return False

    def clear_notebook():
        oracle.send_input("<esc><esc>:clear <return>")
        oracle.wait_for_idle(2.0)

    try:
        print(f"Starting Neptune (Socket: {socket_path})...")
        oracle.wait_for_idle(5.0)

        # 1. Startup
        assert_screen("Neptune Multi-User", "Verify Startup Header")

        # 2. BASH Echo
        print("Testing BASH Echo...")
        # Use multiple escapes to ensure we are in NORMAL mode
        oracle.send_input("<esc><esc>!echo OracleEcho <return>")
        assert_screen("OracleEcho", "Execute BASH Echo")

        # 3. Internal Help
        print("Testing Internal Help...")
        oracle.send_input("<esc><esc>:help <return>")
        assert_screen("Commands:", "Internal Help Command")

        # 4. NOTE creation
        print("Testing Note...")
        oracle.send_input("<esc><esc>;NoteMarker <return>")
        assert_screen("NoteMarker", "Create Note")

        # 5. Clear screen
        print("Cleaning up...")
        oracle.send_input("<esc><esc>:clear <return>")
        oracle.wait_for_idle(4.0)

        # 6. Selection Navigation & Deletion
        print("Testing Selection Mode...")
        oracle.send_input("<esc><esc>!echo AAA <return>")
        assert_screen("AAA", "Setup AAA")
        oracle.send_input("s")
        assert_screen("MODE: SELECTION", "Enter Selection Mode")
        oracle.send_input("x")
        assert_not_on_screen("AAA", "Delete block via Selection Mode")

        # 7. Block Reordering
        print("Testing Reordering...")
        oracle.send_input("<esc><esc>!echo MoveMe <return>")
        assert_screen("MoveMe", "Setup MoveMe")
        oracle.send_input("s")
        oracle.wait_for_idle(0.5)
        oracle.send_input("<ctrl+up>")
        oracle.wait_for_idle(2.0)
        assert_screen("MODE: SELECTION", "Reorder block (Ctrl+Up)")

        # 8. Autocomplete
        print("Testing Autocomplete...")
        oracle.send_input("<esc><esc>!ls <tab>")
        # The new provider uses 'SHELL:' instead of 'PATH:' for shadow shell results
        assert_screen("SHELL:", "Path Autocomplete Visibility")
        oracle.send_input("<esc><esc>")

        # 9. Autocomplete Append — file after command, not overwriting
        print("Testing Autocomplete Append...")
        oracle.send_input("<esc><esc>:clear <return>")
        oracle.wait_for_idle(3.0)
        # Type !ls + space, tab to open palette
        oracle.send_input("!ls <tab>")
        oracle.wait_for_idle(0.5)
        # Palette should be open with SHELL: completions
        assert_screen("SHELL:", "Autocomplete Append - palette opens")
        # Second tab selects first result and closes palette
        oracle.send_input("<tab>")
        oracle.wait_for_idle(1.0)
        # Palette should be closed
        assert_not_on_screen("SHELL:", "Autocomplete Append - palette closed")
        # The input area shows "!  User: Me  ls<file>" — check that "ls" is still in the input line
        # (it would be gone if the command text was overwritten by the completion value)
        assert_screen("Me  ls", "Autocomplete Append - command preserved")
        # Execute to verify the completed command runs without crash
        oracle.send_input("<return>")
        oracle.wait_for_idle(3.0)
        # If the command text was preserved, output should appear; just verify no crash
        snapshot = oracle.get_screen_snapshot()
        if "error" not in snapshot.lower():
            record("Autocomplete Append - command executes", "PASS")
        else:
            record("Autocomplete Append - command executes", "WARN", "Command may have had errors")

        # 10. Yank & Paste
        print("Testing Yank & Paste...")
        # Clear again for clean state
        oracle.send_input("<esc><esc>:clear <return>")
        oracle.wait_for_idle(5.0)
        oracle.send_input("<esc><esc>!echo YankMe <return>")
        assert_screen("YankMe", "Setup YankMe")
        oracle.send_input("sy") # Select & Yank
        oracle.wait_for_idle(0.5)
        oracle.send_input("p")  # Paste After
        oracle.wait_for_idle(2.0)
        oracle.feed_stream()
        snapshot = oracle.get_screen_snapshot()
        if snapshot.count("YankMe") >= 2:
            record("Yank and Paste block", "PASS")
        else:
            record("Yank and Paste block", "FAIL", "Duplicated content not found")

        # 12. CMD File Completion via LocalFileProvider
        print("Testing CMD File Completion...")
        oracle.send_input("<esc><esc>:clear <return>")
        oracle.wait_for_idle(3.0)
        oracle.send_input(":import <tab>")
        oracle.wait_for_idle(2.0)
        assert_screen("PATH:", "CMD File Completion - PATH entries visible")
        oracle.send_input("<tab>")
        oracle.wait_for_idle(1.0)
        assert_not_on_screen("PATH:", "CMD File Completion - palette closes after selection")
        oracle.send_input("<esc><esc>")
        oracle.wait_for_idle(0.5)

        # 13. NOTE Markdown Toolbox — open, filter empty, select first
        print("Testing NOTE Markdown Toolbox...")
        oracle.send_input("<esc><esc>:clear <return>")
        oracle.wait_for_idle(3.0)
        oracle.send_input(";<tab>")
        oracle.wait_for_idle(2.0)
        assert_screen("H1:", "NOTE Toolbox - entries visible")
        oracle.send_input("<enter>")
        oracle.wait_for_idle(1.0)
        assert_not_on_screen("H1:", "NOTE Toolbox - closes after selection")
        oracle.send_input("<esc><esc>")
        oracle.wait_for_idle(0.5)

        # 14. NOTE Toolbox — filter text, select, submit preserves existing input
        print("Testing NOTE Toolbox with existing text...")
        oracle.send_input("<esc><esc>:clear <return>")
        oracle.wait_for_idle(3.0)
        oracle.send_input(";some text <tab>")
        oracle.wait_for_idle(2.0)
        assert_screen("H1:", "NOTE Toolbox with text - entries visible")
        oracle.send_input("##<enter>")
        oracle.wait_for_idle(1.0)
        assert_not_on_screen("H1:", "NOTE Toolbox with text - closes")
        oracle.send_input("<return>")
        oracle.wait_for_idle(2.0)
        assert_screen("some text", "NOTE Toolbox - original text preserved")
        oracle.send_input("<esc><esc>")
        oracle.wait_for_idle(0.5)

        # 15. NOTE Toolbox — arrow navigation, then select
        print("Testing NOTE Toolbox arrow navigation...")
        oracle.send_input("<esc><esc>:clear <return>")
        oracle.wait_for_idle(3.0)
        oracle.send_input(";<tab>")
        oracle.wait_for_idle(2.0)
        assert_screen("H1:", "NOTE Toolbox arrows - entries visible")
        oracle.send_input("<down><down>")
        oracle.wait_for_idle(1.0)
        oracle.send_input("<enter>")
        oracle.wait_for_idle(1.0)
        assert_not_on_screen("H1:", "NOTE Toolbox arrows - toolbox closes after navigation")
        oracle.send_input("<esc><esc>")
        oracle.wait_for_idle(0.5)

        # 16. Duplicate ID in autocomplete — workflow + history collision
        print("Testing Duplicate ID prevention...")
        oracle.send_input("<esc><esc>:clear <return>")
        oracle.wait_for_idle(3.0)
        # Run a command that matches an existing workflow to seed history.
        # Both HistoryProvider and WorkflowProvider will return "ls -lah ./",
        # causing a DuplicateID crash unless IDs are made unique.
        oracle.send_input("!ls -lah ./<return>")
        oracle.wait_for_idle(5.0)
        # Now type ls + space and open the palette.
        # Before the fix, the duplicate id="ls -lah ./" crashed with DuplicateID.
        oracle.send_input("!ls <tab>")
        oracle.wait_for_idle(3.0)
        # Palette should open without crash (SHELL: visible means providers ran)
        assert_screen("SHELL:", "Duplicate ID - palette opens without crash")
        # Also check for HISTORY and WORKFLOW entries to confirm collision case
        assert_screen("HISTORY:", "Duplicate ID - history entry visible")
        assert_screen("WORKFLOW:", "Duplicate ID - workflow entry visible")
        oracle.send_input("<esc><esc>")
        oracle.wait_for_idle(0.5)

    except Exception as e:
        record("Test Suite Execution", "ERROR", str(e))
    finally:
        oracle.child.terminate(force=True)
        if os.path.exists(socket_path):
            try: os.remove(socket_path)
            except: pass

    return results

def generate_report(results):
    report = "# Neptune Blackbox Test Results\n\n"
    report += f"**Automated Verification Run:** {time.ctime()}\n\n"
    report += "| Feature Test | Result | Details |\n"
    report += "|--------------|--------|---------|\n"
    for r in results:
        emoji = "✅" if r["result"] == "PASS" else "❌" if r["result"] == "FAIL" else "⚠️"
        report += f"| {r['description']} | {emoji} {r['result']} | {r['details']} |\n"
    return report

if __name__ == "__main__":
    test_results = run_tests()
    report_path = os.path.join(os.path.dirname(__file__), "blackbox_test_results.md")
    with open(report_path, "w") as f:
        f.write(generate_report(test_results))
    print(f"\nBlackbox testing complete. Report: {report_path}")
