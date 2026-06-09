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

    def add_block(self, block_type, content, cwd=None, index=None, pty_uid=None):
        uid = pty_uid
        if not cwd:
            # Default to local-0 (uid 0) if no UID provided and no CWD
            search_uid = uid if uid is not None else 0
            pty = self.pty_manager.ptys.get(search_uid)
            if pty: cwd = pty.cwd

        if uid is None:
            pty_name = "none"
        else:
            pty_name = self.pty_manager.names.get(uid, "unknown")

        block = {"id":str(uuid.uuid4()), "type":block_type, "content":content, "cwd":cwd or os.getcwd(), "output":"", "status":"ready", "locked_by":None, "pty_uid":uid, "pty_name": pty_name}
        if index is not None and 0 <= index <= len(self.blocks): self.blocks.insert(index, block)
        else: self.blocks.append(block)
        return block

    def get_block(self, block_id):
        for b in self.blocks:
            if b.get("id") == block_id: return b
        return None

    async def shutdown(self):
        print("Server: shutting down...")
        for pty in list(self.pty_manager.ptys.values()):
            await pty.kill()
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
        asyncio.get_running_loop().stop()

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

                    p_uid = msg.get("pty_uid")
                    try: p_uid = int(p_uid) if p_uid is not None else None
                    except: pass

                    block = self.add_block(msg.get("mode"), msg.get("content"), index=idx, pty_uid=p_uid)
                    if idx is not None: await self.session_manager.broadcast({"type":"reorder", "blocks":self.blocks})
                    else: await self.session_manager.broadcast({"type":"new_block", "block":block})
                    b_type = block.get("type")
                    b_pty_uid = block["pty_uid"]
                    if b_type == "CMD" and b_pty_uid in self.pty_manager.ptys:
                        await self.pty_manager.ptys[b_pty_uid].queue.put(block); await self.pty_manager.broadcast_queues_status()
                elif msg_type == "edit_start":
                    block = self.get_block(msg.get("block_id"))
                    if block:
                        b_locked_by = block.get("locked_by")
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
                        b_pty_uid = block["pty_uid"]
                        if b_type == "CMD" and b_pty_uid in self.pty_manager.ptys:
                            block["output"] = ""
                            await self.session_manager.broadcast({"type": "update_block", "block": block})
                            await self.pty_manager.ptys[b_pty_uid].queue.put(block); await self.pty_manager.broadcast_queues_status()
                elif msg_type == "edit_cancel":
                    block = self.get_block(msg.get("block_id"))
                    if block and block["locked_by"] == user_id:
                        block["locked_by"] = None; await self.session_manager.broadcast({"type":"unlock", "block_id":block.get("id")})
                elif msg_type == "move_block":
                    idx = next((i for i, b in enumerate(self.blocks) if b.get("id") == msg.get("block_id")), -1)
                    if idx != -1:
                        new_idx = idx - 1 if msg.get("direction") == "up" else idx + 1
                        if 0 <= new_idx < len(self.blocks):
                            self.blocks[idx], self.blocks[new_idx] = self.blocks[new_idx], self.blocks[idx]
                            await self.session_manager.broadcast({"type":"reorder", "blocks":self.blocks})
                elif msg_type == "delete_block":
                    block = self.get_block(msg.get("block_id"))
                    if block:
                        b_id = block.get("id")
                        # First terminate if running
                        for pty in self.pty_manager.ptys.values():
                            if pty.current_block_id == b_id:
                                await pty.stop()

                        self.blocks = [b for b in self.blocks if b["id"] != b_id]
                        await self.session_manager.broadcast({"type":"remove_block", "block_id":b_id})
                        await self.pty_manager.broadcast_queues_status()
                elif msg_type == "stop_process":
                    for pty in self.pty_manager.ptys.values():
                        if pty.current_block_id == msg.get("block_id"): await pty.stop()
                elif msg_type == "paste_block":
                    idx = next((i for i, b in enumerate(self.blocks) if b.get("id") == msg.get("target_id")), -1)
                    if idx != -1:
                        y = msg.get("yank_data", [])
                        if len(y) >= 2:
                            self.add_block(y[0], y[1], cwd=y[2] if len(y)>2 else None, index=idx+1 if msg.get("position")=="after" else idx, pty_uid=y[3] if len(y)>3 else None)
                            await self.session_manager.broadcast({"type":"reorder", "blocks":self.blocks})
                elif msg_type == "run_block":
                    block = self.get_block(msg.get("block_id"))
                    if block and block.get("type") == "CMD":
                        if msg.get("pty_uid") is not None:
                            p_uid = msg.get("pty_uid")
                            try: p_uid = int(p_uid)
                            except: pass
                            block["pty_uid"] = p_uid
                            block["pty_name"] = self.pty_manager.names.get(block["pty_uid"], "unknown")

                        if msg.get("only_update"):
                            # If block was running in another PTY, we must NOT just update metadata
                            # because it might be stuck in that PTY's queue or execution.
                            # But here we just want to update the target PTY for FUTURE runs.
                            await self.session_manager.broadcast({"type": "update_block", "block": block})
                            # We must ensure we don't return from the handle_client loop's if/elif block
                            # if we are inside a loop.
                            # Wait, 'return' here exits the handle_client function, closing the connection!
                            continue

                        block["output"] = ""
                        await self.session_manager.broadcast({"type": "update_block", "block": block})
                        b_pty_uid = block["pty_uid"]
                        if b_pty_uid in self.pty_manager.ptys:
                            await self.pty_manager.ptys[b_pty_uid].queue.put(block); await self.pty_manager.broadcast_queues_status()
                elif msg_type == "clear_session":
                    for pty in self.pty_manager.ptys.values():
                        await pty.stop()
                    self.blocks, self.control_block_id = [], None
                    await self.session_manager.broadcast({"type":"reorder", "blocks":self.blocks})
                    await self.pty_manager.broadcast_queues_status()
                elif msg_type == "import_blocks":
                    self.blocks = []
                    for b_data in msg.get("blocks", []):
                        block = self.add_block(b_data.get("type"), b_data.get("content"), b_data.get("cwd"), pty_uid=b_data.get("pty_uid"))
                        block.update({"output":b_data.get("output",""), "status":b_data.get("status","ready")})
                    await self.session_manager.broadcast({"type":"reorder", "blocks":self.blocks})
                elif msg_type == "control_start":
                    block = self.get_block(msg.get("block_id"))
                    if block:
                        b_locked_by = block.get("locked_by")
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
                        b_pty_uid = block["pty_uid"] if block else None
                        if block and b_pty_uid in self.pty_manager.ptys: await self.pty_manager.ptys[b_pty_uid].send_input(msg.get("data"))
                elif msg_type == "terminal_resize":
                    bid = self.control_block_id
                    b = self.get_block(bid) if bid else None
                    uid = msg.get("pty_uid") if msg.get("pty_uid") is not None else (b["pty_uid"] if b else 0)
                    try: uid = int(uid)
                    except: pass

                    rows, cols = msg.get("rows"), msg.get("cols")
                    self.pty_manager.terminal_size = (rows, cols)
                    if uid in self.pty_manager.ptys: await self.pty_manager.ptys[uid].resize(rows, cols)
                elif msg_type == "terminal_set_echo":
                    uid = msg.get("pty_uid") if msg.get("pty_uid") is not None else 0
                    try: uid = int(uid)
                    except: pass
                    if uid in self.pty_manager.ptys:
                        pty = self.pty_manager.ptys[uid]
                        if isinstance(pty, LocalPTY): await pty.set_echo(msg.get("enabled", False))
                elif msg_type == "pty.create.local":
                    pty = await self.pty_manager.create_local(msg.get("name"))
                    await self.session_manager.broadcast({"type":"pty.list", "ptys":self.pty_manager.list_ptys()})
                elif msg_type == "pty.create.remote":
                    try:
                        pty = await self.pty_manager.create_remote(msg.get("ssh_config"), msg.get("name"))
                        await self.session_manager.broadcast({"type":"pty.list", "ptys":self.pty_manager.list_ptys()})
                    except Exception as e:
                        await self.session_manager.send_to_client(writer, json.dumps({"type":"pty.error", "error":"create_failed", "message":str(e)}).encode()+b"\n", user_id)
                elif msg_type == "pty.destroy":
                    try: uid = int(msg.get("pty_uid"))
                    except: uid = msg.get("pty_uid")
                    await self.pty_manager.destroy(uid)
                    # Update block references on the server
                    for b in self.blocks:
                        if b.get("pty_uid") == uid:
                            b["pty_uid"] = None
                            b["pty_name"] = "deleted"
                            if b.get("status") == "running":
                                b["status"] = "killed"
                            await self.session_manager.broadcast({"type": "update_block", "block": b})
                    await self.session_manager.broadcast({"type":"pty.list", "ptys":self.pty_manager.list_ptys()})
                elif msg_type == "pty.set_default":
                    # Server no longer tracks global default, but we can still broadcast a nudge if needed.
                    # Actually, we'll just ignore this and let the client manage it.
                    pass
                elif msg_type == "pty.rename":
                    try: uid = int(msg.get("pty_uid"))
                    except: uid = msg.get("pty_uid")
                    if self.pty_manager.rename_pty(uid, msg.get("name")):
                        # Update blocks that use this PTY to show the new name
                        for b in self.blocks:
                            if b.get("pty_uid") == uid:
                                b["pty_name"] = msg.get("name")
                                await self.session_manager.broadcast({"type":"update_block", "block":b})
                        await self.session_manager.broadcast({"type":"pty.list", "ptys":self.pty_manager.list_ptys()})
                elif msg_type == "pty.list":
                    await self.session_manager.send_to_client(writer, json.dumps({"type":"pty.list", "ptys":self.pty_manager.list_ptys()}).encode()+b"\n", user_id)
                elif msg_type == "shutdown":
                    await self.shutdown()
                    return
                elif msg_type == "autocomplete_query":
                    _msg, _writer, _uid = msg, writer, user_id
                    async def handle_autocomplete():
                        try:
                            uid = _msg.get("pty_uid", 0)
                            query = _msg.get("query", "")
                            request_id = _msg.get("request_id")
                            logging.debug(f"Server: Received autocomplete_query for UID {uid}, query: '{query}' rid={request_id}")

                            uid = int(uid) if uid else 0

                            results = []
                            if uid in self.pty_manager.ptys:
                                results = await self.pty_manager.ptys[uid].get_completions(query)
                                logging.debug(f"Server: get_completions returned {len(results)} items")
                            else:
                                logging.warning(f"Server: UID {uid} not found in ptys")

                            resp = {"type": "autocomplete_response", "results": results, "request_id": request_id}
                            resp_str = json.dumps(resp)
                            logging.debug(f"Server: Sending autocomplete_response rid={request_id}, {len(results)} items")
                            await self.session_manager.send_to_client(_writer, resp_str.encode() + b"\n", _uid)
                            logging.debug(f"Server: Sent autocomplete_response rid={request_id}")
                        except Exception as e:
                            logging.error(f"Server: autocomplete error: {type(e).__name__}: {e}")

                    asyncio.create_task(handle_autocomplete())
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
        await self.pty_manager.create_local("local-0")
        # Remove stale SSH ControlMaster sockets from previous runs
        cwd = os.getcwd()
        cleaned = []
        for f in os.listdir(cwd):
            if f.startswith("neptune-") and f.endswith(".sock"):
                try:
                    os.remove(os.path.join(cwd, f))
                    cleaned.append(f)
                except:
                    pass
        if cleaned:
            print(f"Recovery: removed stale socket(s): {', '.join(cleaned)}")
        if os.path.exists(self.socket_path): os.remove(self.socket_path)
        s = await asyncio.start_unix_server(self.handle_client, self.socket_path, limit=10*1024*1024)
        print(f"Server started on {self.socket_path}")

        # Signal-Handler für graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))

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
