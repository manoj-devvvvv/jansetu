"""
Synchronous database session factory for Celery tasks.

Celery workers run in a sync context, so we need a standard (non-async)
SQLAlchemy session. This avoids spinning up an asyncio event loop inside
each Celery task.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Convert the async postgres URL to sync
# asyncpg:// → psycopg2:// (or just postgresql://)
_async_url = os.environ.get("SUPABASE_DB_URL", "")
_sync_url = _async_url.replace("postgresql+asyncpg://", "postgresql://")

sync_engine = create_engine(_sync_url, echo=False, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(bind=sync_engine, class_=Session, expire_on_commit=False)


def get_sync_db() -> Session:
    """Returns a sync session for use in Celery tasks. Caller must close it."""
    return SyncSessionLocal()
