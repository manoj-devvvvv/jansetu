"""
Anomaly detection — XGBoost Model Inference & Pipeline Orchestrator.

This module handles:
  1. XGBoost model loading and inference for anomaly scoring
  2. The complete anomaly detection pipeline orchestration
  3. Batch anomaly scanning for periodic scheduler-driven checks

The XGBoost model is trained offline on historical data. This module
loads the trained model and runs inference on new feature vectors.
When no trained model is available, it falls back to a rule-based
heuristic scoring system.
"""

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session
import logging
import os
from typing import Optional

from app.core.anomaly_detection.features import extract_features
from app.core.anomaly_detection.flags import detect_anomalies, persist_flags

logger = logging.getLogger(__name__)

# ── Model Configuration ──────────────────────────────────────────────────────
MODEL_PATH = os.environ.get(
    "ANOMALY_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "xgboost_model.json"),
)

_model = None
_model_loaded = False


def _load_model():
    """
    Lazy-load the XGBoost model. Falls back to heuristic if unavailable.
    """
    global _model, _model_loaded

    if _model_loaded:
        return _model

    _model_loaded = True

    if not os.path.exists(MODEL_PATH):
        logger.info(
            "XGBoost model not found at %s — using heuristic scoring",
            MODEL_PATH,
        )
        return None

    try:
        import xgboost as xgb
        _model = xgb.Booster()
        _model.load_model(MODEL_PATH)
        logger.info("XGBoost anomaly model loaded from %s", MODEL_PATH)
        return _model
    except ImportError:
        logger.warning("xgboost not installed — using heuristic scoring")
        return None
    except Exception:
        logger.exception("Error loading XGBoost model")
        return None


def predict_anomaly_score(feature_vector: dict) -> float:
    """
    Predict an anomaly score from the feature vector.

    Returns a float between 0.0 (normal) and 1.0 (anomalous).

    If XGBoost model is available, uses it for prediction.
    Otherwise, falls back to a weighted heuristic scoring system.
    """
    model = _load_model()

    if model is not None:
        return _xgboost_predict(model, feature_vector)

    return _heuristic_score(feature_vector)


def _xgboost_predict(model, feature_vector: dict) -> float:
    """Run XGBoost inference on the feature vector."""
    try:
        import xgboost as xgb
        import numpy as np

        # Build feature array in consistent order
        feature_names = [
            "distance_from_previous_job_meters",
            "time_since_previous_job_seconds",
            "implied_travel_speed_kmph",
            "completion_duration_seconds",
            "is_duplicate_photo",
            "has_arrival_location",
            "has_completion_location",
            "has_previous_job",
        ]

        values = []
        for name in feature_names:
            val = feature_vector.get(name)
            if val is None:
                values.append(float("nan"))
            elif isinstance(val, bool):
                values.append(1.0 if val else 0.0)
            else:
                values.append(float(val))

        dmatrix = xgb.DMatrix(
            np.array([values]),
            feature_names=feature_names,
            missing=float("nan"),
        )

        prediction = model.predict(dmatrix)[0]
        return float(max(0.0, min(1.0, prediction)))

    except Exception:
        logger.exception("XGBoost prediction failed, falling back to heuristic")
        return _heuristic_score(feature_vector)


def _heuristic_score(feature_vector: dict) -> float:
    """
    Compute a rule-based anomaly score when no XGBoost model is available.

    Weights:
      - Impossible travel speed: 0.30
      - Fast completion:         0.25
      - Duplicate photo:         0.30
      - Missing data:            0.15

    Each component contributes a score between 0 and 1.
    The final score is the weighted sum.
    """
    score = 0.0

    # ── Speed component (0.30 weight) ────────────────────────────────────
    speed = feature_vector.get("implied_travel_speed_kmph")
    if speed is not None:
        if speed >= 200:
            score += 0.30
        elif speed >= 120:
            score += 0.30 * (speed - 80) / (200 - 80)
        elif speed >= 80:
            score += 0.30 * 0.3 * (speed - 60) / (80 - 60)
    else:
        # No speed data — slight bump if we have a previous job
        if feature_vector.get("has_previous_job", False):
            score += 0.05  # suspicious: should have distance data

    # ── Completion duration component (0.25 weight) ──────────────────────
    duration = feature_vector.get("completion_duration_seconds")
    if duration is not None:
        if duration < 60:
            score += 0.25
        elif duration < 120:
            score += 0.25 * (1.0 - duration / 120.0)
        elif duration < 300:
            score += 0.25 * 0.3 * (1.0 - duration / 300.0)

    # ── Duplicate photo component (0.30 weight) ─────────────────────────
    if feature_vector.get("is_duplicate_photo", False):
        score += 0.30

    # ── Missing data component (0.15 weight) ─────────────────────────────
    missing_penalty = 0.0
    if not feature_vector.get("has_arrival_location", True):
        missing_penalty += 0.5
    if not feature_vector.get("has_completion_location", True):
        missing_penalty += 0.5
    score += 0.15 * missing_penalty

    return max(0.0, min(1.0, score))


