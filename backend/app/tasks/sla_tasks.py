"""
SLA background tasks.

1. detect_sla_breaches  — marks overdue SLA trackers as breached and penalizes worker scores
2. auto_escalate_breached — escalates complaints stuck at a review level after SLA breach
"""

from app.tasks.celery_app import celery_app
from app.db.sync_session import get_sync_db
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


@celery_app.task(name="sla.detect_breaches", bind=True, max_retries=3)
def detect_sla_breaches(self):
    """
    Scan for SLA trackers that are past due_at but not yet marked breached.

    For worker_assignment type:
      - Set breached = true, breach_processed_at = now()
      - Penalize the worker's profile_score by -10
      - Log the score change in worker_score_history

    For verification types (panchayat/mandal/district):
      - Set breached = true, breach_processed_at = now()
      - (Auto-escalation is handled by a separate task)
    """
    db = get_sync_db()
    try:
        # ── 1. Find unbreached, unresolved, overdue trackers ─────────────
        rows = db.execute(
            text("""
                SELECT id, tracker_type, worker_assignment_id, complaint_id
                FROM sla_trackers
                WHERE breached = false
                  AND resolved_at IS NULL
                  AND due_at < now()
            """)
        ).fetchall()

        if not rows:
            logger.info("No SLA breaches detected")
            return {"breached_count": 0}

        breached_ids = [str(r.id) for r in rows]

        # ── 2. Mark them all breached in a single UPDATE ─────────────────
        db.execute(
            text("""
                UPDATE sla_trackers
                SET breached = true,
                    breach_processed_at = now()
                WHERE id = ANY(:ids::uuid[])
            """),
            {"ids": breached_ids},
        )

        # ── 3. Penalize workers for worker_assignment breaches ───────────
        worker_assignment_ids = [
            str(r.worker_assignment_id) for r in rows
            if r.tracker_type == "worker_assignment" and r.worker_assignment_id
        ]

        if worker_assignment_ids:
            # Get worker IDs from assignments
            assignment_rows = db.execute(
                text("""
                    SELECT id, worker_id
                    FROM worker_assignments
                    WHERE id = ANY(:ids::uuid[])
                """),
                {"ids": worker_assignment_ids},
            ).fetchall()

            for ar in assignment_rows:
                worker_id = str(ar.worker_id)
                assignment_id = str(ar.id)

                # Deduct score (clamped to 0 minimum by DB check constraint)
                db.execute(
                    text("""
                        UPDATE workers
                        SET profile_score = GREATEST(0, profile_score - 10),
                            updated_at = now()
                        WHERE id = :wid::uuid
                    """),
                    {"wid": worker_id},
                )

                # Log score change
                db.execute(
                    text("""
                        INSERT INTO worker_score_history
                            (worker_id, change_amount, reason, related_assignment_id)
                        VALUES
                            (:wid::uuid, -10, 'SLA breach — assignment not completed in time', :aid::uuid)
                    """),
                    {"wid": worker_id, "aid": assignment_id},
                )

        db.commit()
        logger.info("Processed %d SLA breaches", len(breached_ids))
        return {"breached_count": len(breached_ids)}

    except Exception as exc:
        db.rollback()
        logger.exception("Error in detect_sla_breaches")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@celery_app.task(name="sla.auto_escalate", bind=True, max_retries=3)
def auto_escalate_breached(self):
    """
    Auto-escalate complaints whose verification SLA has been breached.

    Logic:
      - Find breached verification SLA trackers (panchayat/mandal/district)
        that have NOT been resolved yet.
      - For panchayat → escalate to mandal.
      - For mandal → escalate to district.
      - District verification breaches have nowhere to go — just log them.
      - Create Escalation row with trigger_type='sla_breach'.
      - Create a new verification SLA tracker for the next level.
      - Resolve the old tracker.

    DB triggers handle updating complaint.status and current_review_level
    when the Escalation row is inserted.
    """
    db = get_sync_db()
    try:
        # Find breached, unresolved verification SLA trackers
        rows = db.execute(
            text("""
                SELECT st.id, st.tracker_type, st.complaint_id
                FROM sla_trackers st
                WHERE st.breached = true
                  AND st.resolved_at IS NULL
                  AND st.tracker_type IN ('panchayat_verification', 'mandal_verification')
                  AND st.complaint_id IS NOT NULL
            """)
        ).fetchall()

        if not rows:
            logger.info("No verification SLA breaches to auto-escalate")
            return {"escalated_count": 0}

        escalation_map = {
            "panchayat_verification": ("panchayat", "mandal", "mandal_verification"),
            "mandal_verification": ("mandal", "district", "district_verification"),
        }

        escalated_count = 0

        for r in rows:
            tracker_type = r.tracker_type
            complaint_id = str(r.complaint_id)
            sla_id = str(r.id)

            if tracker_type not in escalation_map:
                continue

            from_level, to_level, next_tracker_type = escalation_map[tracker_type]

            # Check if complaint is already at or beyond the target level
            complaint_row = db.execute(
                text("""
                    SELECT current_review_level, status
                    FROM complaints
                    WHERE id = :cid::uuid
                """),
                {"cid": complaint_id},
            ).fetchone()

            if not complaint_row:
                continue

            # Skip if already escalated past this point or in a terminal state
            if complaint_row.current_review_level != from_level:
                # Already escalated — just resolve the tracker
                db.execute(
                    text("UPDATE sla_trackers SET resolved_at = now() WHERE id = :sid::uuid"),
                    {"sid": sla_id},
                )
                continue

            if complaint_row.status in ("closed", "dismissed"):
                db.execute(
                    text("UPDATE sla_trackers SET resolved_at = now() WHERE id = :sid::uuid"),
                    {"sid": sla_id},
                )
                continue

            # Insert Escalation row — DB triggers will update complaint status
            db.execute(
                text("""
                    INSERT INTO escalations
                        (complaint_id, from_level, to_level, trigger_type, reason, sla_tracker_id)
                    VALUES
                        (:cid::uuid, :from, :to, 'sla_breach',
                         'Auto-escalated due to SLA breach at ' || :from || ' level',
                         :sid::uuid)
                """),
                {"cid": complaint_id, "from": from_level, "to": to_level, "sid": sla_id},
            )

            # Resolve old SLA tracker
            db.execute(
                text("UPDATE sla_trackers SET resolved_at = now() WHERE id = :sid::uuid"),
                {"sid": sla_id},
            )

            # Create new verification SLA for the next level
            # Get duration from sla_configs
            sla_cfg = db.execute(
                text("SELECT duration_hours FROM sla_configs WHERE tracker_type = :tt"),
                {"tt": next_tracker_type},
            ).fetchone()

            duration_hours = sla_cfg.duration_hours if sla_cfg else 48

            db.execute(
                text("""
                    INSERT INTO sla_trackers
                        (tracker_type, complaint_id, due_at)
                    VALUES
                        (:tt, :cid::uuid, now() + make_interval(hours => :hrs))
                """),
                {"tt": next_tracker_type, "cid": complaint_id, "hrs": duration_hours},
            )

            escalated_count += 1

        db.commit()
        logger.info("Auto-escalated %d complaints", escalated_count)
        return {"escalated_count": escalated_count}

    except Exception as exc:
        db.rollback()
        logger.exception("Error in auto_escalate_breached")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
