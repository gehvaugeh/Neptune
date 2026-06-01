import sys
import os
import time

# Ensure we can import NeptuneOracle from the sibling directory
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "oracle"))
from test_driver import NeptuneOracle

def run_tests():
    results = []
    perf_metrics = {}
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

    try:
        print(f"Starting Neptune (Socket: {socket_path})...")
        start_time = time.time()
        oracle.wait_for_idle(5.0)
        perf_metrics["Startup Time"] = time.time() - start_time

        # 1. Startup
        assert_screen("Neptune Multi-User", "Verify Startup Header")

        # 2. BASH Echo
        print("Testing BASH Echo...")
        start_time = time.time()
        oracle.send_input("<esc><esc>!echo OracleEcho <return>")
        if assert_screen("OracleEcho", "Execute BASH Echo"):
            perf_metrics["BASH Echo Latency"] = time.time() - start_time

        # 3. Internal Help
        oracle.send_input("<esc><esc>:help <return>")
        assert_screen("Commands:", "Internal Help Command")

        # 4. NOTE creation
        oracle.send_input("<esc><esc>;NoteMarker <return>")
        assert_screen("NoteMarker", "Create Note")

        # 5. Clear screen
        oracle.send_input("<esc><esc>:clear <return>")
        oracle.wait_for_idle(2.0)

        # 6. Selection Navigation & Deletion
        oracle.send_input("<esc><esc>!echo AAA <return>")
        assert_screen("AAA", "Setup AAA")
        oracle.send_input("s")
        assert_screen("MODE: SELECTION", "Enter Selection Mode")
        oracle.send_input("x")
        assert_not_on_screen("AAA", "Delete block via Selection Mode")

    except Exception as e:
        record("Test Suite Execution", "ERROR", str(e))
    finally:
        oracle.child.terminate(force=True)
        if os.path.exists(socket_path):
            try: os.remove(socket_path)
            except: pass

    return results, perf_metrics

def generate_report(results, perf_metrics):
    report = "# Neptune Blackbox Test Results\n\n"
    report += f"**Automated Verification Run:** {time.ctime()}\n\n"
    report += "## Feature Tests\n\n"
    report += "| Feature Test | Result | Details |\n"
    report += "|--------------|--------|---------|\n"
    for r in results:
        emoji = "✅" if r["result"] == "PASS" else "❌" if r["result"] == "FAIL" else "⚠️"
        report += f"| {r['description']} | {emoji} {r['result']} | {r['details']} |\n"

    report += "\n## Performance Metrics\n\n"
    report += "| Metric | Value |\n"
    report += "|--------|-------|\n"
    for metric, value in perf_metrics.items():
        report += f"| {metric} | {value:.4f}s |\n"
    return report

if __name__ == "__main__":
    results, metrics = run_tests()
    report_path = os.path.join(os.path.dirname(__file__), "blackbox_test_results.md")
    with open(report_path, "w") as f:
        f.write(generate_report(results, metrics))
    print(f"\nBlackbox testing complete. Report: {report_path}")
