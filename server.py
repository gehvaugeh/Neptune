import asyncio
import json
import os
import pty
import subprocess
import uuid
import signal
import argparse
import shutil
import logging
import re
import fcntl
import termios
import struct
from typing import Dict, List, Any

# Setup logging
logging.basicConfig(
    filename='gemmi_server.log',
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s: %(message)s'
)

DEFAULT_SOCKET_PATH = "/tmp/gemmi_shell.sock"

def get_shell():
    env_shell = os.environ.get("SHELL")
    if env_shell and shutil.which(env_shell):
        return env_shell
    termux_bash = "/data/data/com.termux/files/usr/bin/bash"
    if os.path.exists(termux_bash):
        return termux_bash
    return shutil.which("bash") or shutil.which("sh") or "/bin/sh"

DEFAULT_SHELL = get_shell()

class Server:
    def __init__(self, socket_path=DEFAULT_SOCKET_PATH):
        self.socket_path = socket_path
        self.blocks = []  # List of dicts: {id, type, content, cwd, output, status, locked_by}
        self.clients = {} # writer: {id, color, name}
        self.active_processes = {} # legacy
        self.master_fd = None
        self.master_process = None
        self.command_queue = asyncio.Queue()
        self.current_block = None
        self.current_sentinel = None
        self.done_event = None
        self.init_done = asyncio.Event()

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

    async def broadcast(self, message):
        data = json.dumps(message).encode() + b"\n"
        logging.debug(f"Broadcasting: {message.get('type')}")

        # Copy clients to avoid mutation during iteration
        clients = list(self.clients.items())
        for writer, client_info in clients:
            asyncio.create_task(self.send_to_client(writer, data, client_info['id']))

    async def send_to_client(self, writer, data, user_id):
        try:
            if not writer.is_closing():
                writer.write(data)
                await asyncio.wait_for(writer.drain(), timeout=2.0)
        except Exception as e:
            logging.error(f"Removing unresponsive client {user_id}: {e}")
            if writer in self.clients:
                del self.clients[writer]
            try:
                writer.close()
                await writer.wait_closed()
            except: pass

    async def handle_client(self, reader, writer):
        user_id = str(uuid.uuid4())
        self.clients[writer] = {"id": user_id, "color": "white"}
        logging.info(f"Client connected: {user_id}")

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                line_str = line.decode().strip()
                if not line_str:
                    continue

                try:
                    msg = json.loads(line_str)
                except Exception as e:
                    logging.error(f"Error decoding JSON from {user_id}: {e} | Raw: {line_str}")
                    continue

                msg_type = msg.get("type")
                logging.debug(f"Received from {user_id}: {msg_type}")

                if msg_type == "connect":
                    user_color = msg.get("color", "white")
                    user_name = msg.get("user", user_id[:4])
                    self.clients[writer]["color"] = user_color
                    self.clients[writer]["name"] = user_name
                    logging.info(f"Client authorized: {user_id} ({user_name}, {user_color})")

                    # Send initial state
                    init_msg = {
                        "type": "init",
                        "blocks": self.blocks,
                        "users": {c["id"]: {"color": c["color"], "name": c.get("name", c["id"][:4])} for c in self.clients.values()},
                        "your_id": user_id
                    }
                    writer.write(json.dumps(init_msg).encode() + b"\n")
                    await writer.drain()

                    await self.broadcast({
                        "type": "user_join",
                        "user_id": user_id,
                        "color": user_color,
                        "name": user_name
                    })

                elif msg_type == "submit":
                    mode = msg.get("mode")
                    content = msg.get("content")
                    cwd = msg.get("cwd", os.getcwd())
                    logging.info(f"Received submit from {user_id}: {mode} - {content[:50]}")

                    block = self.add_block(mode, content, cwd)
                    await self.broadcast({"type": "new_block", "block": block})

                    if mode == "CMD":
                        await self.command_queue.put(block)

                elif msg_type == "edit_start":
                    block_id = msg.get("block_id")
                    logging.info(f"Edit start from {user_id} on {block_id}")
                    block = self.get_block(block_id)
                    if block and not block["locked_by"]:
                        block["locked_by"] = user_id
                        await self.broadcast({
                            "type": "lock",
                            "block_id": block_id,
                            "user_id": user_id,
                            "user_color": self.clients[writer]["color"],
                            "user_name": self.clients[writer].get("name", user_id[:4])
                        })

                elif msg_type == "edit_save":
                    block_id = msg.get("block_id")
                    content = msg.get("content")
                    block = self.get_block(block_id)
                    if block and block["locked_by"] == user_id:
                        block["content"] = content
                        block["locked_by"] = None
                        await self.broadcast({"type": "update_block", "block": block})
                        await self.broadcast({"type": "unlock", "block_id": block_id})

                        if block["type"] == "CMD":
                            block["output"] = ""
                            await self.command_queue.put(block)

                elif msg_type == "edit_cancel":
                    block_id = msg.get("block_id")
                    block = self.get_block(block_id)
                    if block and block["locked_by"] == user_id:
                        block["locked_by"] = None
                        await self.broadcast({"type": "unlock", "block_id": block_id})

                elif msg_type == "move_block":
                    block_id = msg.get("block_id")
                    direction = msg.get("direction") # "up" or "down"

                    idx = next((i for i, b in enumerate(self.blocks) if b["id"] == block_id), -1)
                    if idx != -1:
                        new_idx = idx - 1 if direction == "up" else idx + 1
                        if 0 <= new_idx < len(self.blocks):
                            self.blocks[idx], self.blocks[new_idx] = self.blocks[new_idx], self.blocks[idx]
                            await self.broadcast({"type": "reorder", "blocks": self.blocks})

                elif msg_type == "delete_block":
                    block_id = msg.get("block_id")
                    self.blocks = [b for b in self.blocks if b["id"] != block_id]
                    if self.current_block and self.current_block["id"] == block_id:
                        if self.master_fd:
                            os.write(self.master_fd, b'\x03')
                    await self.broadcast({"type": "remove_block", "block_id": block_id})

                elif msg_type == "stop_process":
                    if self.master_fd:
                        os.write(self.master_fd, b'\x03')

                elif msg_type == "paste_block":
                    target_id = msg.get("target_id")
                    position = msg.get("position")
                    yank_data = msg.get("yank_data") # ("TYPE", content, [cwd])

                    idx = next((i for i, b in enumerate(self.blocks) if b["id"] == target_id), -1)
                    if idx != -1:
                        new_block_type = yank_data[0]
                        new_block_content = yank_data[1]
                        new_block_cwd = yank_data[2] if len(yank_data) > 2 else os.getcwd()

                        new_block = {
                            "id": str(uuid.uuid4()),
                            "type": new_block_type,
                            "content": new_block_content,
                            "cwd": new_block_cwd,
                            "output": "",
                            "status": "ready",
                            "locked_by": None
                        }
                        if position == "after":
                            self.blocks.insert(idx + 1, new_block)
                        else:
                            self.blocks.insert(idx, new_block)
                        await self.broadcast({"type": "reorder", "blocks": self.blocks})

                elif msg_type == "run_block":
                    block_id = msg.get("block_id")
                    block = self.get_block(block_id)
                    if block and block["type"] == "CMD":
                        block["output"] = ""
                        await self.command_queue.put(block)

                elif msg_type == "terminal_input":
                    data = msg.get("data")
                    if self.master_fd and data:
                        os.write(self.master_fd, data.encode())

                elif msg_type == "terminal_resize":
                    rows = msg.get("rows", 24)
                    cols = msg.get("cols", 80)
                    if self.master_fd:
                        winsize = struct.pack("HHHH", rows, cols, 0, 0)
                        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)

                elif msg_type == "terminal_set_echo":
                    enabled = msg.get("enabled", False)
                    if self.master_fd:
                        attr = termios.tcgetattr(self.master_fd)
                        if enabled:
                            attr[3] |= termios.ECHO
                        else:
                            attr[3] &= ~termios.ECHO
                        termios.tcsetattr(self.master_fd, termios.TCSANOW, attr)

                elif msg_type == "clear_session":
                    if self.master_fd:
                        os.write(self.master_fd, b'\x03')
                    self.blocks = []
                    await self.broadcast({"type": "reorder", "blocks": self.blocks})

                elif msg_type == "import_blocks":
                    new_blocks = msg.get("blocks")
                    self.blocks = []
                    for b_data in new_blocks:
                        block = self.add_block(b_data["type"], b_data["content"], b_data.get("cwd"))
                        block["output"] = b_data.get("output", "")
                        block["status"] = b_data.get("status", "ready")

                    await self.broadcast({"type": "reorder", "blocks": self.blocks})

        except Exception as e:
            logging.error(f"Error handling client {user_id}: {e}")
        finally:
            logging.info(f"Client disconnected: {user_id}")
            if writer in self.clients:
                del self.clients[writer]
            await self.broadcast({"type": "user_leave", "user_id": user_id})
            # Unlock any blocks locked by this user
            for b in self.blocks:
                if b["locked_by"] == user_id:
                    b["locked_by"] = None
                    await self.broadcast({"type": "unlock", "block_id": b["id"]})
            writer.close()
            try:
                await writer.wait_closed()
            except: pass

    async def start_master_shell(self):
        m, s = pty.openpty()
        self.master_fd = m
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        self.master_process = await asyncio.create_subprocess_exec(
            DEFAULT_SHELL,
            stdin=s,
            stdout=s,
            stderr=s,
            preexec_fn=os.setsid,
            env=env
        )
        os.close(s)
        init_cmds = "stty -echo && export PS1='' PROMPT_COMMAND='' && clear\necho GS_INIT_DONE\n"
        os.write(self.master_fd, init_cmds.encode())
        asyncio.create_task(self.read_master_output())
        asyncio.create_task(self.process_queue())

    async def read_master_output(self):
        loop = asyncio.get_event_loop()
        while self.master_process.returncode is None:
            try:
                data = await loop.run_in_executor(None, os.read, self.master_fd, 4096)
                if not data: break
                decoded = data.decode(errors="replace")
                if "GS_INIT_DONE" in decoded:
                    self.init_done.set()
                if self.current_block:
                    await self.handle_master_output(decoded)
            except OSError: break
        logging.info("Master shell terminated")

    async def process_queue(self):
        await self.init_done.wait()
        while True:
            block = await self.command_queue.get()
            try:
                self.current_block = block
                self.current_sentinel = f"GS_DONE_{uuid.uuid4()}"
                block["status"] = "running"
                block["output"] = ""
                await self.broadcast({"type": "update_block", "block": block})
                full_cmd = f"cd {block['cwd']} 2>/dev/null; {block['content']}\necho {self.current_sentinel} $?\npwd\n"
                os.write(self.master_fd, full_cmd.encode())
                self.done_event = asyncio.Event()
                await self.done_event.wait()
            except Exception as e:
                logging.error(f"Error in process_queue: {e}")
            finally:
                self.current_block = None
                self.command_queue.task_done()

    async def handle_master_output(self, data):
        if not self.current_block:
            return

        self.current_block["output"] += data

        # Check if the sentinel is present in the output
        if self.current_sentinel and self.current_sentinel in self.current_block["output"]:
            pattern = rf'{self.current_sentinel}\s+(\d+)\s*\r?\n(.*?)\r?\n'
            match = re.search(pattern, self.current_block["output"], re.DOTALL)
            if match:
                exit_code, cwd = int(match.group(1)), match.group(2).strip()
                idx = match.start()
                self.current_block["output"] = self.current_block["output"][:idx]
                self.current_block["status"] = "ok" if exit_code == 0 else f"error({exit_code})"
                self.current_block["cwd"] = cwd
                await self.broadcast({"type": "update_block", "block": self.current_block})
                self.done_event.set()
                return

        await self.broadcast({"type": "output", "block_id": self.current_block["id"], "data": data})

    async def start(self):
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
        await self.start_master_shell()
        server = await asyncio.start_unix_server(self.handle_client, self.socket_path, limit=10 * 1024 * 1024)
        logging.info(f"Server started on {self.socket_path}")
        print(f"Server started on {self.socket_path}")
        print(f"Using shell: {DEFAULT_SHELL}")

        async with server:
            try:
                await server.serve_forever()
            finally:
                if os.path.exists(self.socket_path):
                    os.remove(self.socket_path)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemmi-Shell Server")
    parser.add_argument("-s", "--socket", default=DEFAULT_SOCKET_PATH, help="Path to the Unix Domain Socket")
    args = parser.parse_args()

    server = Server(socket_path=args.socket)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        pass
