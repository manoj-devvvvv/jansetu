"""
Similarity-based complaint clustering engine.

This is the core matching logic. Given a new complaint's embedding,
it finds semantically similar open complaints within the SAME
department AND jurisdiction (panchayat-level first, then mandal-level),
and determines which MasterIssue cluster the new complaint belongs to.

Key design principles:
  - Only cluster complaints in the SAME department (water ≠ roads)
  - Only cluster complaints in the SAME jurisdiction
  - Only cluster complaints that are still OPEN (not closed/dismissed)
  - Similarity threshold is strict (≥ 0.75 cosine) to avoid false clusters
  - Panchayat-level clustering first, then mandal-level for broader patterns
"""

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session
import logging
from typing import List, Tuple
import uuid as _uuid

logger = logging.getLogger(__name__)

# ── Thresholds ───────────────────────────────────────────────────────────────
# Cosine similarity threshold for clustering.
# 0.75 is strict enough to avoid grouping unrelated issues.
PANCHAYAT_SIMILARITY_THRESHOLD = 0.75
MANDAL_SIMILARITY_THRESHOLD = 0.80  # stricter for mandal-level (wider area)

# Minimum members for a MasterIssue to be considered significant
MIN_CLUSTER_SIZE = 3

# Member count thresholds for fast-tracking based on severity
FAST_TRACK_THRESHOLDS = {
    "critical": 2,   # 2+ critical complaints → fast-track immediately
    "high": 3,       # 3+ high complaints → fast-track
    "medium": 5,     # 5+ medium complaints → fast-track
    "low": 10,       # 10+ low complaints → fast-track
}


def find_similar_complaints(
    db: Session,
    embedding: List[float],
    department_id: str,
    jurisdiction_id: str,
    exclude_complaint_id: str | None = None,
    threshold: float = PANCHAYAT_SIMILARITY_THRESHOLD,
) -> List[Tuple[str, float]]:
    """
    Find open complaints in the same department+jurisdiction that are
    semantically similar to the given embedding.

    Uses pgvector's cosine distance operator (<=>).
    Cosine similarity = 1 - cosine_distance.

    Returns:
        List of (complaint_id, similarity_score) tuples, sorted by similarity desc.
    """
    # Format embedding as a pgvector literal
    embedding_str = "[" + ",".join(str(f) for f in embedding) + "]"

    exclude_clause = ""
    params = {
        "dept_id": department_id,
        "jur_id": jurisdiction_id,
        "embedding": embedding_str,
        "threshold": 1.0 - threshold,  # cosine_distance threshold
    }

    if exclude_complaint_id:
        exclude_clause = "AND c.id != :excl_id::uuid"
        params["excl_id"] = exclude_complaint_id

    query = sa_text(f"""
        SELECT
            ce.complaint_id::text,
            1 - (ce.embedding <=> :embedding::vector) AS similarity
        FROM complaint_embeddings ce
        JOIN complaints c ON c.id = ce.complaint_id
        WHERE c.department_id = :dept_id::uuid
          AND (c.panchayat_id = :jur_id::uuid OR c.mandal_id = :jur_id::uuid)
          AND c.status NOT IN ('closed', 'dismissed')
          AND (ce.embedding <=> :embedding::vector) < :threshold
          {exclude_clause}
        ORDER BY similarity DESC
        LIMIT 50
    """)

    rows = db.execute(query, params).fetchall()
    return [(str(row[0]), float(row[1])) for row in rows]


def find_existing_master_issue(
    db: Session,
    department_id: str,
    jurisdiction_id: str,
    cluster_level: str,
) -> List[dict]:
    """
    Find active MasterIssues for a given department + jurisdiction + level.

    Returns:
        List of dicts with master issue info and their member complaint_ids.
    """
    rows = db.execute(
        sa_text("""
            SELECT
                mi.id::text AS master_issue_id,
                mi.member_count,
                mi.status,
                mi.is_fast_tracked,
                mi.representative_complaint_id::text
            FROM master_issues mi
            WHERE mi.department_id = :dept_id::uuid
              AND mi.jurisdiction_id = :jur_id::uuid
              AND mi.cluster_level = :level
              AND mi.status IN ('active', 'fast_tracked')
            ORDER BY mi.created_at DESC
        """),
        {"dept_id": department_id, "jur_id": jurisdiction_id, "level": cluster_level},
    ).fetchall()

    result = []
    for r in rows:
        # Get member complaint IDs for this master issue
        members = db.execute(
            sa_text("""
                SELECT complaint_id::text
                FROM master_issue_members
                WHERE master_issue_id = :mi_id::uuid
                  AND is_active = true
            """),
            {"mi_id": r[0]},
        ).fetchall()

        result.append({
            "master_issue_id": r[0],
            "member_count": r[1],
            "status": r[2],
            "is_fast_tracked": r[3],
            "representative_complaint_id": r[4],
            "member_complaint_ids": [str(m[0]) for m in members],
        })

    return result


def compute_cluster_similarity(
    db: Session,
    new_embedding: List[float],
    member_complaint_ids: List[str],
) -> float:
    """
    Compute the average cosine similarity between a new embedding
    and all members of an existing cluster.

    This ensures we don't add a complaint to a cluster where it only
    matches one member — it must be similar to the cluster as a whole.
    """
    if not member_complaint_ids:
        return 0.0

    embedding_str = "[" + ",".join(str(f) for f in new_embedding) + "]"

    rows = db.execute(
        sa_text("""
            SELECT
                AVG(1 - (ce.embedding <=> :embedding::vector)) AS avg_similarity
            FROM complaint_embeddings ce
            WHERE ce.complaint_id = ANY(:ids::uuid[])
        """),
        {"embedding": embedding_str, "ids": member_complaint_ids},
    ).fetchone()

    return float(rows[0]) if rows and rows[0] else 0.0
