from test_driver import NeptuneOracle
import time
import os

def run_tests():
    results = []
    cmd = "python3 main.py all --clean-history"
    oracle = NeptuneOracle(cmd)

    def record(desc, status):
        results.append({"description": desc, "result": status})
        print(f"{status}: {desc}")

    try:
        print("Waiting for Neptune to start...")
        oracle.wait_for_idle(4.0)

        # Test 1: Startup
        snapshot = oracle.get_screen_snapshot()
        if "Neptune Multi-User" in snapshot:
            record("Verify Neptune header on startup", "PASS")
        else:
            record("Verify Neptune header on startup", "FAIL")

        # Test 2: Bash Command
        oracle.send_input("!echo 'Blackbox Test' <return>")
        oracle.wait_for_idle(1.5)
        snapshot = oracle.get_screen_snapshot()
        if "Blackbox Test" in snapshot:
            record("Execute echo command in BASH mode", "PASS")
        else:
            record("Execute echo command in BASH mode", "FAIL")

        # Test 3: Mode Switch to Selection
        oracle.send_input("s")
        oracle.wait_for_idle(0.5)
        snapshot = oracle.get_screen_snapshot()
        if "MODE: SELECTION" in snapshot:
            record("Switch to SELECTION mode", "PASS")
        else:
            record("Switch to SELECTION mode", "FAIL")

        # Test 4: Escape back to Normal
        oracle.send_input("<esc>")
        oracle.wait_for_idle(0.5)
        snapshot = oracle.get_screen_snapshot()
        if "MODE: NORMAL" in snapshot:
            record("Return to NORMAL mode via ESC", "PASS")
        else:
            record("Return to NORMAL mode via ESC", "FAIL")

        # Test 5: CMD mode and help
        oracle.send_input(":help <return>")
        oracle.wait_for_idle(1.0)
        snapshot = oracle.get_screen_snapshot()
        if "Commands:" in snapshot and "export" in snapshot:
            record("Execute help command in CMD mode", "PASS")
        else:
            record("Execute help command in CMD mode", "FAIL")

    except Exception as e:
        record(f"Error during testing: {str(e)}", "ERROR")
    finally:
        oracle.child.terminate(force=True)

    return results

def generate_markdown_table(results):
    table = "| Test Description | Result |\n"
    table += "|------------------|--------|\n"
    for r in results:
        res = r["result"]
        # Use emojis for better visibility
        emoji = "✅" if res == "PASS" else "❌" if res == "FAIL" else "⚠️"
        table += f"| {r['description']} | {emoji} {res} |\n"
    return table

if __name__ == "__main__":
    test_results = run_tests()
    markdown_report = "# Blackbox Test Results\n\n"
    markdown_report += "This report was generated using the `neptune-oracle` testing framework.\n\n"
    markdown_report += generate_markdown_table(test_results)

    with open("blackbox_test_results.md", "w") as f:
        f.write(markdown_report)

    print("\nBlackbox testing complete. Report written to blackbox_test_results.md")
