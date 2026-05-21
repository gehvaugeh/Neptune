import sys
import os
import time

# Ensure we can import NeptuneOracle from the sibling directory
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "oracle"))
from test_driver import NeptuneOracle

def run_tests():
    results = []
    socket_path = "test.sock"
    if os.path.exists(socket_path):
        try: os.remove(socket_path)
        except: pass

    # main.py is in the root directory
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    main_path = os.path.join(root_dir, "main.py")
    cmd = f"python3 {main_path} all --clean-history -s {socket_path}"
    oracle = NeptuneOracle(cmd)

    def record(desc, status, details=""):
        results.append({"description": desc, "result": status, "details": details})
        print(f"{status}: {desc} {'(' + details + ')' if details else ''}")

    def assert_screen(expected, desc, timeout=15.0):
        start = time.time()
        while time.time() - start < timeout:
            oracle.feed_stream()
            snapshot = oracle.get_screen_snapshot()
            if expected in snapshot:
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
            if forbidden not in snapshot:
                record(desc, "PASS")
                return True
            time.sleep(0.5)
        record(desc, "FAIL", f"Still found '{forbidden}' on screen")
        return False

    try:
        print(f"Starting Neptune (Socket: {socket_path})...")
        oracle.wait_for_idle(5.0)

        # 1. Startup
        assert_screen("Neptune Multi-User", "Verify Startup Header")

        # 2. BASH Echo
        print("Testing BASH Echo...")
        oracle.send_input("<esc>!echo OracleEcho <return>")
        assert_screen("OracleEcho", "Execute BASH Echo")

        # 3. Internal Help
        print("Testing Internal Help...")
        oracle.send_input("<esc>:help <return>")
        assert_screen("Commands:", "Internal Help Command")

        # 4. NOTE creation
        print("Testing Note...")
        oracle.send_input("<esc>;NoteMarker <return>")
        assert_screen("NoteMarker", "Create Note")

        # 5. Clear screen
        print("Cleaning up...")
        oracle.send_input("<esc>:clear <return>")
        oracle.wait_for_idle(3.0)

        # 6. Selection Navigation & Deletion
        print("Testing Selection Mode...")
        oracle.send_input("!echo AAA <return>")
        assert_screen("AAA", "Setup AAA")
        oracle.send_input("s")
        assert_screen("MODE: SELECTION", "Enter Selection Mode")
        oracle.send_input("x")
        assert_not_on_screen("AAA", "Delete block via Selection Mode")

        # 7. Block Reordering
        print("Testing Reordering...")
        oracle.send_input("<esc>!echo MoveMe <return>")
        assert_screen("MoveMe", "Setup MoveMe")
        oracle.send_input("s<ctrl+up>")
        oracle.wait_for_idle(1.5)
        assert_screen("MODE: SELECTION", "Reorder block (Ctrl+Up)")

        # 8. Autocomplete
        print("Testing Autocomplete...")
        oracle.send_input("<esc>!ls <tab>")
        assert_screen("PATH:", "Path Autocomplete Visibility")
        oracle.send_input("<esc>")

        # 9. Yank & Paste
        print("Testing Yank & Paste...")
        # Clear again for clean state
        oracle.send_input("<esc>:clear <return>")
        oracle.wait_for_idle(3.0)
        oracle.send_input("!echo YankMe <return>")
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
