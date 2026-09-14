"""
Complaint-related background tasks.

1. check_sla_warnings — sends reminder notifications when SLA is approaching deadline
"""

from app.tasks.celery_app import celery_app
from app.db.sync_session import get_sync_db
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


@celery_app.task(name="complaints.check_sla_warnings", bind=True, max_retries=3)
def check_sla_warnings(self):
    """
    Find worker_assignment SLA trackers approaching their deadline (within 6 hours)
    and send proactive warning notifications to the assigned worker.

    Only sends one warning per tracker (checks breach_processed_at is null
    as a proxy — once breached, the breach task handles it).
    """
    db = get_sync_db()
    try:
        rows = db.execute(
            text("""
                SELECT st.id, st.worker_assignment_id,
                       wa.worker_id, wa.complaint_id,
                       EXTRACT(EPOCH FROM (st.due_at - now())) / 3600 AS hours_remaining
                FROM sla_trackers st
                JOIN worker_assignments wa ON wa.id = st.worker_assignment_id
                WHERE st.tracker_type = 'worker_assignment'
                  AND st.breached = false
                  AND st.resolved_at IS NULL
                  AND st.due_at > now()
                  AND st.due_at < now() + interval '6 hours'
                  AND st.breach_processed_at IS NULL
                  AND wa.status IN ('assigned', 'accepted', 'in_progress')
            """)
        ).fetchall()

        if not rows:
            logger.info("No SLA warnings to send")
            return {"warnings_sent": 0}

        from app.tasks.notification_tasks import notify_sla_warning

        sent = 0
        for r in rows:
            hours = max(1, int(r.hours_remaining))
            notify_sla_warning.delay(
                worker_id=str(r.worker_id),
                complaint_id=str(r.complaint_id),
                assignment_id=str(r.worker_assignment_id),
                hours_remaining=hours,
            )
            sent += 1

        logger.info("Sent %d SLA warning notifications", sent)
        return {"warnings_sent": sent}

    except Exception as exc:
        logger.exception("Error in check_sla_warnings")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@celery_app.task(name="complaints.process_clustering", bind=True, max_retries=3)
def process_complaint_clustering(self, complaint_id: str):
    """
    Triggered on every new complaint submission.

    Runs the full clustering pipeline:
      1. Generate text embedding (fastembed + BGE-M3)
      2. Store embedding in complaint_embeddings
      3. Find or create a MasterIssue cluster
      4. Evaluate fast-tracking based on severity + member count
      5. Send notifications to officers if fast-tracked
    """
    db = get_sync_db()
    try:
        from app.core.clustering.master_issue import process_new_complaint
        result = process_new_complaint(db, complaint_id)
        logger.info(
            "Clustering complete for complaint %s: action=%s, master_issue=%s, fast_tracked=%s",
            complaint_id,
            result.get("cluster_action"),
            result.get("master_issue_id"),
            result.get("fast_tracked"),
        )
        return result
    except Exception as exc:
        db.rollback()
        logger.exception("Error in process_complaint_clustering for %s", complaint_id)
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()
