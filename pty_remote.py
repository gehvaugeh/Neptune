import asyncio
import asyncssh
import uuid
import logging
import re
from typing import Optional, Callable, Awaitable, Dict
from pty_base import BasePTY

TUI_COMMANDS = {"vim", "vi", "nano", "htop", "top", "less", "more", "man", "tmux", "neptune"}

class RemotePTY(BasePTY):
    def __init__(self, pty_id: str, broadcast_func: Callable[[dict], Awaitable[None]]):
        super().__init__(pty_id)
        self.broadcast = broadcast_func
        self.conn: Optional[asyncssh.SSHClientConnection] = None
        self.chan: Optional[asyncssh.SSHClientChannel] = None
        self.reader_task: Optional[asyncio.Task] = None
        self.ssh_config: Dict = {}
        self.current_sentinel: Optional[str] = None
        self.command_finished = asyncio.Event()
        self.buffer = ""
        self.timeout = 30.0

    @property
    def cwd(self) -> str:
        return "" # CWD tracking remote not implemented for this milestone

    async def connect(self, ssh_config: dict):
        self.ssh_config = ssh_config
        self.timeout = float(ssh_config.get("timeout", 30.0))
        host, user, key_path = ssh_config.get("host"), ssh_config.get("user"), ssh_config.get("key")

        logging.info(f"[{self.pty_id}] Connecting to {user}@{host}...")
        try:
            self.conn = await asyncssh.connect(host, username=user, client_keys=[key_path] if key_path else None, known_hosts=None)
            self.chan, _ = await self.conn.create_session(asyncssh.SSHClientProcess, term_type='xterm-256color', request_pty=True)
            self.reader_task = asyncio.create_task(self.remote_reader())
            await self.send_input("export PS1='NEPTUNE> '\n")
            logging.info(f"[{self.pty_id}] Connected to {host}")
        except Exception as e:
            logging.error(f"[{self.pty_id}] SSH Connection failed: {e}")
            await self.broadcast({"type": "pty.error", "pty_id": self.pty_id, "error": "connection_failed", "message": str(e)})
            raise

    async def remote_reader(self):
        try:
            while True:
                data = await self.chan.read(4096)
                if not data: break
                self.buffer += data
                await self.process_buffer()
        except Exception as e:
            logging.error(f"[{self.pty_id}] Remote reader error: {e}")
            await self.broadcast({"type": "pty.error", "pty_id": self.pty_id, "error": "connection_lost", "message": str(e)})
        finally:
            self.command_finished.set()

    async def process_buffer(self):
        if not self.current_block_id:
            self.buffer = ""
            return

        if self.mode == "sentinel" and self.current_sentinel:
            pattern = rf'NEPTUNE_SENTINEL:{re.escape(self.current_sentinel)}:(-?\d+)'
            match = re.search(pattern, self.buffer)
            if match:
                before = self.buffer[:match.start()]
                if before: await self.broadcast({"type": "output", "block_id": self.current_block_id, "data": before, "pty_id": self.pty_id})
                exit_code = int(match.group(1))
                await self.broadcast({"type": "update_block", "block": {"id": self.current_block_id, "status": "ok" if exit_code == 0 else f"error({exit_code})", "pty_id": self.pty_id}})
                self.buffer = self.buffer[match.end():]
                if self.buffer.startswith('\r\n'): self.buffer = self.buffer[2:]
                elif self.buffer.startswith('\n'): self.buffer = self.buffer[1:]
                self.command_finished.set()
            else:
                s_idx = self.buffer.find('NEPTUNE_SENTINEL')
                if s_idx == -1:
                    await self.broadcast({"type": "output", "block_id": self.current_block_id, "data": self.buffer, "pty_id": self.pty_id})
                    self.buffer = ""
                elif s_idx > 0:
                    await self.broadcast({"type": "output", "block_id": self.current_block_id, "data": self.buffer[:s_idx], "pty_id": self.pty_id})
                    self.buffer = self.buffer[s_idx:]
        elif self.mode == "interactive":
            pattern = r'NEPTUNE_TUI_DONE:(-?\d+)'
            match = re.search(pattern, self.buffer)
            if match:
                before = self.buffer[:match.start()]
                before = re.sub(r'NEPTUNE_PID:\d+\r?\n?', '', before)
                if before: await self.broadcast({"type": "output", "block_id": self.current_block_id, "data": before, "pty_id": self.pty_id})
                exit_code = int(match.group(1))
                await self.broadcast({"type": "update_block", "block": {"id": self.current_block_id, "status": "ok" if exit_code == 0 else f"error({exit_code})", "pty_id": self.pty_id}})
                self.buffer = self.buffer[match.end():]
                if self.buffer.startswith('\r\n'): self.buffer = self.buffer[2:]
                elif self.buffer.startswith('\n'): self.buffer = self.buffer[1:]
                self.command_finished.set()
            else:
                if self.buffer and 'NEPTUNE_' not in self.buffer:
                    await self.broadcast({"type": "output", "block_id": self.current_block_id, "data": self.buffer, "pty_id": self.pty_id})
                    self.buffer = ""

    async def run_command(self, block: dict) -> None:
        if not self.conn: await self.connect(self.ssh_config)
        self.current_block_id = block["id"]
        self.command_finished.clear()
        self.buffer = ""
        cmd = block["content"].strip()
        first_word = cmd.split()[0] if cmd.split() else ""
        is_tui = first_word in TUI_COMMANDS
        if is_tui:
            self.mode = "interactive"
            wrapped_cmd = f"({cmd}) & NEPTUNE_PID=$!; echo NEPTUNE_PID:$NEPTUNE_PID; wait $NEPTUNE_PID; echo NEPTUNE_TUI_DONE:$?\n"
        else:
            self.mode, self.current_sentinel = "sentinel", uuid.uuid4().hex
            wrapped_cmd = f"({cmd}); NEPTUNE_EXIT=$?; echo 'NEPTUNE_SENTINEL:{self.current_sentinel}:'$NEPTUNE_EXIT\n"
        self.chan.write(wrapped_cmd)
        try:
            await asyncio.wait_for(self.command_finished.wait(), timeout=self.timeout)
        except asyncio.TimeoutError:
            logging.warning(f"[{self.pty_id}] Command timed out")
            await self.broadcast({"type": "update_block", "block": {"id": self.current_block_id, "status": "error(timeout)", "pty_id": self.pty_id}})
        finally:
            self.current_block_id, self.current_sentinel, self.mode = None, None, "sentinel"

    async def send_input(self, data: str) -> None:
        if self.chan: self.chan.write(data)

    async def stop(self) -> None:
        await self.send_input("\x03") # Simple stop for remote

    async def kill(self) -> None:
        if self.conn: self.conn.close(); await self.conn.wait_closed()
        if self.reader_task: self.reader_task.cancel()

    def is_running(self) -> bool:
        return self.chan is not None and not self.chan.is_closing()

    async def resize(self, rows: int, cols: int) -> None:
        if self.chan: self.chan.set_terminal_size(cols, rows)
