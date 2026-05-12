import asyncio
import json
import logging
from typing import Dict, Any

class SessionManager:
    def __init__(self):
        self.clients: Dict[Any, Dict[str, Any]] = {} # writer: {id, color, name}

    async def broadcast(self, message: dict):
        data = json.dumps(message).encode() + b"\n"
        logging.debug(f"Broadcasting: {message.get('type')}")

        clients = list(self.clients.items())
        for writer, client_info in clients:
            asyncio.create_task(self.send_to_client(writer, data, client_info.get('id')))

    async def send_to_client(self, writer: asyncio.StreamWriter, data: bytes, user_id: str):
        try:
            if not writer.is_closing():
                writer.write(data)
                await asyncio.wait_for(writer.drain(), timeout=2.0)
        except Exception as e:
            logging.error(f"Removing unresponsive client {user_id}: {e}")
            if writer in self.clients:
                del self.clients[writer]
            try:
                writer.close()
                await writer.wait_closed()
            except: pass
