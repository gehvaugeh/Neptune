import asyncio
import logging
from typing import Dict, List, Optional, Callable, Awaitable, Set
from pty_base import BasePTY
from pty_local import LocalPTY
from pty_remote import RemotePTY

class PTYManager:
    def __init__(self, broadcast_func: Callable[[dict], Awaitable[None]], enable_hist_expansion: bool = False):
        self.ptys: Dict[str, BasePTY] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self.default_pty_id: str = "local-1"
        self.broadcast = broadcast_func
        self.enable_hist_expansion = enable_hist_expansion
        self.running_blocks: Set[str] = set()

    async def create_local(self, pty_id: str) -> LocalPTY:
        if pty_id in self.ptys:
            return self.ptys[pty_id]

        pty = LocalPTY(pty_id, self.broadcast, self.enable_hist_expansion)
        await pty.start()
        self.ptys[pty_id] = pty
        self._tasks[pty_id] = asyncio.create_task(self._queue_worker(pty))

        await self.broadcast({
            "type": "pty.created",
            "pty_id": pty_id,
            "pty_type": "local",
            "default": pty_id == self.default_pty_id
        })
        return pty

    async def create_remote(self, pty_id: str, ssh_config: dict) -> RemotePTY:
        if pty_id in self.ptys:
            return self.ptys[pty_id]

        pty = RemotePTY(pty_id, self.broadcast)
        await pty.connect(ssh_config)
        self.ptys[pty_id] = pty
        self._tasks[pty_id] = asyncio.create_task(self._queue_worker(pty))

        await self.broadcast({
            "type": "pty.created",
            "pty_id": pty_id,
            "pty_type": "remote",
            "default": pty_id == self.default_pty_id
        })
        return pty

    async def _queue_worker(self, pty: BasePTY):
        logging.info(f"[{pty.pty_id}] Queue worker started")
        try:
            while True:
                block = await pty.queue.get()
                if block["id"] in self.running_blocks:
                    logging.warning(f"[{pty.pty_id}] Block {block['id']} already running, skipping")
                    pty.queue.task_done()
                    continue

                self.running_blocks.add(block["id"])
                try:
                    await self.broadcast_queues_status()
                    await pty.run_command(block)
                finally:
                    self.running_blocks.remove(block["id"])
                    pty.queue.task_done()
                    await self.broadcast_queues_status()
        except asyncio.CancelledError:
            logging.info(f"[{pty.pty_id}] Queue worker cancelled")
        except Exception as e:
            logging.error(f"[{pty.pty_id}] Queue worker error: {e}")

    async def destroy(self, pty_id: str):
        if pty_id not in self.ptys:
            return

        logging.info(f"Destroying PTY {pty_id}")
        pty = self.ptys.pop(pty_id)
        task = self._tasks.pop(pty_id)
        task.cancel()
        await pty.kill()

        await self.broadcast({"type": "pty.destroyed", "pty_id": pty_id})

    def set_default(self, pty_id: str):
        if pty_id in self.ptys:
            self.default_pty_id = pty_id
            return True
        return False

    def list_ptys(self) -> List[dict]:
        return [
            {
                "pty_id": p_id,
                "type": "local" if isinstance(pty, LocalPTY) else "remote",
                "status": "running" if pty.is_running() else "idle",
                "block_count": pty.queue.qsize(),
                "default": p_id == self.default_pty_id
            }
            for p_id, pty in self.ptys.items()
        ]

    async def broadcast_queues_status(self):
        queues_data = []
        default_pty = self.ptys.get(self.default_pty_id)

        for p_id, pty in self.ptys.items():
            queues_data.append({
                "pty_id": p_id,
                "block_count": pty.queue.qsize(),
                "status": "running" if pty.is_running() else "idle",
                "active_block_id": pty.current_block_id
            })

        msg = {
            "type": "queue_status",
            "queues": queues_data
        }

        if default_pty:
            msg["block_count"] = default_pty.queue.qsize()
            msg["status"] = "running" if default_pty.is_running() else "idle"
            msg["active_block_id"] = default_pty.current_block_id
            msg["pty_id"] = self.default_pty_id

        await self.broadcast(msg)
