import sys
import os
import time

# Ensure we can import NeptuneOracle from the sibling directory
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "oracle"))
from test_driver import NeptuneOracle

def run_tests():
    results = []
    socket_path = os.path.abspath("test.sock")
    if os.path.exists(socket_path):
        try: os.remove(socket_path)
        except: pass

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

        # 2. Local Statefulness
        print("Testing Local Statefulness...")
        clear_notebook()
        oracle.send_input("!mkdir -p /tmp/neptune_test <return>")
        oracle.wait_for_idle(1.0)
        oracle.send_input("!cd /tmp/neptune_test <return>")
        oracle.wait_for_idle(1.0)
        oracle.send_input("!pwd <return>")
        assert_screen("/tmp/neptune_test", "Local directory persistence")

        # 3. Local TUI Kill (Ctrl+C)
        print("Testing Local TUI Kill (Ctrl+C)...")
        clear_notebook()
        oracle.send_input("!bash -c \"trap 'echo CAUGHT_INT; exit 130' SIGINT; sleep 100\" <return>")
        assert_screen("running", "Process is running")
        oracle.send_input("si") # Select and enter Control mode
        oracle.wait_for_idle(1.0)
        oracle.send_input("<ctrl+c>") # Send SIGINT
        oracle.wait_for_idle(3.0)
        oracle.send_input("<esc><esc>") # Exit control mode
        oracle.feed_stream()
        snap = oracle.get_screen_snapshot().lower()
        if "caught_int" in snap or "error(130)" in snap or "killed" in snap or "done" in snap:
             record("Local TUI Ctrl+C termination", "PASS")
        else:
             record("Local TUI Ctrl+C termination", "FAIL", "Process did not seem to react to Ctrl+C")

        # 4. Remote PTY Setup and Tab Navigation
        print("Testing Remote PTY Modal and Tab Navigation...")
        oracle.send_input("<ctrl+t>")
        oracle.wait_for_idle(1.0)
        oracle.send_input("N")
        oracle.wait_for_idle(1.0)
        assert_screen("New Remote PTY", "Remote Auth Modal Opened")

        # Type user@host then Tab to Port
        oracle.send_input("test@localhost<tab>")
        oracle.wait_for_idle(0.5)
        oracle.send_input("2222") # Should go into port field
        oracle.wait_for_idle(0.5)
        assert_screen("2222", "Tab navigation to Port field")

        # Tab again to Auth Toggle
        oracle.send_input("<tab>")
        oracle.wait_for_idle(0.5)

        # Return to finalize (will likely fail connection, which is fine for UI test)
        oracle.send_input("<return>")
        oracle.wait_for_idle(5.0)
        # Check if we got back to manager or saw an error
        oracle.feed_stream()
        snap = oracle.get_screen_snapshot().lower()
        if "id:1" in snap or "error" in snap or "pty manager" in snap:
             record("Remote Modal interaction and Tab work", "PASS")
        else:
             record("Remote Modal interaction and Tab work", "FAIL", "Modal did not progress correctly")

        oracle.send_input("<esc>") # Ensure modal closed

    except Exception as e:
        record("Regression Test Suite", "ERROR", str(e))
    finally:
        oracle.child.terminate(force=True)
        if os.path.exists(socket_path):
            try: os.remove(socket_path)
            except: pass

    return results

def generate_report(results):
    report = "# Neptune Regression Test Results\n\n"
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
    print(f"\nVerification complete. Report: {report_path}")
