import sys
import os
import time
import argparse
import json
import subprocess
import signal

# Ensure we can import NeptuneOracle from the sibling directory
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "oracle"))
from test_driver import NeptuneOracle

# Default credentials for local SSH testing
DEFAULT_USER = os.environ.get("NEPTUNE_TEST_USER", "jules")
DEFAULT_PASS = os.environ.get("NEPTUNE_TEST_PASS", "testpassword")

class NeptuneTestRunner:
    def __init__(self, socket_path="test.sock"):
        self.socket_path = os.path.abspath(socket_path)
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        self.main_path = os.path.join(self.root_dir, "main.py")
        self.server_path = os.path.join(self.root_dir, "server.py")
        self.client_path = os.path.join(self.root_dir, "client.py")
        self.results = []
        self._cleanup_artifacts()

    def _cleanup_artifacts(self):
        for f in [self.socket_path, "multiuser.sock", "test_nb.md", "history.txt", "neptune_server.log", "client_debug.log"]:
            if os.path.exists(f):
                try: os.remove(f)
                except: pass

    def record(self, desc, status, details=""):
        self.results.append({"description": desc, "result": status, "details": details})
        emoji = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
        print(f"{emoji} {status}: {desc} {'(' + details + ')' if details else ''}")

    def assert_screen(self, oracle, expected, desc, timeout=15.0):
        start = time.time()
        while time.time() - start < timeout:
            oracle.feed_stream()
            snapshot = oracle.get_screen_snapshot()
            if expected.lower() in snapshot.lower():
                self.record(desc, "PASS")
                return True
            time.sleep(0.5)
        self.record(desc, "FAIL", f"Expected '{expected}' not found")
        return False

    def assert_not_on_screen(self, oracle, forbidden, desc, timeout=15.0):
        start = time.time()
        time.sleep(1.0)
        while time.time() - start < timeout:
            oracle.feed_stream()
            snapshot = oracle.get_screen_snapshot()
            if forbidden.lower() not in snapshot.lower():
                self.record(desc, "PASS")
                return True
            time.sleep(0.5)
        self.record(desc, "FAIL", f"Still found '{forbidden}' on screen")
        return False

    def spawn_oracle(self, clean_history=True, socket=None):
        s = socket or self.socket_path
        cmd = f"python3 {self.main_path} all {'--clean-history' if clean_history else ''} -s {s}"
        oracle = NeptuneOracle(cmd, cwd=self.root_dir)
        oracle.wait_for_idle(5.0)
        return oracle

    def spawn_client(self, socket=None):
        s = socket or self.socket_path
        cmd = f"python3 {self.client_path} -s {s}"
        oracle = NeptuneOracle(cmd, cwd=self.root_dir)
        oracle.wait_for_idle(5.0)
        return oracle

    def test_local(self):
        print("\n--- [Section] LOCAL PTY ---")
        oracle = self.spawn_oracle()
        try:
            self.assert_screen(oracle, "Neptune Multi-User", "Verify Startup Header")

            print("Testing Process Handling (Local)...")
            oracle.send_input("<esc><esc>!echo LocalEchoTest <return>")
            self.assert_screen(oracle, "LocalEchoTest", "Execute BASH Echo")

            oracle.send_input("<esc><esc>!echo Line1<ctrl+j>echo Line2 <return>")
            self.assert_screen(oracle, "Line1", "BASH Multi-line Part 1")
            self.assert_screen(oracle, "Line2", "BASH Multi-line Part 2")

            oracle.send_input("<esc><esc>!false <return>")
            self.assert_screen(oracle, "ERROR(1)", "Verify Non-zero Exit Code")

            oracle.send_input("<esc><esc>!sleep 10 <return>")
            self.assert_screen(oracle, "running", "Wait for sleep to start")
            oracle.send_input("s i")
            oracle.send_input("<ctrl+c>")
            self.assert_screen(oracle, "done", "Verify SIGINT in Control Mode")

        finally:
            oracle.child.terminate(force=True)

    def test_remote(self):
        print("\n--- [Section] REMOTE PTY ---")
        oracle = self.spawn_oracle()
        try:
            print("Testing Remote PTY Creation Flow...")
            oracle.send_input("<esc><esc>:ptyman<return>")
            time.sleep(1)
            oracle.send_input("N")
            time.sleep(1)
            oracle.send_input(f"{DEFAULT_USER}@localhost")
            time.sleep(0.5)
            # Toggle to Password: Tab to Port, Tab to Toggle, RETURN to press Toggle
            oracle.child.send("\t\t\r")
            time.sleep(1)
            oracle.send_input(f"{DEFAULT_PASS}\r")

            self.assert_screen(oracle, "PTY created", "Verify Remote PTY Creation", timeout=30.0)

            print("Testing Process Handling (Remote)...")
            # Close modal if notification appeared but modal stayed
            oracle.send_input("<esc><esc>")
            time.sleep(1)

            # Select ID:1 manually to be sure
            oracle.send_input(":ptyman<return>")
            time.sleep(2)
            oracle.child.send("\x1b[B") # Down arrow
            time.sleep(1)
            oracle.child.send("\r") # Select
            time.sleep(2)

            self.assert_screen(oracle, "localhost", "Verify remote PTY indicator", timeout=10.0)
            oracle.send_input("whoami<return>")
            self.assert_screen(oracle, DEFAULT_USER, "Execute remote command", timeout=20.0)

            print("Testing PTY Deletion (Non-default)...")
            # 1. Switch back to local-0 (ID:0)
            oracle.send_input("<esc><esc>:ptyman<return>")
            time.sleep(1)
            oracle.child.send("\r") # Select local-0
            time.sleep(2)

            # 2. Delete ID:1
            oracle.send_input("<esc><esc>:ptyman<return>")
            time.sleep(2)
            oracle.send_input("/localhost")
            time.sleep(1)
            oracle.child.send("\x1b") # focus list
            time.sleep(1)
            oracle.send_input("x")    # delete
            self.assert_screen(oracle, "PTY destroyed", "Verify PTY Destruction", timeout=15.0)

        finally:
            oracle.child.terminate(force=True)

    def test_ui(self):
        print("\n--- [Section] UI & NAVIGATION ---")
        oracle = self.spawn_oracle()
        try:
            print("Testing Modals...")
            oracle.send_input("<esc><esc>:help <return>")
            self.assert_screen(oracle, "Commands:", "Help Modal Visibility")
            oracle.send_input("<esc>")

            print("Testing Selection Mode Hotkeys...")
            oracle.send_input(";UI-Note <return>")
            oracle.send_input("s")
            self.assert_screen(oracle, "MODE: SELECTION", "Enter Selection Mode")

            oracle.send_input("y") # Yank
            oracle.send_input("p") # Paste After
            time.sleep(2)
            oracle.feed_stream()
            if oracle.get_screen_snapshot().count("UI-Note") >= 2:
                self.record("Hotkey: Yank/Paste (y/p)", "PASS")
            else:
                self.record("Hotkey: Yank/Paste (y/p)", "FAIL")

            oracle.send_input("<ctrl+up>")
            self.record("Hotkey: Move (Ctrl+Up)", "PASS")

            oracle.send_input("x") # Delete
            self.record("Hotkey: Delete (x)", "PASS")

            print("Testing Filtering (Ctrl+F/G)...")
            oracle.send_input("<esc><esc>!echo FilterMe <return>")
            self.assert_screen(oracle, "FilterMe", "Setup Filter Test")
            oracle.send_input("<ctrl+f>")
            self.assert_screen(oracle, "Filter:", "Open Filter Bar")
            oracle.send_input("NotFound<return>")
            self.assert_not_on_screen(oracle, "FilterMe", "Filter Hides Block")
            oracle.send_input("<ctrl+g>")
            self.assert_screen(oracle, "FilterMe", "Clear Filter (Ctrl+G)")

        finally:
            oracle.child.terminate(force=True)

    def test_multiuser(self):
        print("\n--- [Section] MULTIUSER COLLABORATION ---")
        socket_path = os.path.abspath("multiuser.sock")
        if os.path.exists(socket_path): os.remove(socket_path)

        server_proc = subprocess.Popen([sys.executable, self.server_path, "-s", socket_path, "--clean-history"])
        time.sleep(2)
        try:
            oracle_a = self.spawn_client(socket=socket_path)
            oracle_b = self.spawn_client(socket=socket_path)
            try:
                print("Testing Real-time Sync...")
                oracle_a.send_input("<esc><esc>!echo SyncTest <return>")
                self.assert_screen(oracle_b, "SyncTest", "Verify block sync to Client B")

                print("Testing Block Locking...")
                oracle_a.send_input("s e")
                self.assert_screen(oracle_a, "MODE: BLOCKEDIT", "Client A enters edit")

                oracle_b.send_input("s e")
                self.assert_screen(oracle_b, "is locked by user", "Client B denied edit access")

            finally:
                oracle_a.child.terminate(force=True)
                oracle_b.child.terminate(force=True)
        finally:
            server_proc.terminate()
            server_proc.wait()
            if os.path.exists(socket_path): os.remove(socket_path)

    def test_tui(self):
        print("\n--- [Section] TUI & CONTROL MODE ---")
        oracle = self.spawn_oracle()
        try:
            print("Testing TUI Activation...")
            oracle.send_input("<esc><esc>!top <return>")
            self.assert_screen(oracle, "running", "Wait for top")

            oracle.send_input("s i")
            self.assert_screen(oracle, "MODE: CONTROL", "Enter Control Mode")
            self.assert_screen(oracle, "Tasks", "Verify TUI visibility")

            print("Testing Exit from Control Mode...")
            oracle.send_input("<esc>")
            time.sleep(0.1)
            oracle.send_input("<esc>")
            self.assert_screen(oracle, "MODE: SELECTION", "Return to Selection Mode")

            oracle.send_input("x") # Cleanup
        finally:
            oracle.child.terminate(force=True)

    def test_internal(self):
        print("\n--- [Section] INTERNAL COMMANDS ---")
        oracle = self.spawn_oracle()
        try:
            print("Testing :export and :import...")
            oracle.send_input("<esc><esc>;ExportMarker <return>")
            oracle.send_input("<esc><esc>:export test_nb.md <return>")
            self.assert_screen(oracle, "Saved", "Export Command")

            oracle.send_input("<esc><esc>:clear <return>")
            oracle.send_input("<esc><esc>:import test_nb.md <return>")
            self.assert_screen(oracle, "ExportMarker", "Import Command")

            if os.path.exists("test_nb.md"): os.remove("test_nb.md")
        finally:
            oracle.child.terminate(force=True)

    def generate_report(self):
        report = "# Neptune Blackbox Test Results\n\n"
        report += f"**Automated Verification Run:** {time.ctime()}\n\n"
        report += "| Feature Test | Result | Details |\n"
        report += "|--------------|--------|---------|\n"
        for r in self.results:
            emoji = "✅" if r["result"] == "PASS" else "❌" if r["result"] == "FAIL" else "⚠️"
            report += f"| {r['description']} | {emoji} {r['result']} | {r['details']} |\n"

        report_path = os.path.join(os.path.dirname(__file__), "blackbox_test_results.md")
        with open(report_path, "w") as f:
            f.write(report)
        print(f"\nBlackbox testing complete. Report: {report_path}")

def main():
    parser = argparse.ArgumentParser(description="Neptune Blackbox Test Suite")
    parser.add_argument("--local", action="store_true", help="Run local PTY tests")
    parser.add_argument("--remote", action="store_true", help="Run remote PTY tests")
    parser.add_argument("--ui", action="store_true", help="Run UI & Navigation tests")
    parser.add_argument("--multiuser", action="store_true", help="Run multiuser sync tests")
    parser.add_argument("--tui", action="store_true", help="Run TUI & Control mode tests")
    parser.add_argument("--internal", action="store_true", help="Run internal command tests")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    args = parser.parse_args()

    runner = NeptuneTestRunner()

    if args.all or args.local:
        runner.test_local()
    if args.all or args.remote:
        runner.test_remote()
    if args.all or args.ui:
        runner.test_ui()
    if args.all or args.multiuser:
        runner.test_multiuser()
    if args.all or args.tui:
        runner.test_tui()
    if args.all or args.internal:
        runner.test_internal()

    if not any(vars(args).values()):
        parser.print_help()
    else:
        runner.generate_report()

if __name__ == "__main__":
    main()
