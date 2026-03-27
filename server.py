import asyncio
import json
import os
import pty
import uuid
import signal
import argparse
import logging
from typing import Dict, List, Any

from common import get_shell

# Setup logging
logging.basicConfig(
    filename='gemmi_server.log',
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s: %(message)s'
)

DEFAULT_SOCKET_PATH = "/tmp/gemmi_shell.sock"
DEFAULT_SHELL = get_shell()

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
    clients = list(state.clients.items())
    for writer, client_info in clients:
        asyncio.create_task(send_to_client(writer, data, client_info['id']))

async def send_to_client(writer, data, user_id):
    try:
        if not writer.is_closing():
            writer.write(data)
            await asyncio.wait_for(writer.drain(), timeout=2.0)
    except:
        if writer in state.clients: del state.clients[writer]
        try: writer.close(); await writer.wait_closed()
        except: pass

async def handle_client(reader, writer):
    user_id = str(uuid.uuid4())
    state.clients[writer] = {"id": user_id, "color": "white"}
    try:
        while True:
            line = await reader.readline()
            if not line: break
            try:
                msg = json.loads(line.decode().strip())
                msg_type = msg.get("type")
                if msg_type == "connect":
                    user_color = msg.get("color", "white")
                    state.clients[writer]["color"] = user_color
                    init_msg = {"type": "init", "blocks": state.blocks, "users": {c["id"]: c["color"] for c in state.clients.values()}, "your_id": user_id}
                    writer.write(json.dumps(init_msg).encode() + b"\n")
                    await writer.drain()
                    await broadcast({"type": "user_join", "user_id": user_id, "color": user_color})
                elif msg_type == "submit":
                    block = state.add_block(msg.get("mode"), msg.get("content"), msg.get("cwd", os.getcwd()))
                    await broadcast({"type": "new_block", "block": block})
                    if block["type"] == "CMD": asyncio.create_task(run_process(block, DEFAULT_SHELL))
                elif msg_type == "edit_start":
                    block_id = msg.get("block_id"); block = state.get_block(block_id)
                    if block and not block["locked_by"]:
                        block["locked_by"] = user_id
                        await broadcast({"type": "lock", "block_id": block_id, "user_id": user_id, "user_color": state.clients[writer]["color"]})
                elif msg_type == "edit_save":
                    block_id, content = msg.get("block_id"), msg.get("content"); block = state.get_block(block_id)
                    if block and block["locked_by"] == user_id:
                        block["content"], block["locked_by"] = content, None
                        await broadcast({"type": "update_block", "block": block}); await broadcast({"type": "unlock", "block_id": block_id})
                        if block["type"] == "CMD": block["output"] = ""; asyncio.create_task(run_process(block, DEFAULT_SHELL))
                elif msg_type == "edit_cancel":
                    block_id = msg.get("block_id"); block = state.get_block(block_id)
                    if block and block["locked_by"] == user_id: block["locked_by"] = None; await broadcast({"type": "unlock", "block_id": block_id})
                elif msg_type == "move_block":
                    block_id, direction = msg.get("block_id"), msg.get("direction")
                    idx = next((i for i, b in enumerate(state.blocks) if b["id"] == block_id), -1)
                    if idx != -1:
                        new_idx = idx - 1 if direction == "up" else idx + 1
                        if 0 <= new_idx < len(state.blocks):
                            state.blocks[idx], state.blocks[new_idx] = state.blocks[new_idx], state.blocks[idx]
                            await broadcast({"type": "reorder", "blocks": state.blocks})
                elif msg_type == "delete_block":
                    block_id = msg.get("block_id"); state.blocks = [b for b in state.blocks if b["id"] != block_id]
                    if block_id in state.active_processes:
                        p = state.active_processes[block_id]
                        try: os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                        except: pass
                        del state.active_processes[block_id]
                    await broadcast({"type": "remove_block", "block_id": block_id})
                elif msg_type == "stop_process":
                    block_id = msg.get("block_id"); p = state.active_processes.get(block_id)
                    if p:
                        try: os.killpg(os.getpgid(p.pid), signal.SIGINT)
                        except: pass
                elif msg_type == "paste_block":
                    target_id, pos, yank = msg.get("target_id"), msg.get("position"), msg.get("yank_data")
                    idx = next((i for i, b in enumerate(state.blocks) if b["id"] == target_id), -1)
                    if idx != -1:
                        new_block = {"id": str(uuid.uuid4()), "type": yank[0], "content": yank[1], "cwd": yank[2] if len(yank) > 2 else os.getcwd(), "output": "", "status": "ready", "locked_by": None}
                        state.blocks.insert(idx + 1 if pos == "after" else idx, new_block); await broadcast({"type": "reorder", "blocks": state.blocks})
                elif msg_type == "run_block":
                    block = state.get_block(msg.get("block_id"))
                    if block and block["type"] == "CMD": block["output"] = ""; asyncio.create_task(run_process(block, DEFAULT_SHELL))
                elif msg_type == "clear_session":
                    for p in state.active_processes.values():
                        try: os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                        except: pass
                    state.blocks, state.active_processes = [], {}; await broadcast({"type": "reorder", "blocks": state.blocks})
                elif msg_type == "import_blocks":
                    new_blocks = msg.get("blocks"); state.blocks = []
                    for b_data in new_blocks:
                        block = state.add_block(b_data["type"], b_data["content"], b_data.get("cwd"))
                        block["output"], block["status"] = b_data.get("output", ""), b_data.get("status", "ready")
                    await broadcast({"type": "reorder", "blocks": state.blocks})
            except: continue
    except: pass
    finally:
        if writer in state.clients: del state.clients[writer]
        await broadcast({"type": "user_leave", "user_id": user_id})
        for b in state.blocks:
            if b["locked_by"] == user_id: b["locked_by"] = None; await broadcast({"type": "unlock", "block_id": b["id"]})
        writer.close(); await writer.wait_closed()

