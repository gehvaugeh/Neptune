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

        # 2. Local Statefulness: Directory
        print("Testing Local Statefulness: Directory...")
        clear_notebook()
        oracle.send_input("!mkdir -p /tmp/neptune_test <return>")
        oracle.wait_for_idle(2.0)
        oracle.send_input("!cd /tmp/neptune_test <return>")
        oracle.wait_for_idle(2.0)
        oracle.send_input("!pwd <return>")
        assert_screen("/tmp/neptune_test", "Local directory persistence")

        # 3. Local Statefulness: Variables
        print("Testing Local Statefulness: Variables...")
        oracle.send_input("!MY_VAR=neptune_val <return>")
        oracle.wait_for_idle(2.0)
        oracle.send_input("!echo $MY_VAR <return>")
        assert_screen("neptune_val", "Local variable persistence")

        # 4. Short Commands check
        print("Testing Short Command Visibility...")
        oracle.send_input("!ls -d /tmp <return>")
        assert_screen("/tmp", "Short command output visible")
        # Ensure we don't see PGID: from the old wrapper
        assert_not_on_screen("PGID:", "PGID marker not leaked to UI")

        # 5. Remote PTY Setup
        print("Testing Remote PTY Setup...")
        oracle.send_input("<ctrl+t>")
        oracle.wait_for_idle(1.0)
        oracle.send_input("N")
        oracle.wait_for_idle(1.0)
        oracle.send_input("jules@localhost<return>")
        oracle.wait_for_idle(1.0)
        oracle.send_input("2222<return>")
        oracle.wait_for_idle(1.0)
        oracle.send_input("<return>") # Default key
        oracle.wait_for_idle(8.0)
        assert_screen("ID:1", "Remote PTY Created")
        oracle.send_input("<esc>")
        oracle.wait_for_idle(1.0)

        # 6. Remote Statefulness: Directory
        print("Testing Remote Statefulness: Directory...")
        oracle.send_input("!1mkdir -p /tmp/remote_test <return>")
        oracle.wait_for_idle(2.0)
        oracle.send_input("!1cd /tmp/remote_test <return>")
        oracle.wait_for_idle(2.0)
        oracle.send_input("!1pwd <return>")
        assert_screen("/tmp/remote_test", "Remote directory persistence")

        # 7. Remote Statefulness: Variables
        print("Testing Remote Statefulness: Variables...")
        oracle.send_input("!1REMOTE_VAR=remote_val <return>")
        oracle.wait_for_idle(2.0)
        oracle.send_input("!1echo $REMOTE_VAR <return>")
        assert_screen("remote_val", "Remote variable persistence")

        # 8. Local TUI Kill (to avoid remote timing issues in CI)
        print("Testing Local TUI Kill...")
        clear_notebook()
        oracle.send_input("!top <return>")
        assert_screen("tasks:", "Local top running", timeout=10.0)
        oracle.send_input("s") # selection
        oracle.wait_for_idle(1.0)
        oracle.send_input("i") # control
        oracle.wait_for_idle(1.0)
        oracle.send_input("<ctrl+c>")
        oracle.wait_for_idle(3.0)
        oracle.send_input("<esc>")
        oracle.wait_for_idle(1.0)
        # It should be either OK (if top handles SIGINT) or Killed
        oracle.feed_stream()
        snap = oracle.get_screen_snapshot().lower()
        if "killed" in snap or "ok" in snap or "error" in snap:
             record("Local TUI terminated", "PASS")
        else:
             record("Local TUI terminated", "FAIL", "No terminal status found after Ctrl+C")

    except Exception as e:
        record("Statefulness Test Suite", "ERROR", str(e))
    finally:
        oracle.child.terminate(force=True)
        if os.path.exists(socket_path):
            try: os.remove(socket_path)
            except: pass

    return results

def generate_report(results):
    report = "# Neptune Statefulness Test Results\n\n"
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
    print(f"\nStatefulness testing complete. Report: {report_path}")
