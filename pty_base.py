import asyncio
from abc import ABC, abstractmethod
from typing import Literal, Optional

class BasePTY(ABC):
    def __init__(self, pty_uid: int, pty_id: str):
        self.pty_uid = pty_uid
        self.pty_id = pty_id
        self.shadow_lock = asyncio.Lock()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.mode: Literal["sentinel", "interactive"] = "sentinel"
        self.current_block_id: Optional[str] = None
        self.current_pgid: Optional[int] = None
        self.interrupted = asyncio.Event()

    @property
    @abstractmethod
    def cwd(self) -> str:
        pass

    @abstractmethod
    async def run_command(self, block: dict) -> None:
        pass

    @abstractmethod
    async def send_input(self, data: str) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Terminate the current foreground process group."""
        pass

    @abstractmethod
    async def kill(self) -> None:
        """Destroy the PTY and all associated processes."""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        pass

    @abstractmethod
    async def drain_output(self) -> None:
        """Clear pending output from the PTY."""
        pass

    @abstractmethod
    async def resize(self, rows: int, cols: int) -> None:
        pass

    @abstractmethod
    async def sync_shadow_state(self, cmd: str) -> None:
        """Propagate state-changing commands to the shadow shell."""
        pass

    @abstractmethod
    async def get_completions(self, query: str) -> list[str]:
        """Query the shadow shell for completions using compgen."""
        pass
