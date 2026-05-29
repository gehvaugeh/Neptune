import sys
import os
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "tests", "oracle"))
from test_driver import NeptuneOracle

def test_ctrl_c():
    socket_path = os.path.abspath("test_ctrl_c.sock")
    if os.path.exists(socket_path): os.remove(socket_path)

    cmd = f"python3 main.py all --clean-history -s {socket_path}"
    oracle = NeptuneOracle(cmd)

    try:
        oracle.wait_for_idle(5.0)
        print("Starting sleep 100...")
        oracle.send_input("!sleep 100 <return>")
        oracle.wait_for_idle(2.0)

        print("Entering CONTROL mode...")
        oracle.send_input("si")
        oracle.wait_for_idle(1.0)

        print("Sending Ctrl+C...")
        oracle.send_input("<ctrl+c>")
        oracle.wait_for_idle(3.0)

        print("Exiting CONTROL mode...")
        oracle.send_input("<esc><esc>") # Double escape to be sure
        oracle.wait_for_idle(1.0)

        snapshot = oracle.get_screen_snapshot()
        print("Snapshot after Ctrl+C:")
        print(snapshot)

        if "Killed" in snapshot or "OK" in snapshot or "error" in snapshot:
            print("SUCCESS: Process terminated")
        else:
            print("FAILURE: Process still running?")

    finally:
        oracle.child.terminate(force=True)
        if os.path.exists(socket_path): os.remove(socket_path)

if __name__ == "__main__":
    test_ctrl_c()
