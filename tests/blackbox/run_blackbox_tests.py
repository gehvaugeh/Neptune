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

        # 9. Yank & Paste
        print("Testing Yank & Paste...")
        # Clear again for clean state
        oracle.send_input("<esc><esc>:clear <return>")
        oracle.wait_for_idle(4.0)
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
