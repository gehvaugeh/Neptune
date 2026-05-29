import asyncio, os, time
from pty_remote import RemotePTY

async def test_remote_ctrl_c():
    def broadcast(msg):
        if msg['type'] == 'output':
            print(f"OUTPUT: {msg['data']}", end="")
        elif msg['type'] == 'update_block':
            print(f"STATUS: {msg['block']['status']}")

    pty = RemotePTY(1, "remote-1", lambda m: asyncio.ensure_future(asyncio.sleep(0, result=broadcast(m))))

    ssh_config = {
        "host": "localhost",
        "user": "jules",
        "port": 2222,
        "key": os.path.expanduser("~/.ssh/id_rsa")
    }

    print("Connecting...")
    await pty.connect(ssh_config)
    print(f"Connected. TTY: {pty.remote_tty}, Shell PGID: {pty.shell_pgid}")

    block = {"id": "b1", "content": "sleep 100"}
    print("Running sleep 100...")
    task = asyncio.create_task(pty.run_command(block))

    await asyncio.sleep(2)
    print("Sending Ctrl+C...")
    await pty.send_input("\x03")

    try:
        await asyncio.wait_for(task, timeout=10)
        print("Command task finished.")
    except asyncio.TimeoutError:
        print("Command task TIMED OUT. Ctrl+C failed?")

    await pty.kill()

if __name__ == "__main__":
    asyncio.run(test_remote_ctrl_c())
