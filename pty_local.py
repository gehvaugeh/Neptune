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

        # Inject hooks
        # preexec: DEBUG trap. Ignore printf to avoid loops.
        # precmd: PROMPT_COMMAND.
        hook_init = (
            f" stty -echo\n"
            f" PS1=''; PS2=''; set -m\n"
            f" {h_exp}\n"
            f" set -o history\n"
            f" history -r\n"
            f" trap '[[ \"$BASH_COMMAND\" != \"printf\"* ]] && printf \"\\\\x1eB_%s\\\\x1f\" \"$BASH_COMMAND\"' DEBUG\n"
            f" export PROMPT_COMMAND='printf \"\\\\x1eE_%s_%s\\\\x1f\" \"$?\" \"$PWD\"'\n"
            f" printf '\\x1e{init_sentinel}\\x1f'\n"
        )
        os.write(m, hook_init.encode())

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
                    # Handle Hooks: \x1eB_... \x1f and \x1eE_... \x1f
                    while True:
                        # Find any hook sentinel
                        m_hook = re.search(r'\x1e([BE])_(.*?)\x1f', self._reader_buf)
                        if not m_hook: break

                        pre_data = self._reader_buf[:m_hook.start()]
                        if pre_data:
                            await self.broadcast({"type":"output","block_id":self.current_block_id,"data":pre_data,"pty_uid":self.pty_uid})

                        hook_type = m_hook.group(1)
                        hook_data = m_hook.group(2)

                        if hook_type == 'B':
                            # Command started
                            pass
                        elif hook_type == 'E':
                            # Command ended: E_EXITCODE_CWD
                            parts = hook_data.split('_', 1)
                            exit_code = parts[0]
                            self.shell_cwd = parts[1] if len(parts) > 1 else self.shell_cwd
                            status = "ok" if exit_code == "0" else f"error({exit_code})"
                            await self.broadcast({"type":"update_block","block":{"id":self.current_block_id,"status":status,"cwd":self.shell_cwd,"pty_uid":self.pty_uid}})
                            self.finished.set()

                        self._reader_buf = self._reader_buf[m_hook.end():]

                    # Broadcast remaining output, avoiding partial sentinels
                    split_idx = self._reader_buf.find('\x1e')
                    if split_idx != -1:
                        if split_idx > 0:
                            await self.broadcast({"type":"output","block_id":self.current_block_id,"data":self._reader_buf[:split_idx],"pty_uid":self.pty_uid})
                            self._reader_buf = self._reader_buf[split_idx:]
                        if len(self._reader_buf) > 512: # Safety flush
                            await self.broadcast({"type":"output","block_id":self.current_block_id,"data":self._reader_buf,"pty_uid":self.pty_uid})
                            self._reader_buf = ""
                    elif self._reader_buf:
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
        try:
            h_cmd = cmd.replace('\\', '\\\\').replace("'", "'\\''")
            os.write(self.master_fd, f" history -s $'{h_cmd}'\n".encode())

            # Simple direct write. The hooks will handle the rest.
            os.write(self.master_fd, f" {cmd}\n".encode())

            # Monitor via hooks (finished Event is set in reader)
            await self._monitor_command(block_id)
        finally:
            pass

    async def _monitor_command(self, block_id: str):
        # Wait for the finished event, which is set in the reader() when E_ sentinel is found
        try:
            await self.finished.wait()
        except asyncio.CancelledError:
            pass

    async def send_input(self, data: str):
        if self.master_fd:
            # For Ctrl+C (\x03), we rely on the TTY to generate SIGINT for the foreground process group.
            # We write it directly to the master FD.
            os.write(self.master_fd, data.encode())

    async def stop(self):
        self.interrupted.set()
        if not self.master_fd: return

        # Capture context to avoid race
        target_block_id = self.current_block_id
        target_pgid = self.current_pgid

        try:
            pgids = []
            if target_pgid:
                pgids = [target_pgid]
            else:
                pgid_str = await self._run_control_command(["ps", "-t", self.tty_name, "-o", "pgid="])
                if pgid_str:
                    pgids = [int(line.strip()) for line in pgid_str.splitlines() if line.strip().isdigit()]

            for pgid in pgids:
                if pgid != self.shell_pgid:
                    try: os.killpg(pgid, signal.SIGTERM)
                    except: pass

            await asyncio.sleep(1.0)

            # Double check if we are still supposed to be stopping the same block
            if self.current_block_id != target_block_id and target_block_id is not None:
                 logging.info(f"[{self.pty_id}] Termination race detected. Next command already started. Aborting SIGKILL.")
                 return

            # Final check and kill
            if target_pgid:
                try: os.killpg(target_pgid, signal.SIGKILL)
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
