"""
Anomaly detection — Flag Generation.

Analyzes the computed features to determine if an assignment
should be flagged for anomalous behaviour. Flags are stored in
the anomaly_flags table.

Flag types (from schema's anomaly_flag_type enum):
  - impossible_travel: Worker traveled unrealistically fast between jobs
  - fast_completion: Worker completed a task in an impossibly short time
  - duplicate_photo: Worker submitted a previously-used photo
  - model_flagged: XGBoost model predicted anomalous behaviour
"""

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Detection Thresholds ─────────────────────────────────────────────────────
# Each threshold maps to a severity level.

# Impossible travel speed thresholds (km/h)
IMPOSSIBLE_TRAVEL_CRITICAL = 200.0   # high severity
IMPOSSIBLE_TRAVEL_SUSPICIOUS = 120.0  # medium severity
IMPOSSIBLE_TRAVEL_ELEVATED = 80.0     # low severity (only flagged if < 5 min between jobs)

# Fast completion thresholds (seconds)
FAST_COMPLETION_CRITICAL = 60        # < 1 min → high severity
FAST_COMPLETION_SUSPICIOUS = 120     # < 2 min → medium severity
FAST_COMPLETION_ELEVATED = 300       # < 5 min → low severity

# Model anomaly score thresholds
MODEL_SCORE_HIGH = 0.85
MODEL_SCORE_MEDIUM = 0.70
MODEL_SCORE_LOW = 0.50

# Worker penalty points per severity
PENALTY_MAP = {
    "high": -15,
    "medium": -10,
    "low": -5,
}


def detect_anomalies(
    db: Session,
    worker_id: str,
    assignment_id: str,
    feature_vector: dict,
    anomaly_score: Optional[float] = None,
) -> list[dict]:
    """
    Run all anomaly detection rules against the computed features.

    Returns a list of detected anomalies, each as:
      {"flag_type": str, "severity": str, "score": float}
    """
    detected = []

    # ── 1. Impossible Travel Detection ───────────────────────────────────
    speed = feature_vector.get("implied_travel_speed_kmph")
    time_since_prev = feature_vector.get("time_since_previous_job_seconds")

    if speed is not None:
        if speed >= IMPOSSIBLE_TRAVEL_CRITICAL:
            detected.append({
                "flag_type": "impossible_travel",
                "severity": "high",
                "score": min(1.0, speed / 300.0),
            })
        elif speed >= IMPOSSIBLE_TRAVEL_SUSPICIOUS:
            detected.append({
                "flag_type": "impossible_travel",
                "severity": "medium",
                "score": min(1.0, speed / 300.0),
            })
        elif speed >= IMPOSSIBLE_TRAVEL_ELEVATED and time_since_prev is not None:
            # Only flag elevated speed if the gap between jobs is very short
            if time_since_prev < 300:  # < 5 minutes
                detected.append({
                    "flag_type": "impossible_travel",
                    "severity": "low",
                    "score": min(1.0, speed / 300.0),
                })

    # ── 2. Fast Completion Detection ─────────────────────────────────────
    duration = feature_vector.get("completion_duration_seconds")

    if duration is not None and duration >= 0:
        if duration < FAST_COMPLETION_CRITICAL:
            detected.append({
                "flag_type": "fast_completion",
                "severity": "high",
                "score": max(0.0, 1.0 - (duration / FAST_COMPLETION_CRITICAL)),
            })
        elif duration < FAST_COMPLETION_SUSPICIOUS:
            detected.append({
                "flag_type": "fast_completion",
                "severity": "medium",
                "score": max(0.0, 1.0 - (duration / FAST_COMPLETION_SUSPICIOUS)),
            })
        elif duration < FAST_COMPLETION_ELEVATED:
            detected.append({
                "flag_type": "fast_completion",
                "severity": "low",
                "score": max(0.0, 1.0 - (duration / FAST_COMPLETION_ELEVATED)),
            })

    # ── 3. Duplicate Photo Detection ─────────────────────────────────────
    is_dup = feature_vector.get("is_duplicate_photo", False)

    if is_dup:
        detected.append({
            "flag_type": "duplicate_photo",
            "severity": "high",  # photo reuse is always high severity
            "score": 1.0,
        })

    # ── 4. Model-Based Detection (XGBoost score) ─────────────────────────
    if anomaly_score is not None:
        if anomaly_score >= MODEL_SCORE_HIGH:
            detected.append({
                "flag_type": "model_flagged",
                "severity": "high",
                "score": anomaly_score,
            })
        elif anomaly_score >= MODEL_SCORE_MEDIUM:
            detected.append({
                "flag_type": "model_flagged",
                "severity": "medium",
                "score": anomaly_score,
            })
        elif anomaly_score >= MODEL_SCORE_LOW:
            detected.append({
                "flag_type": "model_flagged",
                "severity": "low",
                "score": anomaly_score,
            })

    return detected


