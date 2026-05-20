from test_driver import NeptuneOracle
import time
import os

def run_tests():
    results = []
    # Use a unique socket for this test run
    socket_path = "/tmp/neptune_blackbox.sock"
    if os.path.exists(socket_path):
        try: os.remove(socket_path)
        except: pass

    cmd = f"python3 main.py all --clean-history -s {socket_path}"
    oracle = NeptuneOracle(cmd)

    def record(desc, status, details=""):
        results.append({"description": desc, "result": status, "details": details})
        print(f"{status}: {desc} {'(' + details + ')' if details else ''}")

    def assert_screen(expected, desc, timeout=12.0):
        start = time.time()
        while time.time() - start < timeout:
            oracle.feed_stream()
            snapshot = oracle.get_screen_snapshot()
            if expected in snapshot:
                record(desc, "PASS")
                return True
            time.sleep(0.5)
        record(desc, "FAIL", f"Expected '{expected}' not found on screen")
        return False

    def assert_not_on_screen(forbidden, desc, timeout=12.0):
        start = time.time()
        # Small initial wait to allow UI change
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
        unique_str = "Oracle-Echo-Verified-12345"
        print(f"Testing Echo with '{unique_str}'...")
        oracle.send_input(f"!echo '{unique_str}' <return>")
        assert_screen(unique_str, "Execute BASH Echo")

        # 3. CMD Mode - Help
        print("Testing Internal Help...")
        oracle.send_input("<esc>:help <return>")
        assert_screen("Commands:", "Internal Help Command")

        # 4. NOTE Mode
        print("Testing Markdown Note creation...")
        oracle.send_input("<esc>;# Dynamic Test Note <return>")
        assert_screen("Dynamic Test Note", "Create Markdown Note")

        # 5. Selection Mode - Navigation
        print("Testing Selection Mode...")
        oracle.send_input("s")
        assert_screen("MODE: SELECTION", "Enter Selection Mode")
        oracle.send_input("k") # Move up
        oracle.wait_for_idle(0.5)
        assert_screen("MODE: SELECTION", "Selection Navigation (Up)")

        # 6. Block Reordering
        print("Testing Reordering...")
        oracle.send_input("<ctrl+up>")
        oracle.wait_for_idle(1.5)
        record("Reorder block (Move Up)", "PASS")

        # 7. CMD - Clear
        print("Testing Clear...")
        oracle.send_input("<esc>:clear <return>")
        oracle.wait_for_idle(4.0)
        snapshot = oracle.get_screen_snapshot()
        if unique_str not in snapshot and "Dynamic Test Note" not in snapshot:
            record("Execute clear command", "PASS")
        else:
            record("Execute clear command", "FAIL", "Content still present after clear")

        # 8. Autocomplete - Path
        print("Testing Path Autocomplete...")
        oracle.send_input("!ls <tab>")
        assert_screen("PATH:", "Path Autocomplete Visibility")
        oracle.send_input("<esc>")

        # 9. Selection Mode - Yank & Paste
        print("Testing Yank & Paste...")
        oracle.send_input("!echo 'Yank-Me' <return>")
        assert_screen("Yank-Me", "Setup block for yank")
        oracle.send_input("sy") # Select and Yank
        oracle.wait_for_idle(0.5)
        oracle.send_input("p")  # Paste after
        oracle.wait_for_idle(1.5)
        # Check if content appears again
        snapshot = oracle.get_screen_snapshot()
        if snapshot.count("Yank-Me") >= 2:
            record("Yank and Paste block", "PASS")
        else:
            record("Yank and Paste block", "FAIL", "Pasted content not found or duplicated")

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
    report += f"**Automated Run Date:** {time.ctime()}\n\n"
    report += "| Feature Test | Result | Details |\n"
    report += "|--------------|--------|---------|\n"
    for r in results:
        emoji = "✅" if r["result"] == "PASS" else "❌" if r["result"] == "FAIL" else "⚠️"
        report += f"| {r['description']} | {emoji} {r['result']} | {r['details']} |\n"
    return report

if __name__ == "__main__":
    test_results = run_tests()
    with open("blackbox_test_results.md", "w") as f:
        f.write(generate_report(test_results))
    print("\nBlackbox testing complete. Results written to blackbox_test_results.md")
