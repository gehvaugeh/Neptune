import asyncio, os, pty, termios, struct, fcntl, signal, re, logging
from typing import Optional, Callable, Awaitable
from pty_base import BasePTY
from common import HISTORY_FILE, get_shell

TUI_CMDS = {"vim", "vi", "nano", "htop", "top", "less", "more", "man", "tmux", "neptune"}

class LocalPTY(BasePTY):
    def __init__(self, pty_uid: int, pty_id: str, broadcast: Callable[[dict], Awaitable[None]], hist_exp: bool = False):
        super().__init__(pty_uid, pty_id)
        self.broadcast, self.hist_exp = broadcast, hist_exp
        self.master_fd: Optional[int] = None
        self.master_proc: Optional[asyncio.subprocess.Process] = None
        self.shell_pgid: Optional[int] = None
        self.tty_name: Optional[str] = None
        self.reader_task: Optional[asyncio.Task] = None
        self.current_sentinel: Optional[str] = None
        self.finished = asyncio.Event()
        self.shell_cwd = os.getcwd()

    @property
    def cwd(self) -> str: return self.shell_cwd

    async def _run_control_command(self, cmd: list) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await proc.communicate()
        return out.decode().strip()

    async def start(self):
        if self.master_proc and self.master_proc.returncode is None: return
        if self.reader_task: self.reader_task.cancel()
        m, s = pty.openpty()
        self.tty_name = os.ttyname(s)
        try:
            a = termios.tcgetattr(s); a[3] &= ~termios.ECHO
            termios.tcsetattr(s, termios.TCSANOW, a)
        except: pass
        self.master_fd = m
        env = {**os.environ, "PS1": "", "PS2": "", "PROMPT_COMMAND": "", "TERM": "xterm-256color",
               "COLORTERM": "truecolor", "HISTFILE": HISTORY_FILE, "HISTCONTROL": "ignorespace",
               "HISTSIZE": "10000", "HISTFILESIZE": "20000"}
        self.master_proc = await asyncio.create_subprocess_exec(
            get_shell(), "--noediting", "--norc", "--noprofile",
            stdin=s, stdout=s, stderr=s, preexec_fn=os.setsid, env=env)
        os.close(s)
        h_exp = "set -H" if self.hist_exp else "set +H"
        init_sentinel = f"INIT_{os.urandom(4).hex()}"
        os.write(m, f" stty -echo\n PS1=''; PS2=''; set -m\n {h_exp}\n set -o history\n history -r\n printf '\\x1e{init_sentinel}\\x1f'\n".encode())

        self.shell_pgid = os.getpgid(self.master_proc.pid)
        self.reader_task = asyncio.create_task(self.reader())

        # Wait for initialization sentinel
        self._init_done = asyncio.Event()
        self._init_sentinel = init_sentinel
        try:
            await asyncio.wait_for(self._init_done.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logging.warning(f"[{self.pty_id}] Shell initialization timed out")
        finally:
            self._init_sentinel = None

    async def reader(self):
        self._reader_buf = ""
        loop = asyncio.get_running_loop()
        try:
            while True:
                data = await loop.run_in_executor(None, os.read, self.master_fd, 4096)
                if not data: break
                self._reader_buf += data.decode(errors="replace")

                if getattr(self, "_init_sentinel", None):
                    if f"\x1e{self._init_sentinel}\x1f" in self._reader_buf:
                        parts = self._reader_buf.split(f"\x1e{self._init_sentinel}\x1f", 1)
                        self._reader_buf = parts[1]
                        self._init_done.set()

                if self.current_block_id:
                    # Catch PGID if not yet known
                    if self.current_pgid is None and "PGID:" in self._reader_buf and "\n" in self._reader_buf:
                        match = re.search(r'PGID:(\d+)\n', self._reader_buf)
                        if match:
                            self.current_pgid = int(match.group(1))
                            self._reader_buf = self._reader_buf[match.end():]

                    if self.current_sentinel:
                        while True:
                            match = re.search(rf'\x1e{re.escape(self.current_sentinel)}_(-?\d+)_([^\x1f]*?)\x1f', self._reader_buf)
                            if not match: break
                            out_data = self._reader_buf[:match.start()]
                            if out_data: await self.broadcast({"type":"output","block_id":self.current_block_id,"data":out_data,"pty_uid":self.pty_uid})
                            self.shell_cwd = match.group(2).strip()
                            await self.broadcast({"type":"update_block","block":{"id":self.current_block_id,"status":"ok" if int(match.group(1))==0 else f"error({match.group(1)})","cwd":self.shell_cwd,"pty_uid":self.pty_uid}})
                            self._reader_buf = self._reader_buf[match.end():]
                            self.finished.set()

                        idx = self._reader_buf.find('\x1e')
                        if idx > 0:
                            await self.broadcast({"type":"output","block_id":self.current_block_id,"data":self._reader_buf[:idx],"pty_uid":self.pty_uid})
                            self._reader_buf = self._reader_buf[idx:]
                        elif idx == -1 and self._reader_buf:
                            # Avoid broadcasting partial PGID markers
                            if "PGID:" not in self._reader_buf or "\n" in self._reader_buf:
                                await self.broadcast({"type":"output","block_id":self.current_block_id,"data":self._reader_buf,"pty_uid":self.pty_uid})
                                self._reader_buf = ""
                    else:
                        await self.broadcast({"type":"output","block_id":self.current_block_id,"data":self._reader_buf,"pty_uid":self.pty_uid})
                        self._reader_buf = ""
        except Exception as e:
            logging.error(f"Reader error in {self.pty_id}: {e}")
        finally:
            self.finished.set()

    async def run_command(self, block: dict):
        if not self.master_proc or self.master_proc.returncode is not None: await self.start()
        block_id = block.get("id")
        cmd = block.get("content").strip()
        self.interrupted.clear()
        self.finished.clear()
        self.current_pgid = None
        try:
            h_cmd = cmd.replace('\\', '\\\\').replace("'", "'\\''")
            os.write(self.master_fd, f" history -s $'{h_cmd}'\n".encode())

            sentinel = f"NS_{os.urandom(4).hex()}"
            self.current_sentinel = sentinel

            e_cmd = cmd.replace('\\', '\\\\').replace('\"', '\\\"').replace('$','\\$').replace('`','\\`')
            # Wrapper prints PGID first
            wrapper = f" (printf 'PGID:'; ps -o pgid= -p $$; {e_cmd}); printf '\\x1e{sentinel}_%s_%s\\x1f' \"$?\" \"$(pwd)\"; history -a\n"
            os.write(self.master_fd, wrapper.encode())

            # Shared monitoring loop for both local and remote
            await self._monitor_command(block_id, sentinel)
        finally:
            self.current_sentinel = None
            self.current_pgid = None

    async def _monitor_command(self, block_id: str, sentinel: str):
        # Poll PGID until it returns to shell_pgid OR sentinel is received
        start_time = asyncio.get_running_loop().time()
        while not self.finished.is_set():
            # Check for explicitly captured PGID existence first
            if self.current_pgid:
                out = await self._run_control_command(["ps", "-o", "pgid=", "-g", str(self.current_pgid)])
                if not out:
                    # Process group is gone
                    await asyncio.sleep(0.5)
                    if self.finished.is_set(): break
                    status = "killed" if self.interrupted.is_set() else "done"
                    await self.broadcast({"type": "update_block", "block": {
                        "id": block_id, "status": status, "pty_uid": self.pty_uid, "cwd": self.shell_cwd
                    }})
                    break

            # Fallback/Safety: Check ALL PGIDs on the TTY
            pgid_str = await self._run_control_command(["ps", "-t", self.tty_name, "-o", "pgid="])
            if pgid_str:
                try:
                    pgids = [int(line.strip()) for line in pgid_str.splitlines() if line.strip().isdigit()]
                    is_user_cmd_running = any(pgid != self.shell_pgid for pgid in pgids)

                    if not is_user_cmd_running:
                        # Process group returned to shell, but wait a bit for sentinel
                        if asyncio.get_running_loop().time() - start_time > 1.0:
                             # Give some time for the printf to be read by the reader() task
                             await asyncio.sleep(0.5)
                             if self.finished.is_set(): break
                             # If still not set, command might have been killed or failed before printf
                             status = "killed" if self.interrupted.is_set() else "done"
                             await self.broadcast({"type": "update_block", "block": {
                                 "id": block_id, "status": status, "pty_uid": self.pty_uid, "cwd": self.shell_cwd
                             }})
                             break
                except Exception: pass

            await asyncio.sleep(0.2)

    async def send_input(self, data: str):
        if self.master_fd:
            if data == "\x03" and self.master_proc:
                try:
                    pgid_str = await self._run_control_command(["ps", "-t", self.tty_name, "-o", "pgid="])
                    if pgid_str:
                        pgids = [int(line.strip()) for line in pgid_str.splitlines() if line.strip().isdigit()]
                        for pgid in pgids:
                            if pgid != self.shell_pgid:
                                os.killpg(pgid, signal.SIGINT)
                        return
                except: pass
            os.write(self.master_fd, data.encode())

    async def stop(self):
        self.interrupted.set()
        if not self.master_fd: return
        try:
            pgids = []
            if self.current_pgid:
                pgids = [self.current_pgid]
            else:
                pgid_str = await self._run_control_command(["ps", "-t", self.tty_name, "-o", "pgid="])
                if pgid_str:
                    pgids = [int(line.strip()) for line in pgid_str.splitlines() if line.strip().isdigit()]

            for pgid in pgids:
                if pgid != self.shell_pgid:
                    try: os.killpg(pgid, signal.SIGTERM)
                    except: pass

            await asyncio.sleep(1.0)

            # Final check and kill
            if self.current_pgid:
                try: os.killpg(self.current_pgid, signal.SIGKILL)
                except: pass
            else:
                pgid_str = await self._run_control_command(["ps", "-t", self.tty_name, "-o", "pgid="])
                if pgid_str:
                    pgids = [int(line.strip()) for line in pgid_str.splitlines() if line.strip().isdigit()]
                    for pgid in pgids:
                        if pgid != self.shell_pgid:
                            try: os.killpg(pgid, signal.SIGKILL)
                            except: pass
        except: pass

    async def kill(self):
        await self.stop()
        if self.master_proc: self.master_proc.terminate(); await self.master_proc.wait()
        if self.reader_task: self.reader_task.cancel()
        if self.master_fd: os.close(self.master_fd)
        self.master_proc, self.master_fd = None, None

    def is_running(self) -> bool:
        return self.current_block_id is not None

    async def drain_output(self):
        # Local PTY reader runs in background, so we just clear its buffer
        self._reader_buf = ""

    async def resize(self, r: int, c: int):
        if self.master_fd: fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", r, c, 0, 0))

    async def set_echo(self, e: bool):
        if self.master_fd:
            try:
                a = termios.tcgetattr(self.master_fd); a[3] = a[3] | termios.ECHO if e else a[3] & ~termios.ECHO
                termios.tcsetattr(self.master_fd, termios.TCSANOW, a)
            except: pass
