"""
APScheduler job definitions.

These jobs run inside the FastAPI process on startup and dispatch
Celery tasks at regular intervals. APScheduler is the clock;
Celery workers do the actual work.

Schedule overview:
  ┌─────────────────────────────────┬───────────────┬─────────────────────────────────┐
  │ Job                             │ Interval      │ Celery Task                     │
  ├─────────────────────────────────┼───────────────┼─────────────────────────────────┤
  │ SLA breach detection            │ Every 5 min   │ sla.detect_breaches             │
  │ Auto-escalation of breached     │ Every 10 min  │ sla.auto_escalate               │
  │ SLA warning notifications       │ Every 15 min  │ complaints.check_sla_warnings   │
  │ Closure deadline enforcement    │ Every 30 min  │ closure.enforce_deadlines        │
  │ Closure verification reminders  │ Every 1 hour  │ closure.send_reminders          │
  │ Materialized view refresh       │ Every 6 hours │ (direct SQL)                    │
  │ Anomaly batch scoring           │ Every 6 hours │ anomaly.batch_score_unscored    │
  │ Anomaly model retraining        │ Weekly (Sun)  │ anomaly.retrain_model           │
  └─────────────────────────────────┴───────────────┴─────────────────────────────────┘
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import logging

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


def _dispatch_sla_breach():
    """Dispatch SLA breach detection to Celery."""
    from app.tasks.sla_tasks import detect_sla_breaches
    detect_sla_breaches.delay()
    logger.debug("Dispatched sla.detect_breaches")


def _dispatch_auto_escalate():
    """Dispatch auto-escalation to Celery."""
    from app.tasks.sla_tasks import auto_escalate_breached
    auto_escalate_breached.delay()
    logger.debug("Dispatched sla.auto_escalate")


def _dispatch_sla_warnings():
    """Dispatch SLA warning notifications to Celery."""
    from app.tasks.complaint_tasks import check_sla_warnings
    check_sla_warnings.delay()
    logger.debug("Dispatched complaints.check_sla_warnings")


def _dispatch_closure_deadlines():
    """Dispatch closure deadline enforcement to Celery."""
    from app.tasks.closure_tasks import enforce_closure_deadlines
    enforce_closure_deadlines.delay()
    logger.debug("Dispatched closure.enforce_deadlines")


def _dispatch_closure_reminders():
    """Dispatch closure verification reminders to Celery."""
    from app.tasks.closure_tasks import send_closure_reminders
    send_closure_reminders.delay()
    logger.debug("Dispatched closure.send_reminders")


async def _refresh_materialized_views():
    """
    Refresh materialized views used by analytics dashboards.

    These are:
      - mv_quarterly_complaint_summary
      - mv_sla_compliance
    """
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            from sqlalchemy import text
            await db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_quarterly_complaint_summary"))
            await db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_sla_compliance"))
            await db.commit()
            logger.info("Materialized views refreshed successfully")
        except Exception:
            logger.exception("Error refreshing materialized views")
            await db.rollback()


def _dispatch_anomaly_batch_scoring():
    """Dispatch anomaly batch scan to Celery — catches missed completions."""
    from app.tasks.anomaly_tasks import batch_anomaly_scan
    batch_anomaly_scan.delay(hours=24)
    logger.debug("Dispatched anomaly.batch_scan")


def register_jobs():
    """Register all scheduled jobs. Called once on app startup."""

    # SLA breach detection — every 5 minutes
    scheduler.add_job(
        _dispatch_sla_breach,
        trigger=IntervalTrigger(minutes=5),
        id="sla_breach_detection",
        name="SLA Breach Detection",
        replace_existing=True,
    )

    # Auto-escalation — every 10 minutes (runs after breach detection)
    scheduler.add_job(
        _dispatch_auto_escalate,
        trigger=IntervalTrigger(minutes=10),
        id="sla_auto_escalation",
        name="SLA Auto-Escalation",
        replace_existing=True,
    )

    # SLA warning notifications — every 15 minutes
    scheduler.add_job(
        _dispatch_sla_warnings,
        trigger=IntervalTrigger(minutes=15),
        id="sla_warning_notifications",
        name="SLA Warning Notifications",
        replace_existing=True,
    )

    # Closure deadline enforcement — every 30 minutes
    scheduler.add_job(
        _dispatch_closure_deadlines,
        trigger=IntervalTrigger(minutes=30),
        id="closure_deadline_enforcement",
        name="Closure Deadline Enforcement",
        replace_existing=True,
    )

    # Closure verification reminders — every hour
    scheduler.add_job(
        _dispatch_closure_reminders,
        trigger=IntervalTrigger(hours=1),
        id="closure_verification_reminders",
        name="Closure Verification Reminders",
        replace_existing=True,
    )

    # Materialized view refresh — every 6 hours
    scheduler.add_job(
        _refresh_materialized_views,
        trigger=IntervalTrigger(hours=6),
        id="materialized_view_refresh",
        name="Materialized View Refresh",
        replace_existing=True,
    )

    # Anomaly batch scoring — every 6 hours (scores assignments missed by on-demand pipeline)
    scheduler.add_job(
        _dispatch_anomaly_batch_scoring,
        trigger=IntervalTrigger(hours=6),
        id="anomaly_batch_scoring",
        name="Anomaly Batch Scoring",
        replace_existing=True,
    )

    # Historic Intelligence — daily at 3 AM
    scheduler.add_job(
        _dispatch_historic_intelligence,
        trigger=CronTrigger(hour=3, minute=0),
        id="historic_intelligence",
        name="Historic Intelligence Pattern Analysis",
        replace_existing=True,
    )

    logger.info("Registered %d scheduled jobs", len(scheduler.get_jobs()))

def _dispatch_historic_intelligence():
    """Dispatch historic intelligence processing to Celery."""
    from app.tasks.intelligence_tasks import analyze_historic_patterns
    analyze_historic_patterns.delay()
    logger.debug("Dispatched intelligence.analyze_historic_patterns")
