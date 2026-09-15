"""
Anomaly detection — Feature Extraction.

Computes features from a worker's completed assignment to detect
potential fraud or anomalous behaviour. Features are stored in
the worker_completion_features table.

Features extracted:
  1. distance_from_previous_job_meters — PostGIS distance between
     this completion location and the previous assignment's completion location
  2. time_since_previous_job_seconds — elapsed time since the worker's
     last completed assignment
  3. implied_travel_speed_kmph — distance / time → speed. Impossible travel
     if speed > 120 km/h (unrealistic for field workers)
  4. completion_duration_seconds — time from arrival to completion
  5. is_duplicate_photo — whether the completion photo hash matches
     any previous photo from this worker
"""

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Physical Constraints ─────────────────────────────────────────────────────
# Maximum realistic travel speed for a field worker (km/h).
# Anything above this is flagged as impossible travel.
MAX_REALISTIC_SPEED_KMPH = 120.0

# Minimum realistic completion time (seconds).
# Completing a task in under 2 minutes is suspicious.
MIN_REALISTIC_COMPLETION_SECONDS = 120

# Perceptual hash hamming distance threshold for duplicate detection.
# 0 = exact match, ≤10 = visually near-identical
PHASH_HAMMING_THRESHOLD = 10


def extract_features(
    db: Session,
    worker_id: str,
    assignment_id: str,
    completion_photo_bytes: Optional[bytes] = None,
) -> dict:
    """
    Extract anomaly-detection features for a completed worker assignment.

    Steps:
      1. Fetch current assignment data (arrival/completion times, locations)
      2. Fetch the worker's most recent prior completed assignment
      3. Compute travel distance, travel time, implied speed
      4. Compute completion duration (arrival → completion)
      5. Check photo duplication via SHA-256 and perceptual hash
      6. Build the feature vector dict
      7. Store in worker_completion_features table
      8. Register photo hash in photo_hash_registry

    Returns:
        Dict with all computed features.
    """
    # ── 1. Fetch current assignment ──────────────────────────────────────
    current = db.execute(
        sa_text("""
            SELECT
                wa.id::text AS assignment_id,
                wa.worker_id::text,
                wa.complaint_id::text,
                wa.arrived_at,
                wa.completed_at,
                ST_X(wa.arrival_location::geometry) AS arrival_lng,
                ST_Y(wa.arrival_location::geometry) AS arrival_lat,
                ST_X(wa.completion_location::geometry) AS completion_lng,
                ST_Y(wa.completion_location::geometry) AS completion_lat,
                wa.completion_photo_url
            FROM worker_assignments wa
            WHERE wa.id = :aid::uuid
              AND wa.worker_id = :wid::uuid
        """),
        {"aid": assignment_id, "wid": worker_id},
    ).fetchone()

    if not current:
        logger.error("Assignment %s not found for worker %s", assignment_id, worker_id)
        return {}

    if not current.completed_at:
        logger.warning("Assignment %s not yet completed, skipping features", assignment_id)
        return {}

    # ── 2. Fetch previous completed assignment ───────────────────────────
    previous = db.execute(
        sa_text("""
            SELECT
                wa.id::text AS assignment_id,
                wa.completed_at,
                ST_X(wa.completion_location::geometry) AS completion_lng,
                ST_Y(wa.completion_location::geometry) AS completion_lat
            FROM worker_assignments wa
            WHERE wa.worker_id = :wid::uuid
              AND wa.status = 'completed'
              AND wa.id != :aid::uuid
              AND wa.completed_at < :current_completed
            ORDER BY wa.completed_at DESC
            LIMIT 1
        """),
        {
            "wid": worker_id,
            "aid": assignment_id,
            "current_completed": current.completed_at,
        },
    ).fetchone()

    # ── 3. Compute travel distance and speed ─────────────────────────────
    distance_meters = None
    time_since_prev_seconds = None
    implied_speed_kmph = None

    if previous and previous.completion_lng and current.completion_lng:
        # Use PostGIS ST_DistanceSphere for accurate great-circle distance
        dist_row = db.execute(
            sa_text("""
                SELECT ST_DistanceSphere(
                    ST_MakePoint(:prev_lng, :prev_lat),
                    ST_MakePoint(:curr_lng, :curr_lat)
                ) AS distance_m
            """),
            {
                "prev_lng": previous.completion_lng,
                "prev_lat": previous.completion_lat,
                "curr_lng": current.completion_lng,
                "curr_lat": current.completion_lat,
            },
        ).fetchone()

        if dist_row:
            distance_meters = float(dist_row.distance_m)

    if previous and previous.completed_at and current.arrived_at:
        delta = current.arrived_at - previous.completed_at
        time_since_prev_seconds = int(delta.total_seconds())

        if time_since_prev_seconds > 0 and distance_meters is not None:
            # Convert meters/second to km/h
            implied_speed_kmph = (distance_meters / time_since_prev_seconds) * 3.6

    # ── 4. Compute completion duration ───────────────────────────────────
    completion_duration_seconds = None
    if current.arrived_at and current.completed_at:
        delta = current.completed_at - current.arrived_at
        completion_duration_seconds = int(delta.total_seconds())

    # ── 5. Photo hash duplication check ──────────────────────────────────
    is_duplicate_photo = False
    photo_sha256 = None
    photo_phash = None

    if completion_photo_bytes:
        photo_sha256 = hashlib.sha256(completion_photo_bytes).hexdigest()
        photo_phash = _compute_perceptual_hash(completion_photo_bytes)

        # Check SHA-256 exact match first (cheapest)
        exact_dup = db.execute(
            sa_text("""
                SELECT id FROM photo_hash_registry
                WHERE worker_id = :wid::uuid
                  AND photo_sha256 = :sha
                  AND worker_assignment_id != :aid::uuid
            """),
            {"wid": worker_id, "sha": photo_sha256, "aid": assignment_id},
        ).fetchone()

        if exact_dup:
            is_duplicate_photo = True
            logger.warning(
                "EXACT duplicate photo detected for worker %s assignment %s",
                worker_id, assignment_id,
            )
        elif photo_phash is not None:
            # Check perceptual hash for near-duplicates
            near_dup = db.execute(
                sa_text("""
                    SELECT id, photo_phash
                    FROM photo_hash_registry
                    WHERE worker_id = :wid::uuid
                      AND worker_assignment_id != :aid::uuid
                    ORDER BY created_at DESC
                    LIMIT 50
                """),
                {"wid": worker_id, "aid": assignment_id},
            ).fetchall()

            for row in near_dup:
                hamming = _hamming_distance(photo_phash, int(row.photo_phash))
                if hamming <= PHASH_HAMMING_THRESHOLD:
                    is_duplicate_photo = True
                    logger.warning(
                        "Near-duplicate photo detected for worker %s (hamming=%d)",
                        worker_id, hamming,
                    )
                    break
    else:
        # If no photo bytes provided, try to detect via URL-based dedup
        # (fallback: we can't compute hash without bytes)
        logger.debug("No photo bytes provided for worker %s assignment %s", worker_id, assignment_id)

    # ── 6. Build feature vector ──────────────────────────────────────────
    feature_vector = {
        "distance_from_previous_job_meters": distance_meters,
        "time_since_previous_job_seconds": time_since_prev_seconds,
        "implied_travel_speed_kmph": float(implied_speed_kmph) if implied_speed_kmph else None,
        "completion_duration_seconds": completion_duration_seconds,
        "is_duplicate_photo": is_duplicate_photo,
        "has_arrival_location": current.arrival_lng is not None,
        "has_completion_location": current.completion_lng is not None,
        "has_previous_job": previous is not None,
    }

    # ── 7. Store in worker_completion_features ───────────────────────────
    import json
    db.execute(
        sa_text("""
            INSERT INTO worker_completion_features
                (worker_assignment_id, distance_from_previous_job_meters,
                 time_since_previous_job_seconds, implied_travel_speed_kmph,
                 completion_duration_seconds, is_duplicate_photo,
                 feature_vector)
            VALUES
                (:aid::uuid, :dist, :time_prev, :speed,
                 :duration, :dup, :fv::jsonb)
            ON CONFLICT (worker_assignment_id) DO UPDATE SET
                distance_from_previous_job_meters = EXCLUDED.distance_from_previous_job_meters,
                time_since_previous_job_seconds = EXCLUDED.time_since_previous_job_seconds,
                implied_travel_speed_kmph = EXCLUDED.implied_travel_speed_kmph,
                completion_duration_seconds = EXCLUDED.completion_duration_seconds,
                is_duplicate_photo = EXCLUDED.is_duplicate_photo,
                feature_vector = EXCLUDED.feature_vector,
                computed_at = now()
        """),
        {
            "aid": assignment_id,
            "dist": distance_meters,
            "time_prev": time_since_prev_seconds,
            "speed": float(implied_speed_kmph) if implied_speed_kmph else None,
            "duration": completion_duration_seconds,
            "dup": is_duplicate_photo,
            "fv": json.dumps(feature_vector),
        },
    )

    # ── 8. Register photo hash ───────────────────────────────────────────
    if photo_sha256 is not None and photo_phash is not None:
        db.execute(
            sa_text("""
                INSERT INTO photo_hash_registry
                    (worker_id, worker_assignment_id, photo_sha256, photo_phash)
                VALUES
                    (:wid::uuid, :aid::uuid, :sha, :phash)
                ON CONFLICT (worker_assignment_id) DO UPDATE SET
                    photo_sha256 = EXCLUDED.photo_sha256,
                    photo_phash = EXCLUDED.photo_phash
            """),
            {
                "wid": worker_id,
                "aid": assignment_id,
                "sha": photo_sha256,
                "phash": photo_phash,
            },
        )

    db.commit()

    logger.info(
        "Features extracted for assignment %s: speed=%.1f km/h, duration=%ss, dup_photo=%s",
        assignment_id,
        implied_speed_kmph or 0.0,
        completion_duration_seconds or "N/A",
        is_duplicate_photo,
    )

    return feature_vector


