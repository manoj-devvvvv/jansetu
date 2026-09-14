import time
import base64
import hmac
import hashlib
import json
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import uuid as _uuid

from app.config.settings import settings
from app.db.session import get_db
from app.models.worker import Worker


def b64url_encode(data: bytes) -> str:
    """Base64 URL encode without padding."""
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def b64url_decode(b64_str: str) -> bytes:
    """Base64 URL decode with padding."""
    padding = "=" * (4 - (len(b64_str) % 4))
    return base64.urlsafe_b64decode(b64_str + padding)


def create_worker_token(worker_id: str, exp_hours: int = 24) -> str:
    """Creates a simple HMAC-SHA256 JWT for workers since they don't use Supabase Auth."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(worker_id),
        "exp": int(time.time()) + (exp_hours * 3600),
        "iat": int(time.time()),
    }

    header_enc = b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_enc = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    msg = f"{header_enc}.{payload_enc}".encode("utf-8")
    signature = hmac.new(settings.JWT_SECRET.encode("utf-8"), msg, hashlib.sha256).digest()
    sig_enc = b64url_encode(signature)

    return f"{header_enc}.{payload_enc}.{sig_enc}"


def verify_worker_token(token: str) -> str:
    """Verifies the HMAC-SHA256 JWT and returns the worker_id."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format")

    header_enc, payload_enc, sig_enc = parts
    msg = f"{header_enc}.{payload_enc}".encode("utf-8")
    signature = hmac.new(settings.JWT_SECRET.encode("utf-8"), msg, hashlib.sha256).digest()
    expected_sig = b64url_encode(signature)

    if not hmac.compare_digest(sig_enc, expected_sig):
        raise ValueError("Invalid signature")

    payload = json.loads(b64url_decode(payload_enc).decode("utf-8"))
    if payload.get("exp", 0) < time.time():
        raise ValueError("Token expired")

    return payload["sub"]


security = HTTPBearer()

async def get_current_worker(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Worker:
    """FastAPI dependency to authenticate workers via custom JWT."""
    token = credentials.credentials
    try:
        worker_id_str = verify_worker_token(token)
        worker_uuid = _uuid.UUID(worker_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    result = await db.execute(select(Worker).where(Worker.id == worker_uuid))
    worker = result.scalar_one_or_none()

    if not worker:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker not found"
        )
    if not worker.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Worker account is inactive"
        )

    return worker
