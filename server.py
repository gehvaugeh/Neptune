import asyncio
import json
import os
import pty
import subprocess
import uuid
import signal
from typing import Dict, List, Any

SOCKET_PATH = "/tmp/gemmi_shell.sock"
BASH_EXE = "/data/data/com.termux/files/usr/bin/bash" if os.path.exists("/data/data/com.termux/files/usr/bin/bash") else "/bin/bash"

class ServerState:
    def __init__(self):
        self.blocks = []  # List of dicts: {id, type, content, cwd, output, status, locked_by}
        self.clients = {} # writer: {id, color}
        self.active_processes = {} # block_id: process

    def add_block(self, block_type, content, cwd=None):
        block = {
            "id": str(uuid.uuid4()),
            "type": block_type,
            "content": content,
            "cwd": cwd or os.getcwd(),
            "output": "",
            "status": "ready",
            "locked_by": None
        }
        self.blocks.append(block)
        return block

    def get_block(self, block_id):
        for b in self.blocks:
            if b["id"] == block_id:
                return b
        return None

state = ServerState()

async def broadcast(message):
    data = json.dumps(message).encode() + b"\n"
    for writer in list(state.clients.keys()):
        try:
            writer.write(data)
            await writer.drain()
        except:
            del state.clients[writer]

async def handle_client(reader, writer):
    user_id = str(uuid.uuid4())
    state.clients[writer] = {"id": user_id, "color": "white"}

    print(f"Client connected: {user_id}")

    try:
        while True:
            line = await reader.readline()
            if not line:
                break

            msg = json.loads(line.decode())
            msg_type = msg.get("type")

            if msg_type == "connect":
                state.clients[writer]["color"] = msg.get("color", "white")
                # Send initial state
                init_msg = {
                    "type": "init",
                    "blocks": state.blocks,
                    "users": {c["id"]: c["color"] for c in state.clients.values()},
                    "your_id": user_id
                }
                writer.write(json.dumps(init_msg).encode() + b"\n")
                await writer.drain()

                await broadcast({"type": "user_join", "user_id": user_id, "color": state.clients[writer]["color"]})

            elif msg_type == "submit":
                mode = msg.get("mode")
                content = msg.get("content")
                cwd = msg.get("cwd", os.getcwd())

                block = state.add_block(mode, content, cwd)
                await broadcast({"type": "new_block", "block": block})

                if mode == "CMD":
                    asyncio.create_task(run_process(block))

            elif msg_type == "edit_start":
                block_id = msg.get("block_id")
                block = state.get_block(block_id)
                if block and not block["locked_by"]:
                    block["locked_by"] = user_id
                    await broadcast({
                        "type": "lock",
                        "block_id": block_id,
                        "user_id": user_id,
                        "user_color": state.clients[writer]["color"]
                    })

            elif msg_type == "edit_save":
                block_id = msg.get("block_id")
                content = msg.get("content")
                block = state.get_block(block_id)
                if block and block["locked_by"] == user_id:
                    block["content"] = content
                    block["locked_by"] = None
                    await broadcast({"type": "update_block", "block": block})
                    await broadcast({"type": "unlock", "block_id": block_id})

                    if block["type"] == "CMD":
                        block["output"] = ""
                        asyncio.create_task(run_process(block))

            elif msg_type == "edit_cancel":
                block_id = msg.get("block_id")
                block = state.get_block(block_id)
                if block and block["locked_by"] == user_id:
                    block["locked_by"] = None
                    await broadcast({"type": "unlock", "block_id": block_id})

    except Exception as e:
        print(f"Error handling client {user_id}: {e}")
    finally:
        print(f"Client disconnected: {user_id}")
        if writer in state.clients:
            del state.clients[writer]
        await broadcast({"type": "user_leave", "user_id": user_id})
        # Unlock any blocks locked by this user
        for b in state.blocks:
            if b["locked_by"] == user_id:
                b["locked_by"] = None
                await broadcast({"type": "unlock", "block_id": b["id"]})
        writer.close()
        await writer.wait_closed()

async def run_process(block):
    block_id = block["id"]
    cmd = block["content"]
    cwd = block["cwd"]

    block["status"] = "running"
    await broadcast({"type": "update_block", "block": block})

    m, s = pty.openpty()
    try:
        # We need to use os.chdir temporarily or pass cwd to Popen
        # Note: changing global cwd might be risky if multiple processes start at same time
        # But subprocess.Popen has cwd argument
        p = await asyncio.create_subprocess_shell(
            cmd,
            stdout=s,
            stderr=s,
            stdin=s,
            executable=BASH_EXE,
            cwd=cwd,
            preexec_fn=os.setsid
        )
        state.active_processes[block_id] = p
        os.close(s)

        loop = asyncio.get_event_loop()
        while p.returncode is None:
            try:
                # Use loop.run_in_executor to avoid blocking the event loop on os.read
                data = await loop.run_in_executor(None, os.read, m, 4096)
                if data:
                    decoded_data = data.decode(errors="replace")
                    block["output"] += decoded_data
                    await broadcast({"type": "output", "block_id": block_id, "data": decoded_data})
                else:
                    break
            except OSError:
                break

        exit_code = await p.wait()
        block["status"] = "ok" if exit_code == 0 else f"error({exit_code})"
        await broadcast({"type": "update_block", "block": block})
    except Exception as e:
        err_msg = f"\nError: {e}"
        block["output"] += err_msg
        block["status"] = "error"
        await broadcast({"type": "output", "block_id": block_id, "data": err_msg})
        await broadcast({"type": "update_block", "block": block})
    finally:
        try: os.close(m)
        except: pass
        if block_id in state.active_processes:
            del state.active_processes[block_id]

async def main():
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    server = await asyncio.start_unix_server(handle_client, SOCKET_PATH)
    print(f"Server started on {SOCKET_PATH}")

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)
