"""
Notification background tasks.

Logs notifications to the notification_log table and pushes real-time
events via the WebSocket connection manager.
"""

from app.tasks.celery_app import celery_app
from app.db.sync_session import get_sync_db
from sqlalchemy import text
import json
import logging

logger = logging.getLogger(__name__)


@celery_app.task(name="notifications.send", bind=True, max_retries=3)
def send_notification(
    self,
    notification_type: str,
    related_complaint_id: str | None = None,
    related_worker_assignment_id: str | None = None,
    payload: dict | None = None,
    target_worker_id: str | None = None,
    target_citizen_id: str | None = None,
):
    """
    Core notification dispatch task.

    1. Log the notification to notification_log table
    2. Publish to Redis pub/sub so WebSocket servers can push in real-time

    notification_type must be one of:
        'assignment', 'sla_reminder', 'citizen_verification_reminder',
        'escalation', 'general'
    """
    db = get_sync_db()
    try:
        payload = payload or {}

        # ── 1. Log to notification_log ───────────────────────────────────
        db.execute(
            text("""
                INSERT INTO notification_log
                    (notification_type, related_complaint_id,
                     related_worker_assignment_id, payload)
                VALUES
                    (:ntype,
                     CASE WHEN :cid = '' THEN NULL ELSE :cid::uuid END,
                     CASE WHEN :waid = '' THEN NULL ELSE :waid::uuid END,
                     :payload::jsonb)
            """),
            {
                "ntype": notification_type,
                "cid": related_complaint_id or "",
                "waid": related_worker_assignment_id or "",
                "payload": json.dumps(payload),
            },
        )
        db.commit()

        # ── 2. Publish to Redis pub/sub for WebSocket delivery ───────────
        _publish_to_redis(
            notification_type=notification_type,
            related_complaint_id=related_complaint_id,
            related_worker_assignment_id=related_worker_assignment_id,
            payload=payload,
            target_worker_id=target_worker_id,
            target_citizen_id=target_citizen_id,
        )

        logger.info(
            "Notification sent: type=%s complaint=%s assignment=%s",
            notification_type,
            related_complaint_id,
            related_worker_assignment_id,
        )
        return {"status": "sent", "type": notification_type}

    except Exception as exc:
        db.rollback()
        logger.exception("Error sending notification")
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()


def _publish_to_redis(
    notification_type: str,
    related_complaint_id: str | None,
    related_worker_assignment_id: str | None,
    payload: dict,
    target_worker_id: str | None,
    target_citizen_id: str | None,
):
    """
    Publish notification event to Redis pub/sub channels.

    Channel naming:
      - worker:{worker_id}   — targeted worker notifications
      - citizen:{citizen_id}  — targeted citizen notifications
      - broadcast:officers    — broadcast to all officers (escalations, etc.)
    """
    import redis as sync_redis
    from app.config.settings import settings

    r = sync_redis.from_url(settings.REDIS_URL)

    message = json.dumps({
        "type": notification_type,
        "complaint_id": related_complaint_id,
        "worker_assignment_id": related_worker_assignment_id,
        "payload": payload,
    })

    try:
        if target_worker_id:
            r.publish(f"ws:worker:{target_worker_id}", message)

        if target_citizen_id:
            r.publish(f"ws:citizen:{target_citizen_id}", message)

        # Escalation and SLA notifications go to officer broadcast
        if notification_type in ("escalation", "sla_reminder"):
            r.publish("ws:broadcast:officers", message)
    finally:
        r.close()


@celery_app.task(name="notifications.assignment_created")
def notify_assignment_created(worker_id: str, complaint_id: str, assignment_id: str):
    """Convenience task: notify a worker they have a new assignment."""
    send_notification.delay(
        notification_type="assignment",
        related_complaint_id=complaint_id,
        related_worker_assignment_id=assignment_id,
        payload={"message": "You have a new assignment", "action": "view_assignment"},
        target_worker_id=worker_id,
    )


@celery_app.task(name="notifications.sla_warning")
def notify_sla_warning(worker_id: str, complaint_id: str, assignment_id: str, hours_remaining: int):
    """Convenience task: warn a worker their SLA deadline is approaching."""
    send_notification.delay(
        notification_type="sla_reminder",
        related_complaint_id=complaint_id,
        related_worker_assignment_id=assignment_id,
        payload={
            "message": f"SLA deadline approaching — {hours_remaining}h remaining",
            "action": "view_assignment",
        },
        target_worker_id=worker_id,
    )


@celery_app.task(name="notifications.escalation_alert")
def notify_escalation(complaint_id: str, from_level: str, to_level: str, reason: str):
    """Convenience task: alert officers about an escalation."""
    send_notification.delay(
        notification_type="escalation",
        related_complaint_id=complaint_id,
        payload={
            "message": f"Complaint escalated from {from_level} to {to_level}",
            "reason": reason,
            "action": "view_complaint",
        },
    )
