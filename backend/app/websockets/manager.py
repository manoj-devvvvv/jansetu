"""
WebSocket Connection Manager.

Tracks active WebSocket connections and handles broadcasting messages.
"""

from fastapi import WebSocket
from typing import Dict, Set
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Maps user_id -> set of active WebSockets (allows multiple devices)
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        
        # Maps broadcast_group -> set of active WebSockets
        self.broadcast_groups: Dict[str, Set[WebSocket]] = {
            "officers": set(),
        }

    async def connect(self, websocket: WebSocket, user_id: str, is_officer: bool = False):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
        
        if is_officer:
            self.broadcast_groups["officers"].add(websocket)
            
        logger.debug(f"Client {user_id} connected. Total devices: {len(self.active_connections[user_id])}")

    def disconnect(self, websocket: WebSocket, user_id: str, is_officer: bool = False):
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
                
        if is_officer:
            self.broadcast_groups["officers"].discard(websocket)

    async def send_personal_message(self, message: str, user_id: str):
        if user_id in self.active_connections:
            disconnected = set()
            for ws in self.active_connections[user_id]:
                try:
                    await ws.send_text(message)
                except Exception:
                    disconnected.add(ws)
            
            # Cleanup any broken connections
            for ws in disconnected:
                self.disconnect(ws, user_id)

    async def broadcast_to_group(self, message: str, group: str):
        if group in self.broadcast_groups:
            disconnected = set()
            for ws in self.broadcast_groups[group]:
                try:
                    await ws.send_text(message)
                except Exception:
                    disconnected.add(ws)
                    
            for ws in disconnected:
                self.broadcast_groups[group].discard(ws)

manager = ConnectionManager()
