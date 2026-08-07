"""Test autocomplete through the TUI - screen capture after tab"""
import pexpect, pyte, time, os, json, signal

SOCKET_PATH = os.path.abspath("test_debug.sock")
for f in [SOCKET_PATH, "test_debug_debug.log"]:
    if os.path.exists(f): os.remove(f)

os.environ["NEPTUNE_DEBUG"] = "1"
os.environ["LOG_FILE"] = "test_debug_debug.log"

child = pexpect.spawn(
    f"python3 main.py all --clean-history -s {SOCKET_PATH}",
    dimensions=(24, 80), encoding='utf-8', timeout=15,
    cwd=os.path.abspath(os.path.dirname(__file__))
)
time.sleep(4)

screen = pyte.Screen(80, 24)
stream = pyte.Stream(screen)

def feed():
    try:
        while True:
            data = child.read_nonblocking(size=4096, timeout=0.1)
            if data: stream.feed(data)
            else: break
    except: pass

def snapshot():
    feed()
    lines = []
    for y in range(24):
        line = "".join(screen.buffer[y][x].data for x in range(80))
        lines.append(line.rstrip())
    return "\n".join(lines)

print("=== Initial ===")
print(snapshot())

# Connect raw socket to monitor server messages
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect(SOCKET_PATH)
sock.settimeout(0.5)

def drain_server():
    msgs = []
    try:
        while True:
            data = sock.recv(65536)
            if not data: break
            for line in data.decode().strip().split("\n"):
                if line:
                    try: msgs.append(json.loads(line))
                    except: pass
    except socket.timeout: pass
    return msgs

drain_server()  # clear init messages

print("\n=== Sending !ls + tab ===")

# Simulate what the test driver does
child.send('\x1b'); time.sleep(0.2)
child.send('\x1b'); time.sleep(0.2)
child.send('!'); time.sleep(0.6)  # mode trigger delay
child.send('l'); time.sleep(0.05)
child.send('s'); time.sleep(0.05)
child.send('\t'); time.sleep(0.5)

time.sleep(5)  # wait for autocomplete

print("\n=== Screen ===")
print(snapshot())

msgs = drain_server()
print(f"\n=== Server msgs: {len(msgs)} ===")
for m in msgs:
    print(f"  {json.dumps(m)[:200]}")

# Check debug log
log_file = "test_debug_debug.log"
if os.path.exists(log_file):
    with open(log_file) as f:
        log = f.read()
    # Show relevant log lines
    for line in log.split("\n"):
        if any(kw in line.lower() for kw in ["autocomplete", "shadow", "get_suggestions", "future"]):
            print(f"LOG: {line}")

child.terminate(force=True)
sock.close()
for f in [SOCKET_PATH, "test_debug_debug.log"]:
    try: os.remove(f)
    except: pass