def persist_flags(
    db: Session,
    worker_id: str,
    assignment_id: str,
    flags: list[dict],
) -> list[str]:
    """
    Insert detected anomaly flags into the anomaly_flags table,
    apply score penalties to the worker, and return the IDs of created flags.
    """
    if not flags:
        return []

    created_ids = []

    for flag in flags:
        # ── Check if this flag type already exists for this assignment ────
        existing = db.execute(
            sa_text("""
                SELECT id FROM anomaly_flags
                WHERE worker_assignment_id = :aid::uuid
                  AND flag_type = :ftype
            """),
            {"aid": assignment_id, "ftype": flag["flag_type"]},
        ).fetchone()

        if existing:
            logger.debug(
                "Flag %s already exists for assignment %s, skipping",
                flag["flag_type"], assignment_id,
            )
            continue

        # ── Insert the anomaly flag ──────────────────────────────────────
        row = db.execute(
            sa_text("""
                INSERT INTO anomaly_flags
                    (worker_id, worker_assignment_id, flag_type,
                     severity, anomaly_score)
                VALUES
                    (:wid::uuid, :aid::uuid, :ftype,
                     :severity, :score)
                RETURNING id::text
            """),
            {
                "wid": worker_id,
                "aid": assignment_id,
                "ftype": flag["flag_type"],
                "severity": flag["severity"],
                "score": flag["score"],
            },
        ).fetchone()

        if row:
            created_ids.append(row[0])

        # ── Apply score penalty ──────────────────────────────────────────
        penalty = PENALTY_MAP.get(flag["severity"], -5)
        _apply_penalty(db, worker_id, assignment_id, flag, penalty)

        logger.warning(
            "ANOMALY FLAG: worker=%s assignment=%s type=%s severity=%s score=%.3f",
            worker_id, assignment_id, flag["flag_type"], flag["severity"], flag["score"],
        )

    # ── Send notification to officers ────────────────────────────────────
    if created_ids:
        _notify_officers(worker_id, assignment_id, flags)

    db.commit()
    return created_ids


def _apply_penalty(
    db: Session,
    worker_id: str,
    assignment_id: str,
    flag: dict,
    penalty: int,
):
    """
    Apply a profile_score penalty to the worker and log it in
    worker_score_history.
    """
    # Clamp the score to [0, 100]
    db.execute(
        sa_text("""
            UPDATE workers
            SET profile_score = GREATEST(0, LEAST(100, profile_score + :penalty)),
                updated_at = now()
            WHERE id = :wid::uuid
        """),
        {"wid": worker_id, "penalty": penalty},
    )

    # Log to score history
    reason = f"Anomaly detected: {flag['flag_type']} ({flag['severity']} severity, score={flag['score']:.3f})"
    db.execute(
        sa_text("""
            INSERT INTO worker_score_history
                (worker_id, change_amount, reason, related_assignment_id)
            VALUES
                (:wid::uuid, :change, :reason, :aid::uuid)
        """),
        {
            "wid": worker_id,
            "change": penalty,
            "reason": reason,
            "aid": assignment_id,
        },
    )


def _notify_officers(worker_id: str, assignment_id: str, flags: list[dict]):
    """Send anomaly alert notification to officers via Celery."""
    try:
        from app.tasks.notification_tasks import send_notification

        worst = max(flags, key=lambda f: {"high": 3, "medium": 2, "low": 1}[f["severity"]])
        flag_types = ", ".join(f["flag_type"] for f in flags)

        send_notification.delay(
            notification_type="general",
            related_worker_assignment_id=assignment_id,
            payload={
                "message": f"Anomaly detected for worker: {flag_types}",
                "worker_id": worker_id,
                "assignment_id": assignment_id,
                "severity": worst["severity"],
                "flag_count": len(flags),
                "action": "review_anomaly",
            },
        )
    except Exception:
        logger.exception("Failed to send anomaly notification")
