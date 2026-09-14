"""
Redis Pub/Sub listener for WebSockets.

Subscribes to Redis channels and forwards messages to connected WebSockets.
"""

import asyncio
import logging
import redis.asyncio as redis
from app.config.settings import settings
from app.websockets.manager import manager

logger = logging.getLogger(__name__)

async def redis_listener():
    """
    Background task that listens to Redis pub/sub and routes
    messages to the appropriate WebSocket clients.
    """
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()
    
    try:
        # Subscribe to patterns for all targeted and broadcast channels
        await pubsub.psubscribe("ws:worker:*")
        await pubsub.psubscribe("ws:citizen:*")
        await pubsub.psubscribe("ws:broadcast:*")
        
        logger.info("Started Redis pub/sub listener for WebSockets")
        
        async for message in pubsub.listen():
            if message["type"] == "pmessage":
                channel = message["channel"]
                data = message["data"]
                
                parts = channel.split(":")
                if len(parts) >= 3:
                    prefix = parts[1] # 'worker', 'citizen', or 'broadcast'
                    target = parts[2] # user_id or group_name
                    
                    if prefix == "broadcast":
                        await manager.broadcast_to_group(data, target)
                    else:
                        # For worker or citizen, target is the user_id
                        await manager.send_personal_message(data, target)
                        
    except asyncio.CancelledError:
        logger.info("Redis pub/sub listener cancelled")
    except Exception:
        logger.exception("Error in Redis pub/sub listener")
    finally:
        await pubsub.close()
        await redis_client.aclose()
