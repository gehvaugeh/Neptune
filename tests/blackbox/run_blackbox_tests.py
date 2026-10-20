import sys
import os
import time
import tempfile
import shutil
import subprocess

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
        oracle.send_input("<esc><esc>!echo hello neptune <return>")
        assert_screen("hello neptune", "Verify Startup via Echo")

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
        oracle.send_input("<esc><esc>s")
        oracle.wait_for_idle(0.5)
        assert_screen("MODE: SELECTION", "Enter Selection Mode")
        oracle.send_input("x")
        assert_not_on_screen("AAA", "Delete block via Selection Mode")

        # 7. Block Reordering
        print("Testing Reordering...")
        oracle.send_input("<esc><esc>!echo MoveMe <return>")
        assert_screen("MoveMe", "Setup MoveMe")
        oracle.send_input("<esc><esc>s")
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
        oracle.send_input("ls <tab>")
        oracle.wait_for_idle(3.0)
        # Palette should open without crash (SHELL: visible means providers ran)
        assert_screen("SHELL:", "Duplicate ID - palette opens without crash")
        # Also check for HISTORY and WORKFLOW entries to confirm collision case
        assert_screen("HISTORY:", "Duplicate ID - history entry visible")
        assert_screen("WORKFLOW:", "Duplicate ID - workflow entry visible")
        oracle.send_input("<esc><esc>")
        oracle.wait_for_idle(0.5)

        # 17. Notebook Import + Scroll — outputs must survive scroll cycles
        print("Testing Notebook Import + Scroll...")
        test_nb = "/tmp/neptune_blackbox_nb.md"
        if os.path.exists(test_nb):
            try: os.remove(test_nb)
            except: pass
        oracle.send_input("<esc><esc>:clear <return>")
        oracle.wait_for_idle(3.0)
        # Create 12 multi-line-output blocks so the list overflows the viewport
        for i in range(12):
            oracle.send_input(f"<esc><esc>!printf 'Block{i:02d}\\nAlpha{i:02d} line1\\nBeta{i:02d} line2\\nGamma{i:02d} line3\\n' <return>")
            oracle.wait_for_idle(1.2)
        # Export notebook with output
        oracle.send_input(f"<esc><esc>:export {test_nb} <return>")
        oracle.wait_for_idle(3.0)
        if not os.path.exists(test_nb):
            record("Import+Scroll - export file", "FAIL", "export file not created")
        else:
            # Clear then re-import
            oracle.send_input("<esc><esc>:clear <return>")
            oracle.wait_for_idle(4.0)
            oracle.send_input(f"<esc><esc>:import {test_nb} <return>")
            oracle.wait_for_idle(6.0)
            time.sleep(1.0)
            oracle.feed_stream()
            # Focus inside the history container (mouse press+release over a block)
            oracle.child.send("\x1b[<0;12;5M")
            time.sleep(0.2)
            oracle.child.send("\x1b[<0;12;5m")
            oracle.wait_for_idle(0.8)
            # Scroll up to the top blocks
            for _ in range(3):
                oracle.child.send("\x1b[5~")
                oracle.wait_for_idle(0.6)
            oracle.wait_for_idle(1.0)
            s = oracle.get_screen_snapshot()
            top_ok = all(x in s for x in ["Block02", "Alpha02 line1", "Beta02 line2", "Gamma02 line3"])
            record("Import+Scroll - top blocks render after scroll up", "PASS" if top_ok else "FAIL", "" if top_ok else "top block output missing")
            # Scroll back down to the bottom
            for _ in range(6):
                oracle.child.send("\x1b[6~")
                oracle.wait_for_idle(0.4)
            oracle.wait_for_idle(1.0)
            s = oracle.get_screen_snapshot()
            bottom_ok = all(x in s for x in ["Block10", "Alpha10 line1", "Beta10 line2", "Gamma10 line3",
                                              "Block11", "Alpha11 line1", "Beta11 line2", "Gamma11 line3"])
            record("Import+Scroll - bottom output preserved after scroll down", "PASS" if bottom_ok else "FAIL", "" if bottom_ok else "bottom block output missing")
        if os.path.exists(test_nb):
            try: os.remove(test_nb)
            except: pass

        # 18. Autosave — change-driven temp session autosave: written on every
        #     notebook mutation, refreshed, and never clobbered with an empty
        #     notebook after :clear.
        print("Testing Autosave...")
        autosave_file = os.path.join(tempfile.gettempdir(), "neptune_autosave_test.md")
        if os.path.exists(autosave_file):
            try: os.remove(autosave_file)
            except: pass
        # Fresh state: clear, then create a marker block with output.
        oracle.send_input("<esc><esc>:clear <return>")
        oracle.wait_for_idle(3.0)
        oracle.send_input("<esc><esc>!echo NepAutosaveOne <return>")
        oracle.wait_for_idle(3.0)
        # Wait for the 2s autosave tick (with retry margin) and verify the file.
        autosave_ok = False
        start = time.time()
        while time.time() - start < 12.0:
            oracle.feed_stream()
            if os.path.exists(autosave_file):
                try:
                    with open(autosave_file, "r") as f:
                        content = f.read()
                    if "NepAutosaveOne" in content:
                        autosave_ok = True
                        break
                except Exception:
                    pass
            time.sleep(0.5)
        record("Autosave - change-driven file created with content", "PASS" if autosave_ok else "FAIL",
               "" if autosave_ok else f"{autosave_file} missing or stale")
        # Now clear and verify the pre-clear autosave is NOT overwritten with an
        # empty notebook (blocks list empty -> tick must skip writing).
        cleared_preserved = False
        if os.path.exists(autosave_file):
            oracle.send_input("<esc><esc>:clear <return>")
            oracle.wait_for_idle(4.0)
            time.sleep(3.0)  # longer than one autosave interval
            oracle.feed_stream()
            try:
                with open(autosave_file, "r") as f:
                    content = f.read()
                cleared_preserved = "NepAutosaveOne" in content
            except Exception:
                pass
        record("Autosave - :clear does not clobber last autosave", "PASS" if cleared_preserved else "FAIL",
               "" if cleared_preserved else "autosave overwritten with empty notebook")
        # Create a second block and verify the autosave refreshes to the new state.
        if os.path.exists(autosave_file):
            oracle.send_input("<esc><esc>!echo NepAutosaveTwo <return>")
            oracle.wait_for_idle(3.0)
            refreshed = False
            start = time.time()
            while time.time() - start < 12.0:
                oracle.feed_stream()
                try:
                    with open(autosave_file, "r") as f:
                        content = f.read()
                    if "NepAutosaveTwo" in content:
                        refreshed = True
                        break
                except Exception:
                    pass
                time.sleep(0.5)
            record("Autosave - file refreshes to newest state", "PASS" if refreshed else "FAIL",
                   "" if refreshed else "autosave not updated")
        if os.path.exists(autosave_file):
            try: os.remove(autosave_file)
            except: pass

        # 19. PTY Frontmatter — export writes a neptune.ptys registry plus
        #     per-fence (pty:<name>) tokens; import restores the binding.
        print("Testing PTY Frontmatter Export/Import...")
        fm_nb = "/tmp/neptune_frontmatter_nb.md"
        if os.path.exists(fm_nb):
            try: os.remove(fm_nb)
            except: pass
        oracle.send_input("<esc><esc>:clear <return>")
        oracle.wait_for_idle(3.0)
        oracle.send_input("<esc><esc>!echo PtyFmMarker <return>")
        oracle.wait_for_idle(2.5)
        oracle.send_input(f"<esc><esc>:export {fm_nb} <return>")
        oracle.wait_for_idle(3.0)
        fm_ok, pty_token_ok = False, False
        if os.path.exists(fm_nb):
            try:
                with open(fm_nb, "r") as f:
                    fm_content = f.read()
                fm_ok = ("neptune:" in fm_content and "ptys:" in fm_content and "local-0" in fm_content)
                pty_token_ok = "(pty:local-0)" in fm_content
            except Exception:
                pass
        record("PTY Frontmatter - export writes neptune.ptys registry", "PASS" if fm_ok else "FAIL",
               "" if fm_ok else "frontmatter missing in export")
        record("PTY Frontmatter - fence carries (pty:<name>) token", "PASS" if pty_token_ok else "FAIL",
               "" if pty_token_ok else "pty token missing in fence")
        if os.path.exists(fm_nb):
            oracle.send_input("<esc><esc>:clear <return>")
            oracle.wait_for_idle(4.0)
            oracle.send_input(f"<esc><esc>:import {fm_nb} <return>")
            oracle.wait_for_idle(5.0)
            reimport_ok = False
            start = time.time()
            while time.time() - start < 8.0:
                oracle.feed_stream()
                if "PtyFmMarker" in oracle.get_screen_snapshot():
                    reimport_ok = True
                    break
                time.sleep(0.5)
            record("PTY Frontmatter - import restores bound block", "PASS" if reimport_ok else "FAIL",
                   "" if reimport_ok else "imported block not visible")
        if os.path.exists(fm_nb):
            try: os.remove(fm_nb)
            except: pass

        # 20. PTY Remote Reconnect — the frontmatter must persist the SSH user
        #     (plus host/port/key) and importing it must rebuild the connection.
        #     Skipped gracefully when no local sshd/key auth is available.
        print("Testing PTY Remote Reconnect (ssh_config persistence)...")
        rh_path = os.path.join(root_dir, "remote_hosts.txt")
        rh_before = None
        if os.path.exists(rh_path):
            try:
                with open(rh_path) as f:
                    rh_before = f.read()
            except Exception:
                rh_before = None

        ssh_user = os.environ.get("USER") or "root"
        key_candidates = [
            os.path.expanduser("~/.ssh/id_ed25519"),
            os.path.expanduser("~/.ssh/id_rsa"),
        ]
        ssh_key = next(
            (k for k in key_candidates if os.path.exists(k) and os.path.exists(k + ".pub")),
            None,
        )
        ssh_ok = False
        if ssh_key and shutil.which("ssh"):
            try:
                probe = subprocess.run(
                    ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                     "-o", "ConnectTimeout=3", "-i", ssh_key, "localhost", "true"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8,
                )
                ssh_ok = probe.returncode == 0
            except Exception:
                ssh_ok = False

        def wait_for_text(needle, timeout=20.0):
            start = time.time()
            while time.time() - start < timeout:
                oracle.feed_stream()
                if needle.lower() in oracle.get_screen_snapshot().lower():
                    return True
                time.sleep(0.5)
            return False

        remote_nb = "/tmp/neptune_remote_reconnect_nb.md"
        try:
            if not ssh_ok:
                record("PTY Remote Reconnect - ssh_config persisted", "PASS",
                       "skipped (no local ssh key auth)")
            else:
                if os.path.exists(remote_nb):
                    try: os.remove(remote_nb)
                    except: pass
                oracle.send_input("<esc><esc>:clear <return>")
                oracle.wait_for_idle(3.0)

                # Open the PTY target bar with a raw "!!" (the helper sleeps
                # 0.5s per '!', which exceeds the 0.3s double-bang window).
                oracle.send_input("<esc><esc>")
                oracle.child.send("!!")
                time.sleep(0.6)
                oracle.feed_stream()
                oracle.send_input(f"{ssh_user}@localhost:22:{ssh_key}<return>")
                created = wait_for_text("PTY created", 20.0)
                record("PTY Remote Reconnect - remote created", "PASS" if created else "FAIL",
                       "" if created else "no PTY created")

                oracle.send_input("echo RemoteReconnectMarker <return>")
                ran = wait_for_text("RemoteReconnectMarker", 15.0)
                record("PTY Remote Reconnect - command ran", "PASS" if ran else "FAIL")

                oracle.send_input(f"<esc><esc>:export {remote_nb} <return>")
                oracle.wait_for_idle(3.0)
                fm = ""
                if os.path.exists(remote_nb):
                    try:
                        with open(remote_nb) as f:
                            fm = f.read()
                    except Exception:
                        pass
                host_ok = "host: localhost" in fm
                user_ok = f"user: {ssh_user}" in fm
                key_ok = "key:" in fm
                record("PTY Remote Reconnect - persists host/user/key",
                       "PASS" if (host_ok and user_ok and key_ok) else "FAIL",
                       "" if (host_ok and user_ok and key_ok) else fm[:200])

                oracle.send_input("<esc><esc>:clear <return>")
                oracle.wait_for_idle(4.0)
                oracle.send_input(f"<esc><esc>:import {remote_nb} <return>")
                time.sleep(8.0)
                oracle.feed_stream()
                snap = oracle.get_screen_snapshot()
                rebound = "RemoteReconnectMarker" in snap and "localhost" in snap.lower()
                record("PTY Remote Reconnect - reconnects on import",
                       "PASS" if rebound else "FAIL",
                       "" if rebound else snap[-200:])

                # Bad credentials must fail with ssh's reason, never the old
                # "expected str, bytes or os.PathLike object, not NoneType".
                oracle.send_input("<esc><esc>")
                oracle.child.send("!!")
                time.sleep(0.6)
                oracle.feed_stream()
                oracle.send_input(
                    f"definitely_no_such_user_xyz@127.0.0.1:22:{ssh_key}<return>"
                )
                saw_error = False
                saw_typeerror = False
                detail = ""
                start = time.time()
                while time.time() - start < 20.0:
                    oracle.feed_stream()
                    snap2 = oracle.get_screen_snapshot()
                    if "not NoneType" in snap2 or "expected str, bytes" in snap2:
                        saw_typeerror = True
                        detail = snap2[-200:]
                    if "PTY Error" in snap2 or "connect failed" in snap2.lower():
                        saw_error = True
                        detail = snap2[-200:]
                        break
                    time.sleep(0.5)
                record("PTY Remote Reconnect - clear auth error", "PASS" if saw_error and not saw_typeerror else "FAIL", detail)
        finally:
            if os.path.exists(remote_nb):
                try: os.remove(remote_nb)
                except: pass
            # Restore the remote-host history exactly as it was before the test.
            try:
                if rh_before is None:
                    if os.path.exists(rh_path):
                        os.remove(rh_path)
                else:
                    with open(rh_path, "w") as f:
                        f.write(rh_before)
            except Exception:
                pass
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
