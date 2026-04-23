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
import termios
import re
import fcntl
import struct
from typing import Dict, List, Any, Optional, Tuple

# Setup logging
logging.basicConfig(
    filename='neptune_server.log',
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s: %(message)s'
)

DEFAULT_SOCKET_PATH = "/tmp/neptune.sock"

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
        self.active_processes = {} # block_id: process (maintained for compatibility/tracking)

        self.master_fd = None
        self.master_proc = None
        self.command_queue = []
        self.queue_condition = asyncio.Condition()
        self.current_block_id = None
        self.current_sentinel = None
        self.current_command_finished = asyncio.Event()
        self.shell_cwd = os.getcwd()

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

    async def broadcast_queue_status(self):
        async with self.queue_condition:
            for i, block in enumerate(self.command_queue):
                status = f"queued({i+1})"
                if block["status"] != status:
                    block["status"] = status
                    await self.broadcast({"type": "update_block", "block": block})

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
                    block["cwd"] = self.shell_cwd
                    await self.broadcast({"type": "new_block", "block": block})

                    if mode == "CMD":
                        async with self.queue_condition:
                            self.command_queue.append(block)
                            self.queue_condition.notify_all()
                        await self.broadcast_queue_status()

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
                            async with self.queue_condition:
                                if block not in self.command_queue:
                                    self.command_queue.append(block)
                                    self.queue_condition.notify_all()
                            await self.broadcast_queue_status()

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
                    async with self.queue_condition:
                        self.command_queue = [b for b in self.command_queue if b["id"] != block_id]
                    if self.current_block_id == block_id:
                        if self.master_fd:
                            os.write(self.master_fd, b'\x03')
                    await self.broadcast({"type": "remove_block", "block_id": block_id})
                    await self.broadcast_queue_status()

                elif msg_type == "stop_process":
                    block_id = msg.get("block_id")
                    if self.current_block_id == block_id and self.master_proc:
                        try:
                            os.killpg(os.getpgid(self.master_proc.pid), signal.SIGINT)
                        except Exception as e:
                            logging.error(f"Error stopping process: {e}")

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
                        async with self.queue_condition:
                            if block not in self.command_queue:
                                self.command_queue.append(block)
                                self.queue_condition.notify_all()
                        await self.broadcast_queue_status()

                elif msg_type == "clear_session":
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

                elif msg_type == "terminal_input":
                    data = msg.get("data")
                    if self.master_fd and data:
                        # For Ctrl+C, we send it to the process group to ensure it reaches
                        # children even if they are in a different foreground group
                        if data == "\x03" and self.master_proc:
                            try:
                                os.killpg(os.getpgid(self.master_proc.pid), signal.SIGINT)
                            except Exception as e:
                                logging.error(f"Error sending SIGINT: {e}")

                        os.write(self.master_fd, data.encode())

                elif msg_type == "terminal_resize":
                    rows = msg.get("rows")
                    cols = msg.get("cols")
                    if self.master_fd and rows and cols:
                        winsize = struct.pack("HHHH", rows, cols, 0, 0)
                        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)

                elif msg_type == "terminal_set_echo":
                    enabled = msg.get("enabled", False)
                    if self.master_fd:
                        try:
                            attr = termios.tcgetattr(self.master_fd)
                            if enabled:
                                attr[3] |= termios.ECHO
                            else:
                                attr[3] &= ~termios.ECHO
                            termios.tcsetattr(self.master_fd, termios.TCSANOW, attr)
                        except Exception as e:
                            logging.error(f"Error setting terminal echo: {e}")

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
        if self.master_proc and self.master_proc.returncode is None:
            return

        logging.info("Starting master shell session...")
        if hasattr(self, 'reader_task') and not self.reader_task.done():
            logging.debug("Cancelling previous reader task")
            self.reader_task.cancel()

        m, s = pty.openpty()
        try:
            attr = termios.tcgetattr(s)
            attr[3] &= ~termios.ECHO
            termios.tcsetattr(s, termios.TCSANOW, attr)
        except Exception as e:
            logging.error(f"Failed to set TTY attributes: {e}")

        self.master_fd = m
        env = dict(os.environ)
        env["PS1"] = ""
        env["PS2"] = ""
        env["PROMPT_COMMAND"] = ""
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"

        # Use --noediting to disable readline which can cause issues with echo and escape codes
        self.master_proc = await asyncio.create_subprocess_exec(
            DEFAULT_SHELL, "--noediting", "--norc", "--noprofile",
            stdin=s,
            stdout=s,
            stderr=s,
            preexec_fn=os.setsid,
            env=env
        )
        os.close(s)
        logging.info(f"Master shell started (PID: {self.master_proc.pid})")

        # Disable echo explicitly
        os.write(self.master_fd, b"stty -echo\n")

        self.reader_task = asyncio.create_task(self.master_shell_reader())
        if not hasattr(self, 'executor_task') or self.executor_task.done():
            self.executor_task = asyncio.create_task(self.master_shell_executor())

    async def master_shell_reader(self):
        loop = asyncio.get_event_loop()
        buffer = ""

        try:
            while True:
                try:
                    data = await loop.run_in_executor(None, os.read, self.master_fd, 4096)
                    if not data:
                        logging.info("Master shell PTY closed")
                        break

                    decoded_data = data.decode(errors="replace")
                    logging.debug(f"PTY READ: {decoded_data!r}")
                    buffer += decoded_data

                    # Capture current context to handle possible transitions
                    active_block_id = self.current_block_id
                    active_sentinel = self.current_sentinel

                    if active_block_id and active_sentinel:
                        block = self.get_block(active_block_id)
                        if block:
                            while True:
                                # Look for sentinel
                                # We allow optional carriage returns and strip them later
                                pattern = rf'{re.escape(active_sentinel)}_(-?\d+)_([^\r\n]*?)__'
                                match = re.search(pattern, buffer)
                                if match:
                                    logging.debug(f"Sentinel matched: {match.group(0)}")
                                    before_sentinel = buffer[:match.start()]

                                    # Clean up trailing newlines/prompts before sentinel
                                    # often the shell outputs a newline before the next command
                                    if before_sentinel:
                                        block["output"] += before_sentinel
                                        await self.broadcast({"type": "output", "block_id": active_block_id, "data": before_sentinel})

                                    exit_code = int(match.group(1))
                                    new_cwd = match.group(2).strip()
                                    logging.info(f"Command finished. Exit: {exit_code}, CWD: {new_cwd}")

                                    block["status"] = "ok" if exit_code == 0 else f"error({exit_code})"
                                    block["cwd"] = new_cwd
                                    self.shell_cwd = new_cwd

                                    await self.broadcast({"type": "update_block", "block": block})

                                    buffer = buffer[match.end():]
                                    self.current_command_finished.set()
                                    break # Command finished, wait for next one
                                else:
                                    # Handle output before sentinel
                                    # To avoid sending a partial sentinel, we find the first char of the sentinel
                                    s_idx = buffer.find(active_sentinel[0])
                                    if s_idx == -1:
                                        # No start of sentinel, safe to send all
                                        if buffer:
                                            block["output"] += buffer
                                            await self.broadcast({"type": "output", "block_id": active_block_id, "data": buffer})
                                            buffer = ""
                                        break
                                    elif s_idx > 0:
                                        # Send everything before the potential sentinel
                                        to_send = buffer[:s_idx]
                                        block["output"] += to_send
                                        await self.broadcast({"type": "output", "block_id": active_block_id, "data": to_send})
                                        buffer = buffer[s_idx:]

                                    # If buffer starts with sentinel but no match yet, it's partial. Wait.
                                    break
                    else:
                        if buffer:
                            # logging.debug(f"Unrouted shell output: {buffer!r}")
                            buffer = ""
                except OSError:
                    logging.info("Master shell PTY error/closed")
                    break
                except Exception as e:
                    logging.error(f"Error in master_shell_reader: {e}")
                    break
        finally:
            self.current_command_finished.set() # Wake up any waiting executor

    async def master_shell_executor(self):
        while True:
            try:
                async with self.queue_condition:
                    while not self.command_queue:
                        await self.queue_condition.wait()
                    block = self.command_queue.pop(0)

                block["status"] = "running"
                await self.broadcast({"type": "update_block", "block": block})
                await self.broadcast_queue_status()

                # Ensure master shell and reader are alive
                if not self.master_proc or self.master_proc.returncode is not None or self.reader_task.done():
                    logging.info("Restarting master shell before command...")
                    await self.start_master_shell()
                    # Small delay to let shell initialize
                    await asyncio.sleep(0.5)

                self.current_block_id = block["id"]
                self.current_sentinel = f"__GEMMI_END_{os.urandom(4).hex()}"
                self.current_command_finished.clear()

                block["status"] = "running"
                await self.broadcast({"type": "update_block", "block": block})

                cmd = block["content"].strip()
                sentinel = self.current_sentinel
                # Robust command wrapper that handles comments, multi-line, and signals
                # We use a subshell and trap to ensure the sentinel is always printed
                # even if the inner command is interrupted.
                full_cmd = (
                    f"bash -c \"trap 'printf \\\"\\\\n{sentinel}_130_%s__\\\\n\\\" \\\"\\$(pwd)\\\"; exit 130' SIGINT; "
                    f"{{ {cmd} ; }} ; __R=\\$? ; __D=\\$(pwd) ; "
                    f"printf \\\"\\\\n{sentinel}_%s_%s__\\\\n\\\" \\\"\\$__R\\\" \\\"\\$__D\\\"\"\n"
                )
                logging.info(f"Executing block {block['id'][:8]}: {cmd!r}")

                try:
                    os.write(self.master_fd, full_cmd.encode())
                    # Wait for sentinel, but check if process dies
                    while not self.current_command_finished.is_set():
                        if self.master_proc.returncode is not None or self.reader_task.done():
                            block["status"] = "error (shell died)"
                            await self.broadcast({"type": "update_block", "block": block})
                            break
                        await asyncio.sleep(0.1)
                except Exception as e:
                    logging.error(f"Error executing command: {e}")
                    block["status"] = "error"
                    await self.broadcast({"type": "update_block", "block": block})
                finally:
                    self.current_block_id = None
            except Exception as e:
                logging.error(f"Error in executor loop: {e}")
                await asyncio.sleep(1)

    async def start(self):
        await self.start_master_shell()
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

from branding import setup_parser

if __name__ == "__main__":
    parser = setup_parser("Neptune Server")
    parser.add_argument("-s", "--socket", default=DEFAULT_SOCKET_PATH, help="Path to the Unix Domain Socket")
    args = parser.parse_args()

    server = Server(socket_path=args.socket)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        pass
