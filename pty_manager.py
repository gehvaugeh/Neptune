import asyncio
import logging
from typing import Dict, List, Optional, Callable, Awaitable, Set
from pty_base import BasePTY
from pty_local import LocalPTY
from pty_remote import RemotePTY

class PTYManager:
    def __init__(self, broadcast_func: Callable[[dict], Awaitable[None]], enable_hist_expansion: bool = False):
        self.ptys: Dict[int, BasePTY] = {} # Keyed by UID
        self.names: Dict[int, str] = {}
        self._tasks: Dict[int, asyncio.Task] = {}
        self.broadcast = broadcast_func
        self.enable_hist_expansion = enable_hist_expansion
        self.running_blocks: Set[str] = set()
        self.uid_counter = 0
        self.terminal_size = (24, 80)

    async def create_local(self, name: Optional[str] = None) -> LocalPTY:
        uid = self.uid_counter
        self.uid_counter += 1

        if name is None:
            name = f"local-{uid}"

        pty_id = name # Use name as pty_id for internal BasePTY compatibility if needed, but we rely on UID
        pty = LocalPTY(uid, pty_id, self.broadcast, self.enable_hist_expansion)
        await pty.start()
        await pty.resize(*self.terminal_size)

        self.ptys[uid] = pty
        self.names[uid] = name
        self._tasks[uid] = asyncio.create_task(self._queue_worker(uid, pty))

        await self.broadcast({
            "type": "pty.created",
            "uid": uid,
            "name": name,
            "pty_type": "local"
        })
        return pty

    async def create_remote(self, ssh_config: dict, name: Optional[str] = None) -> RemotePTY:
        uid = self.uid_counter
        self.uid_counter += 1

        if name is None:
            host = ssh_config.get("host", "remote")
            name = f"{host}-{uid}"

        pty_id = name
        pty = RemotePTY(uid, pty_id, self.broadcast)
        await pty.connect(ssh_config)
        await pty.resize(*self.terminal_size)

        self.ptys[uid] = pty
        self.names[uid] = name
        self._tasks[uid] = asyncio.create_task(self._queue_worker(uid, pty))

        await self.broadcast({
            "type": "pty.created",
            "uid": uid,
            "name": name,
            "pty_type": "remote"
        })
        return pty

    async def _queue_worker(self, uid: int, pty: BasePTY):
        logging.info(f"[UID:{uid}] Queue worker started")
        try:
            while True:
                block = await pty.queue.get()
                if block.get("id") in self.running_blocks:
                    logging.warning(f"[UID:{uid}] Block {block.get('id')} already running, skipping")
                    pty.queue.task_done()
                    continue

                self.running_blocks.add(block.get("id"))
                pty.current_block_id = block.get("id")
                try:
                    await pty.drain_output()
                    # Mark block as running and clear output
                    await self.broadcast({
                        "type": "update_block",
                        "block": {"id": block.get("id"), "status": "running", "pty_uid": uid, "pty_name": self.names.get(uid), "output": ""}
                    })
                    await self.broadcast_queues_status()
                    await pty.run_command(block)
                finally:
                    pty.current_block_id = None
                    self.running_blocks.remove(block.get("id"))
                    pty.queue.task_done()
                    await self.broadcast_queues_status()
        except asyncio.CancelledError:
            logging.info(f"[UID:{uid}] Queue worker cancelled")
        except Exception as e:
            logging.error(f"[UID:{uid}] Queue worker error: {e}")

    async def stop_pty(self, uid: int):
        if uid in self.ptys:
            await self.ptys[uid].stop()

    async def destroy(self, uid: int):
        if uid not in self.ptys:
            return
        if uid == 0:
            logging.warning("Cannot destroy UID 0")
            return

        logging.info(f"Destroying PTY UID {uid}")
        pty = self.ptys.pop(uid)
        self.names.pop(uid, None)
        task = self._tasks.pop(uid)
        task.cancel()

        # Signal associated blocks
        # We need to tell the server to update all blocks that were tied to this PTY
        # but we don't have direct access to the Server's blocks list here.
        # We'll broadcast a general PTY destroyed message, and the server/clients
        # should handle updating their block metadata.

        if pty.current_block_id:
             await self.broadcast({
                 "type": "update_block",
                 "block": {"id": pty.current_block_id, "status": "killed", "pty_uid": None}
             })

        await pty.kill()
        await self.broadcast({"type": "pty.destroyed", "uid": uid})

    def rename_pty(self, uid: int, new_name: str):
        if uid in self.names:
            self.names[uid] = new_name
            # Also update the pty_id in the pty instance if it's used for display
            if uid in self.ptys:
                self.ptys[uid].pty_id = new_name
            return True
        return False

    def list_ptys(self) -> List[dict]:
        return [
            {
                "uid": uid,
                "name": self.names.get(uid, f"pty-{uid}"),
                "type": "local" if isinstance(pty, LocalPTY) else "remote",
                "status": "running" if pty.current_block_id else "idle",
                "block_count": pty.queue.qsize()
            }
            for uid, pty in self.ptys.items()
        ]

    async def update_all_block_statuses(self):
        for uid, pty in self.ptys.items():
            # Copy items from queue to see their order safely without awaiting
            temp_list = []
            while True:
                try:
                    temp_list.append(pty.queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # Put them back and broadcast status
            for i, block in enumerate(temp_list):
                pty.queue.put_nowait(block)
                await self.broadcast({
                    "type": "update_block",
                    "block": {"id": block.get("id"), "status": f"queued({i+1})", "pty_uid": uid, "pty_name": self.names.get(uid)}
                })

    async def broadcast_queues_status(self):
        await self.update_all_block_statuses()
        queues_data = []
        for uid, pty in self.ptys.items():
            queues_data.append({
                "uid": uid,
                "name": self.names.get(uid),
                "block_count": pty.queue.qsize(),
                "status": "running" if pty.current_block_id else "idle",
                "active_block_id": pty.current_block_id
            })

        msg = {
            "type": "queue_status",
            "queues": queues_data
        }
        await self.broadcast(msg)
