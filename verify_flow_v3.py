import socket
import json
import time
import subprocess
import sys
import os

def test_full_flow():
    socket_path = "/tmp/final_flow_verify_v3.sock"
    if os.path.exists(socket_path):
        os.remove(socket_path)

    server_proc = subprocess.Popen([sys.executable, "server.py", "-s", socket_path])
    time.sleep(2)

    try:
        # Start client-like connection
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(socket_path)

            # 1. Connect
            client.sendall(json.dumps({"type": "connect", "color": "green"}).encode() + b"\n")
            time.sleep(1)

            # 2. Submit CMD
            client.sendall(json.dumps({"type": "submit", "mode": "CMD", "content": "ls -l", "cwd": "."}).encode() + b"\n")
            time.sleep(2)

            client.setblocking(False)
            data = b""
            try:
                while True:
                    chunk = client.recv(4096)
                    if not chunk: break
                    data += chunk
            except: pass

            decoded = data.decode()
            print("Server response stream:")
            print(decoded)

            if '"type": "new_block"' in decoded and '"status": "ok"' in decoded:
                print("\nINTEGRATION SUCCESS")
            else:
                print("\nINTEGRATION FAILURE: Missing messages")

    finally:
        server_proc.terminate()
        if os.path.exists(socket_path):
            os.remove(socket_path)

if __name__ == "__main__":
    test_full_flow()