# ── Pipeline Orchestrator ────────────────────────────────────────────────────


def run_anomaly_pipeline(
    db: Session,
    worker_id: str,
    assignment_id: str,
    completion_photo_bytes: Optional[bytes] = None,
) -> dict:
    """
    Full anomaly detection pipeline for a single completed assignment.

    Called after a worker completes an assignment.

    Steps:
      1. Extract features from assignment data
      2. Compute anomaly score (XGBoost or heuristic)
      3. Update anomaly_score in worker_completion_features
      4. Run flag detection rules
      5. Persist flags and apply penalties
      6. Notify officers if flags detected

    Returns:
        Summary dict with features, score, and flags.
    """
    result = {
        "worker_id": worker_id,
        "assignment_id": assignment_id,
        "features": {},
        "anomaly_score": 0.0,
        "flags": [],
        "flag_ids": [],
    }

    # ── 1. Extract features ──────────────────────────────────────────────
    features = extract_features(db, worker_id, assignment_id, completion_photo_bytes)

    if not features:
        logger.warning(
            "No features extracted for assignment %s, skipping anomaly detection",
            assignment_id,
        )
        return result

    result["features"] = features

    # ── 2. Compute anomaly score ─────────────────────────────────────────
    anomaly_score = predict_anomaly_score(features)
    result["anomaly_score"] = anomaly_score

    # ── 3. Update anomaly_score in worker_completion_features ────────────
    db.execute(
        sa_text("""
            UPDATE worker_completion_features
            SET anomaly_score = :score
            WHERE worker_assignment_id = :aid::uuid
        """),
        {"score": anomaly_score, "aid": assignment_id},
    )

    # ── 4. Detect anomalies ──────────────────────────────────────────────
    flags = detect_anomalies(db, worker_id, assignment_id, features, anomaly_score)
    result["flags"] = flags

    # ── 5. Persist flags and apply penalties ─────────────────────────────
    if flags:
        flag_ids = persist_flags(db, worker_id, assignment_id, flags)
        result["flag_ids"] = flag_ids
        logger.warning(
            "Anomaly pipeline complete for assignment %s: score=%.3f, %d flags",
            assignment_id, anomaly_score, len(flags),
        )
    else:
        db.commit()
        logger.info(
            "Anomaly pipeline complete for assignment %s: score=%.3f, clean",
            assignment_id, anomaly_score,
        )

    return result


def batch_scan_recent_completions(db: Session, hours: int = 24) -> dict:
    """
    Scan recently completed assignments that haven't been analyzed yet.

    This is called by the APScheduler as a periodic job to catch
    any assignments that may have been missed (e.g., if the Celery
    task failed on first attempt).

    Returns:
        Summary dict with counts.
    """
    rows = db.execute(
        sa_text("""
            SELECT
                wa.id::text AS assignment_id,
                wa.worker_id::text
            FROM worker_assignments wa
            LEFT JOIN worker_completion_features wcf
                ON wcf.worker_assignment_id = wa.id
            WHERE wa.status = 'completed'
              AND wa.completed_at > now() - interval ':hours hours'
              AND wcf.id IS NULL
            ORDER BY wa.completed_at DESC
            LIMIT 100
        """.replace(":hours", str(int(hours)))),
    ).fetchall()

    if not rows:
        logger.info("Batch scan: no unanalyzed completions found")
        return {"scanned": 0, "flagged": 0}

    scanned = 0
    flagged = 0

    for r in rows:
        try:
            result = run_anomaly_pipeline(db, r.worker_id, r.assignment_id)
            scanned += 1
            if result.get("flags"):
                flagged += len(result["flags"])
        except Exception:
            logger.exception(
                "Error scanning assignment %s in batch", r.assignment_id
            )
            db.rollback()

    logger.info("Batch scan complete: scanned=%d, flagged=%d", scanned, flagged)
    return {"scanned": scanned, "flagged": flagged}