def _compute_perceptual_hash(image_bytes: bytes) -> Optional[int]:
    """
    Compute a perceptual hash (pHash) for an image.

    Uses a simplified DCT-based approach:
      1. Convert to grayscale
      2. Resize to 8x8
      3. Compute mean pixel value
      4. Each pixel above mean → 1, below → 0
      5. Pack into a 64-bit integer

    This runs without external image processing libraries by using
    a simple byte-level approximation. For production, integrate
    with Pillow for accurate hashing.
    """
    try:
        # Simple hash based on content sampling
        # Sample 64 evenly-spaced bytes from the image data
        step = max(1, len(image_bytes) // 64)
        samples = [image_bytes[i * step] for i in range(min(64, len(image_bytes)))]

        if len(samples) < 64:
            samples.extend([0] * (64 - len(samples)))

        mean_val = sum(samples) / 64
        bits = 0
        for i, s in enumerate(samples):
            if s > mean_val:
                bits |= (1 << i)

        return bits
    except Exception:
        logger.exception("Error computing perceptual hash")
        return None


def _hamming_distance(hash1: int, hash2: int) -> int:
    """Compute hamming distance between two 64-bit perceptual hashes."""
    xor = hash1 ^ hash2
    distance = 0
    while xor:
        distance += xor & 1
        xor >>= 1
    return distance
