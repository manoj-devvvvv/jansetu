"""
Master Issue orchestrator.

This module ties together embedding → clustering → MasterIssue management.
It is the entry point called after every complaint is created.

Workflow:
  1. Generate embedding for the new complaint text
  2. Store embedding in complaint_embeddings
  3. Update complaint_processing_status.embedding_status
  4. Find existing MasterIssues in the same department + panchayat
  5. If a matching cluster exists → join it (MasterIssueMember)
  6. If no match but similar complaints exist → create new MasterIssue
  7. Evaluate fast-tracking based on severity + member count
  8. Notify officers via the notification pipeline
"""

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session
import logging
import json

from app.core.clustering.embed import generate_embedding
from app.core.clustering.cluster import (
    find_similar_complaints,
    find_existing_master_issue,
    compute_cluster_similarity,
    PANCHAYAT_SIMILARITY_THRESHOLD,
    MANDAL_SIMILARITY_THRESHOLD,
    MIN_CLUSTER_SIZE,
    FAST_TRACK_THRESHOLDS,
)

logger = logging.getLogger(__name__)


def process_new_complaint(db: Session, complaint_id: str) -> dict:
    """
    Full clustering pipeline for a single new complaint.

    Called as a Celery task after complaint submission.

    Returns a dict summarizing what happened:
      {
        "complaint_id": "...",
        "embedded": true/false,
        "cluster_action": "joined_existing" | "created_new" | "no_cluster",
        "master_issue_id": "..." | null,
        "fast_tracked": true/false,
      }
    """
    result = {
        "complaint_id": complaint_id,
        "embedded": False,
        "cluster_action": "no_cluster",
        "master_issue_id": None,
        "fast_tracked": False,
    }

    # ── 1. Fetch the complaint ───────────────────────────────────────────
    complaint_row = db.execute(
        sa_text("""
            SELECT
                id::text, department_id::text, panchayat_id::text,
                mandal_id::text, district_id::text, raw_text,
                formalized_text, severity, status
            FROM complaints
            WHERE id = :cid::uuid
        """),
        {"cid": complaint_id},
    ).fetchone()

    if not complaint_row:
        logger.error("Complaint %s not found", complaint_id)
        return result

    # Use formalized_text if available, otherwise raw_text
    text_to_embed = complaint_row.formalized_text or complaint_row.raw_text
    if not text_to_embed or not text_to_embed.strip():
        logger.warning("Complaint %s has no text to embed, skipping clustering", complaint_id)
        _update_embedding_status(db, complaint_id, "failed")
        return result

    department_id = complaint_row.department_id
    panchayat_id = complaint_row.panchayat_id
    mandal_id = complaint_row.mandal_id
    severity = complaint_row.severity

    # ── 2. Generate and store embedding ──────────────────────────────────
    try:
        _update_embedding_status(db, complaint_id, "processing")
        embedding = generate_embedding(text_to_embed)
        _store_embedding(db, complaint_id, embedding)
        _update_embedding_status(db, complaint_id, "completed")
        result["embedded"] = True
        logger.info("Embedding generated for complaint %s", complaint_id)
    except Exception as e:
        logger.exception("Failed to generate embedding for complaint %s", complaint_id)
        _update_embedding_status(db, complaint_id, "failed")
        return result

    # ── 3. Panchayat-level clustering ────────────────────────────────────
    cluster_result = _try_cluster_at_level(
        db=db,
        complaint_id=complaint_id,
        embedding=embedding,
        department_id=department_id,
        jurisdiction_id=panchayat_id,
        cluster_level="panchayat",
        threshold=PANCHAYAT_SIMILARITY_THRESHOLD,
        severity=severity,
    )

    if cluster_result:
        result.update(cluster_result)
    else:
        # ── 4. Mandal-level clustering (broader pattern) ─────────────────
        mandal_result = _try_cluster_at_level(
            db=db,
            complaint_id=complaint_id,
            embedding=embedding,
            department_id=department_id,
            jurisdiction_id=mandal_id,
            cluster_level="mandal",
            threshold=MANDAL_SIMILARITY_THRESHOLD,
            severity=severity,
        )
        if mandal_result:
            result.update(mandal_result)

    db.commit()
    return result


