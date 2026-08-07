"""Debug script: connect to Neptune server and test autocomplete directly"""
import socket, json, time, os, signal, sys, subprocess

SOCKET_PATH = os.path.abspath("test_debug.sock")

# Kill any existing process on this socket
if os.path.exists(SOCKET_PATH): os.remove(SOCKET_PATH)

# Start server
proc = subprocess.Popen(
    [sys.executable, "main.py", "all", "--clean-history", "-s", SOCKET_PATH],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT
)
time.sleep(3)

try:
    # Connect
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(SOCKET_PATH)

    def send(msg):
        sock.sendall((json.dumps(msg) + "\n").encode())
        time.sleep(0.1)

    def recv(timeout=3.0):
        sock.settimeout(timeout)
        try:
            data = sock.recv(65536)
            lines = data.decode().strip().split("\n")
            return [json.loads(l) for l in lines if l]
        except socket.timeout:
            return []
        finally:
            sock.settimeout(None)

    # Read initial messages
    initial = recv(2.0)
    print(f"Initial messages: {len(initial)}")
    for m in initial:
        print(f"  {m.get('type')}: {json.dumps(m)[:100]}")

    # Send autocomplete_query
    print("\nSending autocomplete_query...")
    send({
        "type": "autocomplete_query",
        "pty_uid": 0,
        "query": "ls",
        "request_id": "test_001"
    })

    # Wait for response
    time.sleep(3)
    resp = recv(2.0)
    print(f"\nResponse messages: {len(resp)}")
    for m in resp:
        print(f"  {json.dumps(m)[:200]}")

except Exception as e:
    print(f"ERROR: {e}")
finally:
    sock.close()
    proc.terminate()
    proc.wait()
    if os.path.exists(SOCKET_PATH): os.remove(SOCKET_PATH)
