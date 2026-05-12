import asyncio, os, pty, termios, struct, fcntl, signal, re, logging
from typing import Optional, Callable, Awaitable
from pty_base import BasePTY
from common import HISTORY_FILE, get_shell

TUI_CMDS = {"vim", "vi", "nano", "htop", "top", "less", "more", "man", "tmux", "neptune"}

class LocalPTY(BasePTY):
    def __init__(self, pty_id: str, broadcast: Callable[[dict], Awaitable[None]], hist_exp: bool = False):
        super().__init__(pty_id)
        self.broadcast, self.hist_exp = broadcast, hist_exp
        self.master_fd: Optional[int] = None
        self.master_proc: Optional[asyncio.subprocess.Process] = None
        self.master_pgid: Optional[int] = None
        self.reader_task: Optional[asyncio.Task] = None
        self.current_sentinel: Optional[str] = None
        self.finished = asyncio.Event()
        self.shell_cwd = os.getcwd()

    @property
    def cwd(self) -> str: return self.shell_cwd

    async def start(self):
        if self.master_proc and self.master_proc.returncode is None: return
        if self.reader_task: self.reader_task.cancel()
        m, s = pty.openpty()
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
        os.write(m, f" stty -echo\n set -m\n {h_exp}\n set -o history\n history -r\n".encode())
        await asyncio.sleep(0.1)
        self.master_pgid = os.getpgid(self.master_proc.pid)
        self.reader_task = asyncio.create_task(self.reader())

    async def reader(self):
        buf, loop = "", asyncio.get_running_loop()
        try:
            while True:
                data = await loop.run_in_executor(None, os.read, self.master_fd, 4096)
                if not data: break
                buf += data.decode(errors="replace")
                if self.current_block_id:
                    if self.current_sentinel:
                        while True:
                            match = re.search(rf'\x1e{re.escape(self.current_sentinel)}_(-?\d+)_([^\x1f]*?)\x1f', buf)
                            if not match: break
                            if buf[:match.start()]: await self.broadcast({"type":"output","block_id":self.current_block_id,"data":buf[:match.start()],"pty_id":self.pty_id})
                            self.shell_cwd = match.group(2).strip()
                            await self.broadcast({"type":"update_block","block":{"id":self.current_block_id,"status":"ok" if int(match.group(1))==0 else f"error({match.group(1)})","cwd":self.shell_cwd,"pty_id":self.pty_id}})
                            buf, _ = buf[match.end():], self.finished.set()
                        idx = buf.find('\x1e')
                        if idx > 0: await self.broadcast({"type":"output","block_id":self.current_block_id,"data":buf[:idx],"pty_id":self.pty_id}); buf = buf[idx:]
                        elif idx == -1 and buf: await self.broadcast({"type":"output","block_id":self.current_block_id,"data":buf,"pty_id":self.pty_id}); buf = ""
                    else: await self.broadcast({"type":"output","block_id":self.current_block_id,"data":buf,"pty_id":self.pty_id}); buf = ""
        except: pass
        finally: self.finished.set()

    async def run_command(self, block: dict):
        if not self.master_proc or self.master_proc.returncode is not None: await self.start()
        self.current_block_id, cmd = block.get("id"), block.get("content").strip()
        self.finished.clear()
        is_tui = cmd.split()[0] in TUI_CMDS if cmd.split() else False
        try:
            h_cmd = cmd.replace('\\', '\\\\').replace("'", "'\\''")
            os.write(self.master_fd, f" history -s $'{h_cmd}'\n".encode())
            if is_tui:
                self.mode, self.current_sentinel = "interactive", None
                os.write(self.master_fd, f" {cmd}\n".encode())
                start_time = asyncio.get_running_loop().time()
                while asyncio.get_running_loop().time() - start_time < 0.5:
                    try:
                        if os.tcgetpgrp(self.master_fd) != self.master_pgid: break
                    except: pass
                    await asyncio.sleep(0.05)
                while self.is_running(): await asyncio.sleep(0.1)
                await self.broadcast({"type":"update_block","block":{"id":self.current_block_id,"status":"ok","pty_id":self.pty_id}})
            else:
                self.mode, self.current_sentinel = "sentinel", f"NS_{os.urandom(4).hex()}"
                e_cmd = cmd.replace('\\', '\\\\').replace('\"', '\\\"').replace('$','\\$').replace('`','\\`')
                os.write(self.master_fd, f" eval \"{e_cmd}\"; printf '\\x1e{self.current_sentinel}_%s_%s\\x1f' \"$?\" \"$(pwd)\"; history -a\n".encode())
                start_time = asyncio.get_running_loop().time()
                while asyncio.get_running_loop().time() - start_time < 0.5:
                    try:
                        if os.tcgetpgrp(self.master_fd) != self.master_pgid: break
                    except: pass
                    await asyncio.sleep(0.05)
                await self.finished.wait()
        finally: self.current_block_id, self.current_sentinel, self.mode = None, None, "sentinel"

    async def send_input(self, data: str):
        if self.master_fd:
            if data == "\x03" and self.master_proc:
                try:
                    fg = os.tcgetpgrp(self.master_fd)
                    os.killpg(fg if fg > 0 and fg != self.master_pgid else os.getpgid(self.master_proc.pid), signal.SIGINT)
                except: pass
            os.write(self.master_fd, data.encode())

    async def stop(self):
        if not self.master_fd: return
        try:
            fg = os.tcgetpgrp(self.master_fd)
            if fg > 0 and fg != self.master_pgid:
                os.killpg(fg, signal.SIGTERM); await asyncio.sleep(0.5)
                if os.tcgetpgrp(self.master_fd) != self.master_pgid: os.killpg(fg, signal.SIGKILL)
        except: pass

    async def kill(self):
        await self.stop()
        if self.master_proc: self.master_proc.terminate(); await self.master_proc.wait()
        if self.reader_task: self.reader_task.cancel()
        if self.master_fd: os.close(self.master_fd)
        self.master_proc, self.master_fd = None, None

    def is_running(self) -> bool:
        if not self.master_fd or not self.master_pgid: return False
        try:
            fg = os.tcgetpgrp(self.master_fd)
            return fg > 0 and fg != self.master_pgid
        except: return False

    async def resize(self, r: int, c: int):
        if self.master_fd: fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", r, c, 0, 0))

    async def set_echo(self, e: bool):
        if self.master_fd:
            try:
                a = termios.tcgetattr(self.master_fd); a[3] = a[3] | termios.ECHO if e else a[3] & ~termios.ECHO
                termios.tcsetattr(self.master_fd, termios.TCSANOW, a)
            except: pass
