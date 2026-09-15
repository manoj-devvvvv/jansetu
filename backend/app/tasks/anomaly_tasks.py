"""
Anomaly detection background tasks.

Celery tasks that trigger anomaly detection for completed worker assignments.
"""

from app.tasks.celery_app import celery_app
from app.db.sync_session import get_sync_db
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


@celery_app.task(name="anomaly.process_completion", bind=True, max_retries=3)
def process_anomaly_detection(
    self,
    worker_id: str,
    assignment_id: str,
):
    """
    Triggered when a worker completes an assignment.

    Runs the full anomaly detection pipeline:
      1. Extract features (travel speed, duration, photo hash)
      2. Compute anomaly score (XGBoost or heuristic)
      3. Detect and persist anomaly flags
      4. Apply worker score penalties
      5. Notify officers if anomalies found
    """
    db = get_sync_db()
    try:
        from app.core.anomaly_detection.model import run_anomaly_pipeline

        result = run_anomaly_pipeline(db, worker_id, assignment_id)

        logger.info(
            "Anomaly detection complete for assignment %s: score=%.3f, flags=%d",
            assignment_id,
            result.get("anomaly_score", 0.0),
            len(result.get("flags", [])),
        )
        return result
    except Exception as exc:
        db.rollback()
        logger.exception(
            "Error in anomaly detection for assignment %s", assignment_id
        )
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@celery_app.task(name="anomaly.batch_scan", bind=True, max_retries=2)
def batch_anomaly_scan(self, hours: int = 24):
    """
    Periodic task: scan recently completed assignments that haven't
    been analyzed yet (catch-up for any missed Celery tasks).
    """
    db = get_sync_db()
    try:
        from app.core.anomaly_detection.model import batch_scan_recent_completions

        result = batch_scan_recent_completions(db, hours=hours)
        logger.info(
            "Batch anomaly scan: scanned=%d, flagged=%d",
            result.get("scanned", 0),
            result.get("flagged", 0),
        )
        return result
    except Exception as exc:
        db.rollback()
        logger.exception("Error in batch anomaly scan")
        raise self.retry(exc=exc, countdown=120)
    finally:
        db.close()
