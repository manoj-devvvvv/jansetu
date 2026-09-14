import redis.asyncio as redis
from fastapi import Request, HTTPException, status
from .settings import settings

# Initialize Redis client
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

async def check_rate_limit(key: str, max_requests: int, window_seconds: int):
    """
    Core rate limiting logic using Redis INCR and EXPIRE (Fixed Window Counter).
    """
    try:
        current_count = await redis_client.incr(key)
        if current_count == 1:
            await redis_client.expire(key, window_seconds)
        
        if current_count > max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later."
            )
    except redis.RedisError as e:
        # If Redis fails, fail open (allow request) to prevent blocking users during cache downtime
        # In a strict production environment, this might be logged and handled differently
        pass

async def complaint_rate_limit(request: Request):
    """
    FastAPI dependency to limit complaint submissions to 2 per day per IP.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    key = f"rate_limit:complaint:{client_ip}"
    # 2 requests per 86400 seconds (1 day)
    await check_rate_limit(key, max_requests=2, window_seconds=86400)

async def login_rate_limit(request: Request):
    """
    FastAPI dependency to limit login attempts to 5 per 15 minutes per IP.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    key = f"rate_limit:login:{client_ip}"
    # 5 requests per 900 seconds (15 minutes)
    await check_rate_limit(key, max_requests=5, window_seconds=900)