def _try_cluster_at_level(
    db: Session,
    complaint_id: str,
    embedding: list,
    department_id: str,
    jurisdiction_id: str,
    cluster_level: str,
    threshold: float,
    severity: str,
) -> dict | None:
    """
    Attempt to cluster the complaint at a specific jurisdiction level.

    Strategy:
      A. Check existing MasterIssues → compute similarity to their members
         → if avg similarity >= threshold, join the cluster
      B. If no existing cluster matches, find similar standalone complaints
         → if enough similar ones exist, create a NEW MasterIssue
    """

    # ── A. Try joining an existing MasterIssue ───────────────────────────
    existing_clusters = find_existing_master_issue(
        db, department_id, jurisdiction_id, cluster_level
    )

    best_match = None
    best_similarity = 0.0

    for cluster in existing_clusters:
        if not cluster["member_complaint_ids"]:
            continue

        avg_sim = compute_cluster_similarity(
            db, embedding, cluster["member_complaint_ids"]
        )

        if avg_sim >= threshold and avg_sim > best_similarity:
            best_similarity = avg_sim
            best_match = cluster

    if best_match:
        # Join existing cluster
        _add_member_to_cluster(
            db,
            master_issue_id=best_match["master_issue_id"],
            complaint_id=complaint_id,
            similarity_score=best_similarity,
        )
        logger.info(
            "Complaint %s joined existing cluster %s (similarity: %.3f)",
            complaint_id, best_match["master_issue_id"], best_similarity,
        )

        # Check if fast-tracking should be triggered
        fast_tracked = _evaluate_fast_track(
            db, best_match["master_issue_id"], severity
        )

        return {
            "cluster_action": "joined_existing",
            "master_issue_id": best_match["master_issue_id"],
            "fast_tracked": fast_tracked,
        }

    # ── B. Try creating a new MasterIssue from similar standalone complaints ─
    similar = find_similar_complaints(
        db, embedding, department_id, jurisdiction_id,
        exclude_complaint_id=complaint_id, threshold=threshold,
    )

    if not similar:
        return None

    # Filter to only include complaints NOT already in a cluster at this level
    unclustered = _filter_unclustered(db, [cid for cid, _ in similar], cluster_level)

    if len(unclustered) < (MIN_CLUSTER_SIZE - 1):
        # Not enough similar unclustered complaints to form a cluster
        return None

    # Create a new MasterIssue with all similar complaints + the new one
    master_issue_id = _create_master_issue(
        db=db,
        department_id=department_id,
        jurisdiction_id=jurisdiction_id,
        cluster_level=cluster_level,
        complaint_id=complaint_id,
        members=unclustered,
        new_embedding=embedding,
    )

    logger.info(
        "Created new MasterIssue %s with %d members at %s level",
        master_issue_id, len(unclustered) + 1, cluster_level,
    )

    fast_tracked = _evaluate_fast_track(db, master_issue_id, severity)

    return {
        "cluster_action": "created_new",
        "master_issue_id": master_issue_id,
        "fast_tracked": fast_tracked,
    }


# ── Helper Functions ─────────────────────────────────────────────────────────


def _store_embedding(db: Session, complaint_id: str, embedding: list):
    """Insert or update the embedding in complaint_embeddings."""
    # Check if already exists (idempotency for retries)
    existing = db.execute(
        sa_text("SELECT id FROM complaint_embeddings WHERE complaint_id = :cid::uuid"),
        {"cid": complaint_id},
    ).fetchone()

    embedding_str = "[" + ",".join(str(f) for f in embedding) + "]"

    if existing:
        db.execute(
            sa_text("""
                UPDATE complaint_embeddings
                SET embedding = :emb::vector, model_version = 'bge-m3'
                WHERE complaint_id = :cid::uuid
            """),
            {"cid": complaint_id, "emb": embedding_str},
        )
    else:
        db.execute(
            sa_text("""
                INSERT INTO complaint_embeddings (complaint_id, embedding, model_version)
                VALUES (:cid::uuid, :emb::vector, 'bge-m3')
            """),
            {"cid": complaint_id, "emb": embedding_str},
        )


