import asyncio
from abc import ABC, abstractmethod
from typing import Literal, Optional

class BasePTY(ABC):
    def __init__(self, pty_id: str):
        self.pty_id = pty_id
        self.queue: asyncio.Queue = asyncio.Queue()
        self.mode: Literal["sentinel", "interactive"] = "sentinel"
        self.current_block_id: Optional[str] = None

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
        pass

    @abstractmethod
    async def kill(self) -> None:
        pass

    @abstractmethod
    def is_running(self) -> bool:
        pass

    @abstractmethod
    async def resize(self, rows: int, cols: int) -> None:
        pass
