import asyncio, os, logging, shutil, time, re
from typing import Optional, Callable, Awaitable, List, Dict
from pty_base import BasePTY

TUI_COMMANDS = {"vim", "vi", "nano", "htop", "top", "less", "more", "man", "tmux", "neptune"}

class RemotePTY(BasePTY):
    def __init__(self, pty_id: str, broadcast_func: Callable[[dict], Awaitable[None]]):
        super().__init__(pty_id)
        self.broadcast, self.ssh_config = broadcast_func, {}
        self.master_proc: Optional[asyncio.subprocess.Process] = None
        self.shell_proc: Optional[asyncio.subprocess.Process] = None
        self.socket_path = os.path.abspath(f"neptune-{self.pty_id}.sock")
        self.remote_tty: Optional[str] = None
        self.shell_pgid: Optional[int] = None
        self._cwd = ""

    @property
    def cwd(self) -> str: return self._cwd

    def _get_ssh_base(self, use_socket: bool = True) -> List[str]:
        host, user = self.ssh_config.get("host"), self.ssh_config.get("user")
        key, password = self.ssh_config.get("key"), self.ssh_config.get("password")
        cmd = []
        if password and password != "x" * len(password):
            cmd.extend(["sshpass", "-p", password])
        cmd.append("ssh")
        if use_socket: cmd.extend(["-S", self.socket_path])
        if key: cmd.extend(["-i", key])
        cmd.extend(["-o", "BatchMode=no", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"])
        cmd.append(f"{user}@{host}" if user else host)
        return cmd

    async def connect(self, ssh_config: dict):
        self.ssh_config = ssh_config.copy()
        password = self.ssh_config.get("password")
        if password and not shutil.which("sshpass"):
            msg = "sshpass not installed. Password auth is insecure; please install sshpass or preferably use SSH keys for better security."
            await self.broadcast({"type": "pty.error", "pty_id": self.pty_id, "error": "sshpass_missing", "message": msg})

        # Step 1: Open ControlMaster socket
        m_cmd = self._get_ssh_base(use_socket=False)
        target = m_cmd.pop()
        m_cmd.extend(["-M", "-N", "-S", self.socket_path, target])
        try:
            self.master_proc = await asyncio.create_subprocess_exec(*m_cmd)
            for _ in range(50):
                if os.path.exists(self.socket_path): break
                await asyncio.sleep(0.2)
            else: raise Exception("ControlMaster socket failed to initialize")
        except Exception as e:
            await self.broadcast({"type": "pty.error", "pty_id": self.pty_id, "error": "connection_failed", "message": str(e)})
            raise

        # Step 2: Open persistent shell
        s_cmd = self._get_ssh_base(use_socket=True)
        s_cmd.extend(["-tt", "bash"])
        self.shell_proc = await asyncio.create_subprocess_exec(
            *s_cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )

        # Step 3, 4, 5: Get TTY, PGID, CWD and set prompt
        await asyncio.sleep(0.5)
        self.shell_proc.stdin.write(b"stty -echo\ntty\necho $$\npwd\nexport PS1='NEPTUNE> '\n")
        await self.shell_proc.stdin.drain()

        start = time.time()
        while (not (self.remote_tty and self.shell_pgid and self._cwd)) and (time.time() - start < 5.0):
            try:
                line = (await asyncio.wait_for(self.shell_proc.stdout.readline(), 1.0)).decode(errors="replace").strip()
                if not line or "NEPTUNE>" in line: continue
                if "/dev/" in line and not self.remote_tty: self.remote_tty = line
                elif line.isdigit() and not self.shell_pgid: self.shell_pgid = int(line)
                elif line.startswith("/") and not self._cwd: self._cwd = line
            except asyncio.TimeoutError: break
            except Exception: break

        if password: self.ssh_config["password"] = "x" * len(password)
        if "password" in self.ssh_config: del self.ssh_config["password"]

    async def run_command(self, block: dict):
        self.current_block_id = block["id"]
        cmd = block["content"].strip()
        self.shell_proc.stdin.write(f"{cmd}\n".encode())
        await self.shell_proc.stdin.drain()
        await self._monitor_command(block["id"])

    async def _monitor_command(self, block_id: str):
        try:
            await asyncio.sleep(0.2)
            while await self.is_running():
                try:
                    chunk = await asyncio.wait_for(self.shell_proc.stdout.read(4096), 0.1)
                    if chunk:
                        await self.broadcast({
                            "type": "output", "block_id": block_id,
                            "data": chunk.decode(errors="replace"), "pty_id": self.pty_id
                        })
                except asyncio.TimeoutError: pass
                await asyncio.sleep(0.1)

            # Drain remaining output
            for _ in range(10):
                try:
                    chunk = await asyncio.wait_for(self.shell_proc.stdout.read(4096), 0.05)
                    if not chunk: break
                    await self.broadcast({
                        "type": "output", "block_id": block_id,
                        "data": chunk.decode(errors="replace"), "pty_id": self.pty_id
                    })
                except: break

            # Update CWD after command
            await self._update_cwd()

            await self.broadcast({"type": "update_block", "block": {
                "id": block_id, "status": "done", "pty_id": self.pty_id, "cwd": self._cwd
            }})
        finally:
            self.current_block_id = None

    async def _update_cwd(self):
        cmd = self._get_ssh_base(use_socket=True)
        cmd.append(f"pwdx {self.shell_pgid} | cut -d' ' -f2-")
        try:
            p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await p.communicate()
            res = out.decode().strip()
            if res and res.startswith("/"): self._cwd = res
        except: pass

    async def is_running(self) -> bool:
        if not os.path.exists(self.socket_path):
            await self.broadcast({"type": "pty.error", "pty_id": self.pty_id, "error": "connection_lost", "message": "ControlMaster socket missing"})
            return False
        cmd = self._get_ssh_base(use_socket=True)
        cmd.append(f"ps -t {self.remote_tty} -o pgid= | head -1")
        try:
            p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await p.communicate()
            res = out.decode().strip()
            return int(res) != self.shell_pgid if res else False
        except: return False

    async def is_tui_running(self) -> bool:
        if not os.path.exists(self.socket_path): return False
        cmd = self._get_ssh_base(use_socket=True)
        cmd.append(f"ps -t {self.remote_tty} -o pgid=,comm= | head -1")
        try:
            p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await p.communicate()
            parts = out.decode().strip().split()
            return parts[1] in TUI_COMMANDS if len(parts) >= 2 else False
        except: return False

    async def send_input(self, data: str):
        if self.shell_proc and self.shell_proc.stdin:
            self.shell_proc.stdin.write(data.encode())
            await self.shell_proc.stdin.drain()

    async def stop(self):
        cmd = self._get_ssh_base(use_socket=True)
        cmd.append(f"ps -t {self.remote_tty} -o pgid= | head -1")
        try:
            p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE)
            out, _ = await p.communicate()
            pgid = out.decode().strip()
            if not pgid or int(pgid) == self.shell_pgid: return

            k1 = self._get_ssh_base(use_socket=True); k1.append(f"kill -TERM -{pgid}")
            await (await asyncio.create_subprocess_exec(*k1)).wait()
            await asyncio.sleep(2)
            if await self.is_running():
                k2 = self._get_ssh_base(use_socket=True); k2.append(f"kill -KILL -{pgid}")
                await (await asyncio.create_subprocess_exec(*k2)).wait()
        except: pass

    async def kill(self):
        try:
            # Tell ControlMaster to exit
            e_cmd = self._get_ssh_base(use_socket=True)
            target = e_cmd.pop()
            e_cmd.extend(["-O", "exit", target])
            await (await asyncio.create_subprocess_exec(*e_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)).wait()
        except: pass
        for p in [self.master_proc, self.shell_proc]:
            if p:
                try: p.terminate()
                except: pass
        if os.path.exists(self.socket_path):
            try: os.remove(self.socket_path)
            except: pass

    async def resize(self, r: int, c: int):
        await self.send_input(f"stty rows {r} cols {c}\n")