def _update_embedding_status(db: Session, complaint_id: str, status: str):
    """Update the embedding_status field in complaint_processing_status."""
    db.execute(
        sa_text("""
            UPDATE complaint_processing_status
            SET embedding_status = :status, updated_at = now()
            WHERE complaint_id = :cid::uuid
        """),
        {"cid": complaint_id, "status": status},
    )


def _filter_unclustered(
    db: Session, complaint_ids: list[str], cluster_level: str
) -> list[tuple[str, float]]:
    """
    Filter out complaints that are already members of an active MasterIssue
    at the given cluster level.

    Returns list of (complaint_id, similarity_score) for unclustered ones.
    """
    if not complaint_ids:
        return []

    # Get all complaint_ids already in a cluster at this level
    clustered = db.execute(
        sa_text("""
            SELECT mim.complaint_id::text
            FROM master_issue_members mim
            JOIN master_issues mi ON mi.id = mim.master_issue_id
            WHERE mim.complaint_id = ANY(:ids::uuid[])
              AND mim.is_active = true
              AND mi.cluster_level = :level
              AND mi.status IN ('active', 'fast_tracked')
        """),
        {"ids": complaint_ids, "level": cluster_level},
    ).fetchall()

    clustered_set = {str(r[0]) for r in clustered}
    # Return only unclustered ones (we lost similarity scores here,
    # but they were all above threshold)
    return [(cid, 0.0) for cid in complaint_ids if cid not in clustered_set]


def _add_member_to_cluster(
    db: Session, master_issue_id: str, complaint_id: str, similarity_score: float
):
    """Add a complaint as a member of an existing MasterIssue."""
    # Check if already a member (idempotency)
    existing = db.execute(
        sa_text("""
            SELECT id FROM master_issue_members
            WHERE master_issue_id = :mi_id::uuid
              AND complaint_id = :cid::uuid
              AND is_active = true
        """),
        {"mi_id": master_issue_id, "cid": complaint_id},
    ).fetchone()

    if existing:
        return

    db.execute(
        sa_text("""
            INSERT INTO master_issue_members
                (master_issue_id, complaint_id, similarity_score)
            VALUES (:mi_id::uuid, :cid::uuid, :sim)
        """),
        {"mi_id": master_issue_id, "cid": complaint_id, "sim": similarity_score},
    )

    # Update member_count
    db.execute(
        sa_text("""
            UPDATE master_issues
            SET member_count = member_count + 1,
                updated_at = now()
            WHERE id = :mi_id::uuid
        """),
        {"mi_id": master_issue_id},
    )