async def run_process(block, shell_exe):
    block_id, cmd, cwd = block["id"], block["content"], block["cwd"]; block["status"] = "running"; await broadcast({"type": "update_block", "block": block})
    m, s = pty.openpty()
    try:
        p = await asyncio.create_subprocess_shell(cmd, stdout=s, stderr=s, stdin=s, executable=shell_exe, cwd=cwd, preexec_fn=os.setsid); state.active_processes[block_id] = p; os.close(s)
        loop = asyncio.get_event_loop()
        while p.returncode is None:
            try:
                data = await loop.run_in_executor(None, os.read, m, 4096)
                if data:
                    decoded = data.decode(errors="replace"); block["output"] += decoded
                    await broadcast({"type": "output", "block_id": block_id, "data": decoded})
                else: break
            except OSError: break
        block["status"] = "ok" if await p.wait() == 0 else f"error({p.returncode})"
        await broadcast({"type": "update_block", "block": block})
    except Exception as e:
        err_msg = f"\nError: {e}"; block["output"] += err_msg; block["status"] = "error"
        await broadcast({"type": "output", "block_id": block_id, "data": err_msg}); await broadcast({"type": "update_block", "block": block})
    finally:
        try: os.close(m)
        except: pass
        if block_id in state.active_processes: del state.active_processes[block_id]

async def main(socket_path):
    if os.path.exists(socket_path): os.remove(socket_path)
    server = await asyncio.start_unix_server(handle_client, socket_path, limit=10 * 1024 * 1024)
    async with server:
        try: await server.serve_forever()
        finally:
            if os.path.exists(socket_path): os.remove(socket_path)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemmi-Shell Server")
    parser.add_argument("-s", "--socket", default=DEFAULT_SOCKET_PATH, help="Path to the Unix Domain Socket")
    args = parser.parse_args()
    try: asyncio.run(main(args.socket))
    except KeyboardInterrupt: pass
