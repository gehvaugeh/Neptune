import asyncio, json, os, uuid, signal, argparse, shutil, logging
from typing import Dict, List, Any, Optional
from common import HISTORY_FILE
from session_manager import SessionManager
from pty_manager import PTYManager

logging.basicConfig(filename='neptune_server.log', level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
DEFAULT_SOCKET_PATH = "/tmp/neptune.sock"

class Server:
    def __init__(self, socket_path=DEFAULT_SOCKET_PATH, enable_hist_expansion=False, clean_history=False):
        self.socket_path, self.enable_hist_expansion, self.clean_history = socket_path, enable_hist_expansion, clean_history
        if self.clean_history and os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "w") as f: f.truncate(0)
        self.session_manager = SessionManager()
        self.pty_manager = PTYManager(self.session_manager.broadcast, self.enable_hist_expansion)
        self.blocks, self.control_block_id = [], None

    def add_block(self, block_type, content, cwd=None, index=None, pty_id=None):
        pid = pty_id or self.pty_manager.default_pty_id
        if not cwd:
            pty = self.pty_manager.ptys.get(pid)
            if pty: cwd = pty.cwd
        block = {"id":str(uuid.uuid4()), "type":block_type, "content":content, "cwd":cwd or os.getcwd(), "output":"", "status":"ready", "locked_by":None, "pty_id":pid}
        if index is not None and 0 <= index <= len(self.blocks): self.blocks.insert(index, block)
        else: self.blocks.append(block)
        return block

    def get_block(self, block_id):
        for b in self.blocks:
            if b.get("id") == block_id: return b
        return None

    async def handle_client(self, reader, writer):
        user_id = str(uuid.uuid4())
        self.session_manager.clients[writer] = {"id": user_id, "color": "white"}
        try:
            while True:
                line = await reader.readline()
                if not line: break
                try: msg = json.loads(line.decode().strip())
                except: continue
                msg_type = msg.get("type")
                if msg_type == "connect":
                    c_info = self.session_manager.clients.get(writer)
                    if not c_info: continue
                    c_info.update({"color":msg.get("color","white"), "name":msg.get("user", user_id[:4])})
                    init_msg = {"type":"init", "blocks":self.blocks, "users":{c["id"]:{"color":c["color"],"name":c.get("name",c["id"][:4])} for c in self.session_manager.clients.values()}, "your_id":user_id, "ptys":self.pty_manager.list_ptys()}
                    writer.write(json.dumps(init_msg).encode() + b"\n"); await writer.drain()
                    await self.session_manager.broadcast({"type":"user_join", "user_id":user_id, "color":c_info.get("color"), "name":c_info.get("name")})
                elif msg_type == "submit":
                    idx = None
                    if msg.get("insert_after"):
                        t_idx = next((i for i, b in enumerate(self.blocks) if b.get("id") == msg.get("insert_after")), -1)
                        if t_idx != -1: idx = t_idx + 1
                    block = self.add_block(msg.get("mode"), msg.get("content"), index=idx, pty_id=msg.get("pty_id"))
                    if idx is not None: await self.session_manager.broadcast({"type":"reorder", "blocks":self.blocks})
                    else: await self.session_manager.broadcast({"type":"new_block", "block":block})
                    b_type = block.get("type")
                    b_pty_id = block["pty_id"]
                    if b_type == "CMD" and b_pty_id in self.pty_manager.ptys:
                        await self.pty_manager.ptys[b_pty_id].queue.put(block); await self.pty_manager.broadcast_queues_status()
                elif msg_type == "edit_start":
                    block = self.get_block(msg.get("block_id"))
                    if block:
                        b_locked_by = block["locked_by"]
                        if not b_locked_by or b_locked_by == user_id:
                            block["locked_by"] = user_id
                            await self.session_manager.broadcast({"type":"lock", "block_id":block.get("id"), "user_id":user_id, "user_color":self.session_manager.clients[writer]["color"], "user_name":self.session_manager.clients[writer]["name"]})
                        else:
                            locked_by = self.session_manager.clients.get(next((w for w, c in self.session_manager.clients.items() if c.get('id') == b_locked_by), None), {})
                            await self.session_manager.send_to_client(writer, json.dumps({"type":"lock_denied", "block_id":block.get("id"), "reason":f"Block is locked by {locked_by.get('name', b_locked_by[:4])}"}).encode()+b"\n", user_id)
                elif msg_type == "edit_save":
                    block = self.get_block(msg.get("block_id"))
                    if block and block["locked_by"] == user_id:
                        block["content"], block["locked_by"] = msg.get("content"), None
                        await self.session_manager.broadcast({"type":"update_block", "block":block}); await self.session_manager.broadcast({"type":"unlock", "block_id":block.get("id")})
                        b_type = block.get("type")
                        b_pty_id = block["pty_id"]
                        if b_type == "CMD" and b_pty_id in self.pty_manager.ptys:
                            block["output"] = ""; await self.pty_manager.ptys[b_pty_id].queue.put(block); await self.pty_manager.broadcast_queues_status()
                elif msg_type == "edit_cancel":
                    block = self.get_block(msg.get("block_id"))
                    if block and block["locked_by"] == user_id:
                        block["locked_by"] = None; await self.session_manager.broadcast({"type":"unlock", "block_id":block.get("id")})
                elif msg_type == "move_block":
                    idx = next((i for i, b in enumerate(self.blocks) if b["id"] == msg.get("block_id")), -1)
                    if idx != -1:
                        new_idx = idx - 1 if msg.get("direction") == "up" else idx + 1
                        if 0 <= new_idx < len(self.blocks):
                            self.blocks[idx], self.blocks[new_idx] = self.blocks[new_idx], self.blocks[idx]
                            await self.session_manager.broadcast({"type":"reorder", "blocks":self.blocks})
                elif msg_type == "delete_block":
                    block = self.get_block(msg.get("block_id"))
                    if block:
                        b_id = block.get("id")
                        self.blocks = [b for b in self.blocks if b["id"] != b_id]
                        await self.session_manager.broadcast({"type":"remove_block", "block_id":b_id})
                        for pty in self.pty_manager.ptys.values():
                            if pty.current_block_id == b_id: await pty.stop()
                        await self.pty_manager.broadcast_queues_status()
                elif msg_type == "stop_process":
                    for pty in self.pty_manager.ptys.values():
                        if pty.current_block_id == msg.get("block_id"): await pty.stop()
                elif msg_type == "paste_block":
                    idx = next((i for i, b in enumerate(self.blocks) if b["id"] == msg.get("target_id")), -1)
                    if idx != -1:
                        y = msg.get("yank_data", [])
                        if len(y) >= 2:
                            self.add_block(y[0], y[1], cwd=y[2] if len(y)>2 else None, index=idx+1 if msg.get("position")=="after" else idx)
                            await self.session_manager.broadcast({"type":"reorder", "blocks":self.blocks})
                elif msg_type == "run_block":
                    block = self.get_block(msg.get("block_id"))
                    if block and block.get("type") == "CMD":
                        if msg.get("pty_id"): block["pty_id"] = msg.get("pty_id")
                        block["output"] = ""
                        b_pty_id = block["pty_id"]
                        if b_pty_id in self.pty_manager.ptys:
                            await self.pty_manager.ptys[b_pty_id].queue.put(block); await self.pty_manager.broadcast_queues_status()
                elif msg_type == "clear_session":
                    for pty in self.pty_manager.ptys.values(): await pty.stop()
                    self.blocks, self.control_block_id = [], None
                    await self.session_manager.broadcast({"type":"reorder", "blocks":self.blocks}); await self.pty_manager.broadcast_queues_status()
                elif msg_type == "import_blocks":
                    self.blocks = []
                    for b_data in msg.get("blocks", []):
                        block = self.add_block(b_data.get("type"), b_data.get("content"), b_data.get("cwd"))
                        block.update({"output":b_data.get("output",""), "status":b_data.get("status","ready")})
                    await self.session_manager.broadcast({"type":"reorder", "blocks":self.blocks})
                elif msg_type == "control_start":
                    block = self.get_block(msg.get("block_id"))
                    if block:
                        b_locked_by = block["locked_by"]
                        if not b_locked_by or b_locked_by == user_id:
                            block["locked_by"], self.control_block_id = user_id, block.get("id")
                            await self.session_manager.broadcast({"type":"lock", "block_id":block.get("id"), "user_id":user_id, "user_color":self.session_manager.clients[writer]["color"], "user_name":self.session_manager.clients[writer]["name"]})
                        else:
                            locked_by = self.session_manager.clients.get(next((w for w, c in self.session_manager.clients.items() if c.get('id') == b_locked_by), None), {})
                            await self.session_manager.send_to_client(writer, json.dumps({"type":"lock_denied", "block_id":block.get("id"), "reason":f"Block is locked by {locked_by.get('name', b_locked_by[:4])}"}).encode()+b"\n", user_id)
                elif msg_type == "control_stop":
                    if self.control_block_id:
                        block = self.get_block(self.control_block_id)
                        if block and block["locked_by"] == user_id:
                            block["locked_by"], self.control_block_id = None, None
                            await self.session_manager.broadcast({"type":"unlock", "block_id":block.get("id")})
                elif msg_type == "terminal_input":
                    bid = msg.get("block_id") or self.control_block_id
                    if bid:
                        block = self.get_block(bid)
                        b_pty_id = block["pty_id"] if block else None
                        if block and b_pty_id in self.pty_manager.ptys: await self.pty_manager.ptys[b_pty_id].send_input(msg.get("data"))
                elif msg_type == "terminal_resize":
                    bid = self.control_block_id
                    b = self.get_block(bid) if bid else None
                    pid = msg.get("pty_id") or (b["pty_id"] if b else self.pty_manager.default_pty_id)
                    if pid in self.pty_manager.ptys: await self.pty_manager.ptys[pid].resize(msg.get("rows"), msg.get("cols"))
                elif msg_type == "terminal_set_echo":
                    pid = msg.get("pty_id") or self.pty_manager.default_pty_id
                    if pid in self.pty_manager.ptys:
                        pty = self.pty_manager.ptys[pid]
                        if isinstance(pty, LocalPTY): await pty.set_echo(msg.get("enabled", False))
                elif msg_type == "pty.create.local":
                    await self.pty_manager.create_local(msg.get("pty_id")); await self.session_manager.broadcast({"type":"pty.list", "ptys":self.pty_manager.list_ptys()})
                elif msg_type == "pty.create.remote":
                    pid = msg.get("pty_id")
                    try:
                        await self.pty_manager.create_remote(pid, msg.get("ssh_config"))
                        await self.session_manager.broadcast({"type":"pty.list", "ptys":self.pty_manager.list_ptys()})
                    except Exception as e:
                        await self.session_manager.send_to_client(writer, json.dumps({"type":"pty.error", "pty_id":pid, "error":"create_failed", "message":str(e)}).encode()+b"\n", user_id)
                elif msg_type == "pty.destroy":
                    await self.pty_manager.destroy(msg.get("pty_id")); await self.session_manager.broadcast({"type":"pty.list", "ptys":self.pty_manager.list_ptys()})
                elif msg_type == "pty.set_default":
                    if self.pty_manager.set_default(msg.get("pty_id")):
                        await self.session_manager.broadcast({"type":"pty.default_changed", "pty_id":msg.get("pty_id")})
                        await self.session_manager.broadcast({"type":"pty.list", "ptys":self.pty_manager.list_ptys()})
                elif msg_type == "pty.list":
                    await self.session_manager.send_to_client(writer, json.dumps({"type":"pty.list", "ptys":self.pty_manager.list_ptys()}).encode()+b"\n", user_id)
        except: pass
        finally:
            if writer in self.session_manager.clients: del self.session_manager.clients[writer]
            await self.session_manager.broadcast({"type":"user_leave", "user_id":user_id})
            for b in self.blocks:
                if b.get("locked_by") == user_id:
                    b["locked_by"] = None
                    if self.control_block_id == b.get("id"): self.control_block_id = None
                    await self.session_manager.broadcast({"type":"unlock", "block_id":b.get("id")})
            writer.close()
            try: await writer.wait_closed()
            except: pass

    async def start(self):
        await self.pty_manager.create_local("local-1")
        if os.path.exists(self.socket_path): os.remove(self.socket_path)
        s = await asyncio.start_unix_server(self.handle_client, self.socket_path, limit=10*1024*1024)
        print(f"Server started on {self.socket_path}")
        async with s:
            try: await s.serve_forever()
            finally:
                if os.path.exists(self.socket_path): os.remove(self.socket_path)
                for pty in list(self.pty_manager.ptys.values()): await pty.kill()

from pty_local import LocalPTY
from branding import setup_parser
if __name__ == "__main__":
    p = setup_parser("Neptune Server")
    p.add_argument("-s", "--socket", default=DEFAULT_SOCKET_PATH)
    p.add_argument("--enable-hist-expansion", action="store_true")
    p.add_argument("--clean-history", action="store_true")
    a = p.parse_args(); s = Server(a.socket, a.enable_hist_expansion, a.clean_history)
    try: asyncio.run(s.start())
    except KeyboardInterrupt: pass
