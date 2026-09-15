"""
Intelligence tasks for processing historical data and finding recurring patterns.
"""
from app.tasks.celery_app import celery_app
from app.db.sync_session import get_sync_db
import logging

logger = logging.getLogger(__name__)

@celery_app.task(name="intelligence.analyze_historic_patterns", bind=True, max_retries=2)
def analyze_historic_patterns(self):
    """
    Periodic task to analyze historic master issues and identify
    seasonal patterns and short-term recurring failures.
    """
    db = get_sync_db()
    try:
        from app.core.intelligence import run_full_intelligence_pipeline
        run_full_intelligence_pipeline(db)
        logger.info("Historic Intelligence pattern analysis completed successfully.")
        return {"status": "success"}
    except Exception as exc:
        db.rollback()
        logger.exception("Error during Historic Intelligence analysis")
        raise self.retry(exc=exc, countdown=300)
    finally:
        db.close()
