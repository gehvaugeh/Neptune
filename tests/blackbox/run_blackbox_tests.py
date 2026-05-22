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

        # 2. TUI Test: top (Local)
        clear_notebook()
        print("Testing Local TUI: top...")
        oracle.send_input("!top <return>")
        oracle.wait_for_idle(5.0) # Increased wait for top rendering
        assert_screen("Tasks:", "top is running (header visible)")

        oracle.send_input("s") # selection mode
        oracle.wait_for_idle(0.5)
        oracle.send_input("i") # control mode
        oracle.wait_for_idle(1.0)
        # We check for TUI by looking at the info bar at the bottom
        assert_screen("interactive", "Interactive mode indicator visible")

        # Kill it via Ctrl+C
        oracle.send_input("<ctrl+c>")
        oracle.wait_for_idle(3.0)
        oracle.send_input("<esc>") # Back to selection
        oracle.wait_for_idle(1.0)
        assert_screen("Killed", "top was killed via Ctrl+C")

        # 3. Enqueuing Test
        clear_notebook()
        print("Testing Command Enqueuing...")
        oracle.send_input("!sleep 5 <return>")
        oracle.send_input("!echo QueuedCmd <return>")
        oracle.wait_for_idle(1.0)
        assert_screen("Queue", "Second command is queued")
        oracle.wait_for_idle(6.0)
        assert_screen("QueuedCmd", "Enqueued command executed after sleep")

        # 4. Termination on Block Deletion
        clear_notebook()
        print("Testing Termination on Block Deletion...")
        oracle.send_input("!sleep 100 <return>")
        oracle.wait_for_idle(2.0)
        assert_screen("Running", "Long sleep is running")
        oracle.send_input("s") # selection mode
        oracle.wait_for_idle(0.5)
        oracle.send_input("x") # delete
        oracle.wait_for_idle(2.0)
        assert_not_on_screen("sleep 100", "Block removed after deletion")

        # Verify PTY is idle
        oracle.send_input("<ctrl+t>")
        oracle.wait_for_idle(1.0)
        assert_screen("idle", "PTY returned to idle after block deletion")
        oracle.send_input("<esc>")

        # 5. Remote PTY TUI
        clear_notebook()
        print("Testing Remote PTY TUI...")
        oracle.send_input("<ctrl+t>")
        oracle.send_input("N")
        oracle.send_input("jules@localhost<return>")
        oracle.send_input("2222<return>")
        oracle.send_input("<return>") # Default key
        oracle.wait_for_idle(8.0) # Remote connection takes time
        assert_screen("ID:1", "Remote PTY (ID:1) created")

        oracle.send_input("!1top <return>")
        oracle.wait_for_idle(8.0)
        assert_screen("Tasks:", "Remote top is running")

        # 6. Termination on PTY Deletion
        oracle.send_input("<ctrl+t>")
        oracle.wait_for_idle(1.0)
        # Select ID:1 (it might be the second item if ID:0 is first)
        oracle.send_input("j")
        oracle.send_input("x") # Delete
        oracle.wait_for_idle(1.0)
        assert_screen("Kill", "Kill Confirmation visible")
        oracle.send_input("<return>") # Confirm
        oracle.wait_for_idle(5.0)

        oracle.feed_stream()
        snapshot = oracle.get_screen_snapshot()
        if "localhost" not in snapshot:
             record("Remote PTY deleted from list", "PASS")
        else:
             record("Remote PTY deleted from list", "FAIL", "Remote PTY still in list")
        oracle.send_input("<esc>")

        # Verify block fallback
        oracle.wait_for_idle(1.0)
        assert_screen("deleted", "Remote block marked as deleted")

    except Exception as e:
        record("Extended Test Suite Execution", "ERROR", str(e))
    finally:
        oracle.child.terminate(force=True)
        if os.path.exists(socket_path):
            try: os.remove(socket_path)
            except: pass

    return results

def generate_report(results):
    report = "# Neptune Extended Blackbox Test Results\n\n"
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
    print(f"\nExtended Blackbox testing complete. Report: {report_path}")
