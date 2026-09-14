"""
Closure verification background tasks.

1. enforce_closure_deadlines — auto-closes complaints when citizen doesn't respond within 24h
2. send_closure_reminders    — sends reminders for pending closure verifications
"""

from app.tasks.celery_app import celery_app
from app.db.sync_session import get_sync_db
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


@celery_app.task(name="closure.enforce_deadlines", bind=True, max_retries=3)
def enforce_closure_deadlines(self):
    """
    Auto-close complaints where the citizen verification deadline has passed.

    When a worker completes an assignment, a closure_verification row is created
    with verification_due_at = now() + 24h. If the citizen doesn't confirm or
    reject within that window, we auto-close.

    Logic:
      - Find closure_verifications where verification_due_at < now()
        AND citizen_confirmed = false AND reopened = false
      - Set citizen_confirmed = true, citizen_confirmed_at = now()
      - Update parent complaint status to 'closed', closed_at = now()
      - Resolve any remaining SLA trackers for the complaint
    """
    db = get_sync_db()
    try:
        expired_rows = db.execute(
            text("""
                SELECT cv.id, cv.complaint_id, cv.worker_assignment_id
                FROM closure_verifications cv
                WHERE cv.verification_due_at < now()
                  AND cv.citizen_confirmed = false
                  AND cv.reopened = false
            """)
        ).fetchall()

        if not expired_rows:
            logger.info("No expired closure deadlines found")
            return {"auto_closed_count": 0}

        auto_closed = 0

        for row in expired_rows:
            cv_id = str(row.id)
            complaint_id = str(row.complaint_id)

            # Auto-confirm the closure
            db.execute(
                text("""
                    UPDATE closure_verifications
                    SET citizen_confirmed = true,
                        citizen_confirmed_at = now()
                    WHERE id = :cvid::uuid
                """),
                {"cvid": cv_id},
            )

            # Close the complaint
            db.execute(
                text("""
                    UPDATE complaints
                    SET status = 'closed',
                        closed_at = now(),
                        resolved_at = COALESCE(resolved_at, now()),
                        updated_at = now()
                    WHERE id = :cid::uuid
                      AND status = 'pending_citizen_confirmation'
                """),
                {"cid": complaint_id},
            )

            # Log the status change
            db.execute(
                text("""
                    INSERT INTO complaint_status_history
                        (complaint_id, old_status, new_status)
                    VALUES
                        (:cid::uuid, 'pending_citizen_confirmation', 'closed')
                """),
                {"cid": complaint_id},
            )

            # Resolve any open SLA trackers for this complaint
            db.execute(
                text("""
                    UPDATE sla_trackers
                    SET resolved_at = now()
                    WHERE complaint_id = :cid::uuid
                      AND resolved_at IS NULL
                """),
                {"cid": complaint_id},
            )

            auto_closed += 1

        db.commit()
        logger.info("Auto-closed %d complaints due to expired citizen verification", auto_closed)
        return {"auto_closed_count": auto_closed}

    except Exception as exc:
        db.rollback()
        logger.exception("Error in enforce_closure_deadlines")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@celery_app.task(name="closure.send_reminders", bind=True, max_retries=3)
def send_closure_reminders(self):
    """
    Send reminders for pending closure verifications that haven't been acted on.

    - Only sends to closures where verification_due_at is still in the future
    - Only sends if reminder_count < 2 (max 2 reminders)
    - Records each reminder in citizen_verification_reminders table
    """
    db = get_sync_db()
    try:
        pending = db.execute(
            text("""
                SELECT cv.id, cv.complaint_id, cv.reminder_count,
                       c.citizen_id
                FROM closure_verifications cv
                JOIN complaints c ON c.id = cv.complaint_id
                WHERE cv.citizen_confirmed = false
                  AND cv.reopened = false
                  AND cv.verification_due_at > now()
                  AND cv.reminder_count < 2
                  AND (cv.last_reminder_sent_at IS NULL
                       OR cv.last_reminder_sent_at < now() - interval '4 hours')
            """)
        ).fetchall()

        if not pending:
            logger.info("No closure reminders to send")
            return {"reminders_sent": 0}

        sent = 0

        for row in pending:
            cv_id = str(row.id)

            # Log the reminder
            db.execute(
                text("""
                    INSERT INTO citizen_verification_reminders
                        (closure_verification_id)
                    VALUES (:cvid::uuid)
                """),
                {"cvid": cv_id},
            )

            # Update reminder count and timestamp
            db.execute(
                text("""
                    UPDATE closure_verifications
                    SET reminder_count = reminder_count + 1,
                        last_reminder_sent_at = now()
                    WHERE id = :cvid::uuid
                """),
                {"cvid": cv_id},
            )

            # Queue a WebSocket notification (fire-and-forget)
            from app.tasks.notification_tasks import send_notification
            send_notification.delay(
                notification_type="citizen_verification_reminder",
                related_complaint_id=str(row.complaint_id),
                payload={
                    "message": "Please confirm whether your complaint has been resolved.",
                    "closure_verification_id": cv_id,
                },
            )

            sent += 1

        db.commit()
        logger.info("Sent %d closure verification reminders", sent)
        return {"reminders_sent": sent}

    except Exception as exc:
        db.rollback()
        logger.exception("Error in send_closure_reminders")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