def _create_master_issue(
    db: Session,
    department_id: str,
    jurisdiction_id: str,
    cluster_level: str,
    complaint_id: str,
    members: list[tuple[str, float]],
    new_embedding: list,
) -> str:
    """
    Create a new MasterIssue and add all members (including the new complaint).

    The representative_complaint_id is set to the new complaint (the one that
    triggered cluster creation).
    """
    # Compute centroid location from all complaints in the cluster
    all_ids = [complaint_id] + [cid for cid, _ in members]

    centroid = db.execute(
        sa_text("""
            SELECT ST_AsText(ST_Centroid(ST_Collect(location)))
            FROM complaints
            WHERE id = ANY(:ids::uuid[])
        """),
        {"ids": all_ids},
    ).fetchone()

    centroid_wkt = centroid[0] if centroid and centroid[0] else None
    centroid_param = f"SRID=4326;{centroid_wkt}" if centroid_wkt else None

    # Create the master issue
    row = db.execute(
        sa_text("""
            INSERT INTO master_issues
                (department_id, jurisdiction_id, cluster_level,
                 representative_complaint_id, centroid_location, member_count)
            VALUES
                (:dept::uuid, :jur::uuid, :level,
                 :rep::uuid,
                 CASE WHEN :centroid IS NOT NULL
                      THEN ST_GeomFromText(:centroid_clean, 4326)
                      ELSE NULL END,
                 :count)
            RETURNING id::text
        """),
        {
            "dept": department_id,
            "jur": jurisdiction_id,
            "level": cluster_level,
            "rep": complaint_id,
            "centroid": centroid_param,
            "centroid_clean": centroid_wkt,
            "count": len(all_ids),
        },
    ).fetchone()

    master_issue_id = row[0]

    # Add all members
    for member_cid, sim_score in members:
        db.execute(
            sa_text("""
                INSERT INTO master_issue_members
                    (master_issue_id, complaint_id, similarity_score)
                VALUES (:mi_id::uuid, :cid::uuid, :sim)
            """),
            {"mi_id": master_issue_id, "cid": member_cid, "sim": sim_score},
        )

    # Add the triggering complaint itself
    db.execute(
        sa_text("""
            INSERT INTO master_issue_members
                (master_issue_id, complaint_id, similarity_score)
            VALUES (:mi_id::uuid, :cid::uuid, 1.0)
        """),
        {"mi_id": master_issue_id, "cid": complaint_id},
    )

    return master_issue_id


def _evaluate_fast_track(db: Session, master_issue_id: str, new_severity: str) -> bool:
    """
    Evaluate whether a MasterIssue should be fast-tracked based on
    member count and the severity of its constituent complaints.

    Fast-track thresholds:
      critical: 2+    high: 3+    medium: 5+    low: 10+
    """
    mi_row = db.execute(
        sa_text("""
            SELECT member_count, is_fast_tracked, status
            FROM master_issues
            WHERE id = :mi_id::uuid
        """),
        {"mi_id": master_issue_id},
    ).fetchone()

    if not mi_row or mi_row.is_fast_tracked:
        return mi_row.is_fast_tracked if mi_row else False

    member_count = mi_row.member_count

    # Determine the worst severity among all member complaints
    severity_row = db.execute(
        sa_text("""
            SELECT c.severity, COUNT(*) as cnt
            FROM master_issue_members mim
            JOIN complaints c ON c.id = mim.complaint_id
            WHERE mim.master_issue_id = :mi_id::uuid
              AND mim.is_active = true
            GROUP BY c.severity
            ORDER BY
                CASE c.severity
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                END
            LIMIT 1
        """),
        {"mi_id": master_issue_id},
    ).fetchone()

    if not severity_row:
        return False

    worst_severity = severity_row.severity
    threshold = FAST_TRACK_THRESHOLDS.get(worst_severity, 10)

    if member_count >= threshold:
        # Fast-track the master issue
        db.execute(
            sa_text("""
                UPDATE master_issues
                SET is_fast_tracked = true,
                    fast_tracked_at = now(),
                    status = 'fast_tracked',
                    updated_at = now()
                WHERE id = :mi_id::uuid
            """),
            {"mi_id": master_issue_id},
        )

        logger.info(
            "Master issue %s FAST-TRACKED: %d members, worst severity=%s",
            master_issue_id, member_count, worst_severity,
        )

        # Send fast-track notification to officers
        try:
            from app.tasks.notification_tasks import send_notification
            send_notification.delay(
                notification_type="escalation",
                related_complaint_id=None,
                payload={
                    "message": f"Master Issue fast-tracked: {member_count} similar complaints detected ({worst_severity} severity)",
                    "master_issue_id": master_issue_id,
                    "action": "view_master_issue",
                    "severity": worst_severity,
                    "member_count": member_count,
                },
            )
        except Exception:
            logger.exception("Failed to send fast-track notification")

        return True

    return False
