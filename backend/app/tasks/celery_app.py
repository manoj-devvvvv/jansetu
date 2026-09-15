"""
Celery application configuration for JanSetu background tasks.

Uses Redis as both broker and result backend.
"""

from celery import Celery
from app.config.settings import settings

celery_app = Celery(
    "jansetu",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Discover tasks in these modules
    imports=[
        "app.tasks.sla_tasks",
        "app.tasks.notification_tasks",
        "app.tasks.closure_tasks",
        "app.tasks.complaint_tasks",
        "app.tasks.anomaly_tasks",
        "app.tasks.intelligence_tasks",
    ],
)
