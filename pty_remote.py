import asyncio, os, logging, shutil, time, re, shlex
from typing import Optional, Callable, Awaitable, List, Dict
from pty_base import BasePTY

TUI_COMMANDS = {"vim", "vi", "nano", "htop", "top", "less", "more", "man", "tmux", "neptune"}

class RemotePTY(BasePTY):
    def __init__(self, pty_uid: int, pty_id: str, broadcast_func: Callable[[dict], Awaitable[None]]):
        super().__init__(pty_uid, pty_id)
        self.broadcast, self.ssh_config = broadcast_func, {}
        self.master_proc: Optional[asyncio.subprocess.Process] = None
        self.shell_proc: Optional[asyncio.subprocess.Process] = None
        self.shadow_proc: Optional[asyncio.subprocess.Process] = None
        self.socket_path = os.path.abspath(f"neptune-{self.pty_uid}.sock")
        self.remote_tty: Optional[str] = None
        self.shell_pgid: Optional[int] = None
        self._cwd = ""

    @property
    def cwd(self) -> str: return self._cwd

    def _get_ssh_base(self, use_socket: bool = True) -> List[str]:
        host, user = self.ssh_config.get("host"), self.ssh_config.get("user")
        key, password = self.ssh_config.get("key"), self.ssh_config.get("password")
        port = self.ssh_config.get("port")
        cmd = []
        if password and password != "x" * len(password):
            cmd.extend(["sshpass", "-p", password])
        cmd.append("ssh")
        if use_socket: cmd.extend(["-S", self.socket_path])
        if key: cmd.extend(["-i", key])
        if port: cmd.extend(["-p", str(port)])
        cmd.extend(["-o", "BatchMode=no", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"])
        cmd.append(f"{user}@{host}" if user else host)
        return cmd

    async def connect(self, ssh_config: dict):
        self.ssh_config = ssh_config.copy()
        password = self.ssh_config.get("password")
        if password and not shutil.which("sshpass"):
            msg = "sshpass not installed. Password auth is insecure; please install sshpass or preferably use SSH keys for better security."
            await self.broadcast({"type": "pty.error", "pty_uid": self.pty_uid, "error": "sshpass_missing", "message": msg})

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
            await self.broadcast({"type": "pty.error", "pty_uid": self.pty_uid, "error": "connection_failed", "message": str(e)})
            raise

        # Step 2: Open persistent shell and shadow shell
        s_cmd = self._get_ssh_base(use_socket=True)
        s_cmd.extend(["-tt", "bash"])
        self.shell_proc = await asyncio.create_subprocess_exec(
            *s_cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )

        shadow_cmd = self._get_ssh_base(use_socket=True)
        shadow_cmd.extend(["bash"])
        self.shadow_proc = await asyncio.create_subprocess_exec(
            *shadow_cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )

        # Step 3, 4, 5: Get TTY, PGID, CWD and set prompt
        init_sentinel = f"INIT_{os.urandom(4).hex()}"
        neptunerc = "~/.neptunerc"
        init_rc = f"[[ -f {neptunerc} ]] && source {neptunerc}\n"

        init_script = (
            f"stty -echo opost onlcr\n"
            f"export TERM=xterm-256color\n"
            f"export PS1=''; export PS2=''\n"
            f"{init_rc}"
            f"tty\n"
            f"ps -o pgid= -p $$\n"
            f"pwd\n"
            f"echo '{init_sentinel}'\n"
        )
        # Also initialize shadow shell
        # Set stty -echo to prevent command echoing in shadow shell
        self.shadow_proc.stdin.write(f" stty -echo\n {init_rc}".encode())
        await self.shadow_proc.stdin.drain()
        self.shell_proc.stdin.write(init_script.encode())
        await self.shell_proc.stdin.drain()

        start = time.time()
        init_done = False
        while time.time() - start < 10.0:
            try:
                line = (await asyncio.wait_for(self.shell_proc.stdout.readline(), 1.0)).decode(errors="replace").strip()
                if not line: continue
                if init_sentinel in line:
                    init_done = True
                    break
                if "/dev/" in line and not self.remote_tty: self.remote_tty = line
                elif line.isdigit() and not self.shell_pgid: self.shell_pgid = int(line)
                elif line.startswith("/") and not self._cwd: self._cwd = line
            except asyncio.TimeoutError: continue
            except Exception: break

        if not init_done:
            logging.warning(f"[{self.pty_id}] Remote initialization signal not received")

        if password: self.ssh_config["password"] = "x" * len(password)
        if "password" in self.ssh_config: del self.ssh_config["password"]

    async def run_command(self, block: dict):
        block_id = block.get("id")
        cmd = block.get("content").strip()
        self.interrupted.clear()
        self.current_pgid = None

        # Inject into shadow shell if state-changing
        await self.sync_shadow_state(cmd)

        sentinel = f"NS_{os.urandom(4).hex()}"
        # Run command directly to preserve state
        wrapper = f" {cmd}; printf '\\x1e{sentinel}_%s_%s\\x1f' \"$?\" \"$(pwd)\"\n"

        self.shell_proc.stdin.write(wrapper.encode())
        await self.shell_proc.stdin.drain()
        await self._monitor_command(block_id, sentinel)

    def _is_state_changing(self, cmd: str) -> bool:
        cmd = cmd.strip()
        # Heuristic for state-changing commands
        patterns = [r'^cd\s+', r'^export\s+', r'^\w+=', r'^unset\s+', r'^alias\s+', r'^source\s+', r'^\.\s+']
        return any(re.search(p, cmd) for p in patterns)

    async def sync_shadow_state(self, cmd: str):
        if self.shadow_proc and self.shadow_proc.stdin and self._is_state_changing(cmd):
            async with self.shadow_lock:
                self.shadow_proc.stdin.write(f" {cmd}\n".encode())
                await self.shadow_proc.stdin.drain()

    async def get_completions(self, query: str) -> list[str]:
        if not self.shadow_proc or not self.shadow_proc.stdin: return []

        async with self.shadow_lock:
            # Drain any stray output
            while True:
                try:
                    data = await asyncio.wait_for(self.shadow_proc.stdout.read(4096), timeout=0.01)
                    if not data: break
                except:
                    break

            sentinel = f"COMP_{os.urandom(4).hex()}"

            # Robust tokenization: find the last token
            parts = re.findall(r'(?:[^\s"\']|"(?:\\.|[^"])*"|\'(?:\\.|[^\'])*\')+', query)
            token = parts[-1] if parts and not query.endswith(" ") else ""
            q_token = shlex.quote(token)

            if " " in query.strip():
                comp_cmd = f"compgen -f -- {q_token}; echo {sentinel}\n"
            else:
                comp_cmd = f"compgen -c -- {q_token}; compgen -f -- {q_token}; echo {sentinel}\n"

            self.shadow_proc.stdin.write(comp_cmd.encode())
            await self.shadow_proc.stdin.drain()

            results = []
            try:
                while True:
                    line = await asyncio.wait_for(self.shadow_proc.stdout.readline(), timeout=2.0)
                    if not line: break
                    line = line.decode().strip()
                    if line == sentinel: break
                    if line: results.append(line)
            except asyncio.TimeoutError:
                logging.warning(f"[{self.pty_id}] Autocomplete timeout (remote) after reading {len(results)} items")
            except Exception as e:
                logging.error(f"[{self.pty_id}] ShadowShell remote read error: {e}")

            return sorted(list(set(results)))

    async def _monitor_command(self, block_id: str, sentinel: str):
        buf = ""
        start_time = asyncio.get_running_loop().time()
        last_poll_time = 0.0
        poll_interval = 0.5 # More frequent polling for better responsiveness

        try:
            while True:
                # 1. Prioritize reading output
                try:
                    chunk = await asyncio.wait_for(self.shell_proc.stdout.read(4096), 0.1)
                    if not chunk: break
                    buf += chunk.decode(errors="replace")
                except asyncio.TimeoutError:
                    pass

                now = asyncio.get_running_loop().time()
                if now - last_poll_time >= poll_interval:
                    last_poll_time = now
                    # Check ALL PGIDs on the TTY to see if user command is running
                    cmd = self._get_ssh_base(use_socket=True)
                    cmd.append(f"ps -t {self.remote_tty} -o pgid=")
                    try:
                        p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                        out, _ = await p.communicate()
                        pgids = [int(line.strip()) for line in out.decode().splitlines() if line.strip().isdigit()]
                        is_user_cmd_running = any(pgid != self.shell_pgid for pgid in pgids)

                        if not is_user_cmd_running:
                            # Command finished or killed, give a moment for sentinel to arrive
                            await asyncio.sleep(0.5)
                            # One last read attempt
                            try:
                                chunk = await asyncio.wait_for(self.shell_proc.stdout.read(4096), 0.1)
                                if chunk: buf += chunk.decode(errors="replace")
                            except: pass
                            break
                    except: pass

                try:
                    # 2. Identify and handle ANY sentinel (\x1eNS_... \x1f)
                    while True:
                        sent_match = re.search(r'\x1eNS_[0-9a-fA-F]+_(-?\d+)_([^\x1f]*?)\x1f', buf)
                        if not sent_match: break

                        # Data before sentinel is real output
                        pre_data = buf[:sent_match.start()]
                        if pre_data:
                            await self.broadcast({"type": "output", "block_id": block_id, "data": pre_data, "pty_uid": self.pty_uid})

                        # Is this OUR sentinel?
                        if f"\x1e{sentinel}_" in sent_match.group(0):
                            exit_code = int(sent_match.group(1))
                            self._cwd = sent_match.group(2).strip()
                            await self.broadcast({"type": "update_block", "block": {
                                "id": block_id, "status": "ok" if exit_code == 0 else f"error({exit_code})", "pty_uid": self.pty_uid, "cwd": self._cwd
                            }})
                            return # Done
                        else:
                            # Stale sentinel from previous command, just discard it
                            logging.debug(f"[{self.pty_id}] Discarded stale sentinel: {sent_match.group(0)}")

                        buf = buf[sent_match.end():]

                    # 3. Broadcast remaining output, but stay clear of potential partial sentinel
                    split_idx = buf.find('\x1e')

                    if split_idx != -1:
                        if split_idx > 0:
                            await self.broadcast({"type": "output", "block_id": block_id, "data": buf[:split_idx], "pty_uid": self.pty_uid})
                            buf = buf[split_idx:]

                        # If it's not a sentinel prefix or it's too long, broadcast it
                        if not buf.startswith('\x1eNS_') or len(buf) > 256:
                            await self.broadcast({"type": "output", "block_id": block_id, "data": buf, "pty_uid": self.pty_uid})
                            buf = ""
                    elif buf:
                        await self.broadcast({"type": "output", "block_id": block_id, "data": buf, "pty_uid": self.pty_uid})
                        buf = ""
                except asyncio.TimeoutError:
                    continue

            # If loop exited via PGID check, broadcast remaining data and final status
            # But process one last time for sentinel to avoid leakage
            while True:
                sent_match = re.search(r'\x1eNS_[0-9a-fA-F]+_(-?\d+)_([^\x1f]*?)\x1f', buf)
                if not sent_match: break
                pre_data = buf[:sent_match.start()]
                if pre_data:
                    await self.broadcast({"type": "output", "block_id": block_id, "data": pre_data, "pty_uid": self.pty_uid})

                if f"\x1e{sentinel}_" in sent_match.group(0):
                    exit_code = int(sent_match.group(1))
                    self._cwd = sent_match.group(2).strip()
                    await self.broadcast({"type": "update_block", "block": {
                        "id": block_id, "status": "ok" if exit_code == 0 else f"error({exit_code})", "pty_uid": self.pty_uid, "cwd": self._cwd
                    }})
                    return
                buf = buf[sent_match.end():]

            if buf:
                await self.broadcast({"type": "output", "block_id": block_id, "data": buf, "pty_uid": self.pty_uid})

            status = "killed" if self.interrupted.is_set() else "done"
            await self.broadcast({"type": "update_block", "block": {
                "id": block_id, "status": status, "pty_uid": self.pty_uid, "cwd": self._cwd
            }})
        finally:
            self.current_pgid = None

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
        return self.current_block_id is not None

    async def send_input(self, data: str):
        if self.shell_proc and self.shell_proc.stdin:
            if data == "\x03":
                 # Explicitly send SIGINT to the remote foreground process group for better reliability
                 cmd = self._get_ssh_base(use_socket=True)
                 cmd.append(f"kill -INT -$(ps -o pgid= -p $(ps -o pid= -t {self.remote_tty} | tail -1))")
                 try: await (await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)).wait()
                 except: pass

            self.shell_proc.stdin.write(data.encode())
            await self.shell_proc.stdin.drain()

    async def stop(self):
        self.interrupted.set()

        # Capture context to avoid race with next command
        target_block_id = self.current_block_id
        target_pgid = self.current_pgid

        pgids = []
        if target_pgid:
            pgids = [target_pgid]
        else:
            # Identify all PGIDs on the TTY
            cmd = self._get_ssh_base(use_socket=True)
            cmd.append(f"ps -t {self.remote_tty} -o pgid=")
            try:
                p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE)
                out, _ = await p.communicate()
                pgids = [int(line.strip()) for line in out.decode().splitlines() if line.strip().isdigit()]
            except: pass

        targets = [pgid for pgid in pgids if pgid != self.shell_pgid]
        if not targets: return

        try:
            for pgid in targets:
                k1 = self._get_ssh_base(use_socket=True); k1.append(f"kill -TERM -{pgid}")
                await (await asyncio.create_subprocess_exec(*k1)).wait()

            await asyncio.sleep(1.0)

            # Double check if we are still supposed to be stopping the same block
            if self.current_block_id != target_block_id and target_block_id is not None:
                logging.info(f"[{self.pty_id}] Termination race detected. Next command already started. Aborting SIGKILL.")
                return

            # Check if target still exists
            if target_pgid:
                targets = [target_pgid]
            else:
                cmd = self._get_ssh_base(use_socket=True)
                cmd.append(f"ps -t {self.remote_tty} -o pgid=")
                p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE)
                out, _ = await p.communicate()
                pgids = [int(line.strip()) for line in out.decode().splitlines() if line.strip().isdigit()]
                targets = [pgid for pgid in pgids if pgid != self.shell_pgid]

            for pgid in targets:
                k2 = self._get_ssh_base(use_socket=True); k2.append(f"kill -KILL -{pgid}")
                await (await asyncio.create_subprocess_exec(*k2)).wait()
        except Exception as e:
            logging.error(f"Error in RemotePTY.stop for {self.pty_id}: {e}")

    async def kill(self):
        try:
            # Tell ControlMaster to exit
            e_cmd = self._get_ssh_base(use_socket=True)
            target = e_cmd.pop()
            e_cmd.extend(["-O", "exit", target])
            await (await asyncio.create_subprocess_exec(*e_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)).wait()
        except: pass
        for p in [self.master_proc, self.shell_proc, self.shadow_proc]:
            if p:
                try: p.terminate()
                except: pass
        if os.path.exists(self.socket_path):
            try: os.remove(self.socket_path)
            except: pass

    async def drain_output(self):
        # Read from shell_proc until it would block, with a slight persistence
        for _ in range(5):
            while True:
                try:
                    chunk = await asyncio.wait_for(self.shell_proc.stdout.read(4096), 0.1)
                    if not chunk: break
                except: break
            await asyncio.sleep(0.05)

    async def resize(self, r: int, c: int):
        await self.send_input(f"stty rows {r} cols {c}\n")
