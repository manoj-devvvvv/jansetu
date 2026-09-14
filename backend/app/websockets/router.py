"""
WebSocket endpoints for real-time notifications.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.websockets.manager import manager
import logging
import asyncio

logger = logging.getLogger(__name__)
router = APIRouter()

@router.websocket("/ws/notifications")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str = Query(...),
    role: str = Query(...)  # 'worker', 'officer', 'citizen'
):
    """
    Unified WebSocket endpoint for notifications.
    Clients connect here with their user_id and role to receive real-time pushes.
    In a real production environment, auth tokens should be sent and verified here.
    """
    is_officer = (role == 'officer')
    await manager.connect(websocket, user_id, is_officer=is_officer)
    
    try:
        while True:
            # We don't expect much input from clients, this is primarily for pushing.
            # But we must yield control so the connection stays open and can receive text.
            data = await websocket.receive_text()
            
            # Simple ping/pong for keepalive if needed
            if data == "ping":
                await websocket.send_text("pong")
                
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id, is_officer=is_officer)
    except Exception:
        manager.disconnect(websocket, user_id, is_officer=is_officer)
