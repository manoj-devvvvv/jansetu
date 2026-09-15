"""
Historic Intelligence System — Historical Trends & Recurring Failures.

Analyzes master issues to detect seasonal recurring patterns and 
frequent non-seasonal recurring failures. Populates the 
`recurring_issue_patterns` table.
"""

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)

def analyze_seasonal_trends(db: Session):
    """
    Detects seasonal recurring issues.
    Groups master issues by jurisdiction, department, and month.
    If multiple master issues occur in the same month across years, 
    or frequently within the same month, we register a pattern.
    """
    logger.info("Starting seasonal trends analysis...")
    
    # We find groups that have at least 2 master issues in the same month
    query = sa_text("""
        SELECT
            jurisdiction_id,
            department_id,
            EXTRACT(MONTH FROM created_at)::int AS pattern_month,
            ARRAY_AGG(DISTINCT EXTRACT(YEAR FROM created_at)::int) AS occurrence_years,
            COUNT(id)::int AS recurrence_count,
            ARRAY_AGG(id) AS mi_ids,
            MIN(created_at) AS first_detected,
            MAX(created_at) AS last_detected
        FROM master_issues
        GROUP BY jurisdiction_id, department_id, EXTRACT(MONTH FROM created_at)
        HAVING COUNT(id) >= 2
    """)
    
    results = db.execute(query).fetchall()
    
    
    # We don't have a unique constraint on (jurisdiction_id, department_id, pattern_month)
    # So it's better to update if it exists, or insert.
    # Let's find existing first.
    
    for row in results:
        jid = row.jurisdiction_id
        did = row.department_id
        p_month = row.pattern_month
        years = row.occurrence_years
        r_count = row.recurrence_count
        mi_ids = row.mi_ids
        first_dt = row.first_detected
        last_dt = row.last_detected
        
        # Calculate confidence score
        # Base confidence on how many distinct years it occurred, plus total count
        year_score = min((len(years) / 3.0) * 0.6, 0.6)  # max 0.6 from years (3+ years = 0.6)
        count_score = min((r_count / 10.0) * 0.4, 0.4)   # max 0.4 from count (10+ issues = 0.4)
        confidence = round(year_score + count_score, 4)
        
        # Determine description
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        desc = f"Seasonal recurring issue typically occurring in {months[p_month-1]}. Detected {r_count} times across {len(years)} year(s)."

        # Check if pattern exists
        check_q = sa_text("""
            SELECT id FROM recurring_issue_patterns
            WHERE jurisdiction_id = :jid::uuid
              AND department_id = :did::uuid
              AND pattern_month = :p_month
        """)
        existing = db.execute(check_q, {"jid": jid, "did": did, "p_month": p_month}).fetchone()
        
        if existing:
            # Update
            update_q = sa_text("""
                UPDATE recurring_issue_patterns
                SET occurrence_years = :years::int[],
                    recurrence_count = :r_count,
                    confidence_score = :score,
                    description = :desc,
                    related_master_issue_ids = :mi_ids::uuid[],
                    last_detected_at = :last_detected,
                    is_active = true
                WHERE id = :id::uuid
            """)
            db.execute(update_q, {
                "years": years,
                "r_count": r_count,
                "score": confidence,
                "desc": desc,
                "mi_ids": mi_ids,
                "last_detected": last_dt,
                "id": existing.id
            })
        else:
            # Insert
            insert_q = sa_text("""
                INSERT INTO recurring_issue_patterns (
                    jurisdiction_id,
                    department_id,
                    pattern_month,
                    occurrence_years,
                    recurrence_count,
                    confidence_score,
                    description,
                    related_master_issue_ids,
                    first_detected_at,
                    last_detected_at,
                    is_active
                ) VALUES (
                    :jid::uuid, :did::uuid, :p_month, :years::int[], :r_count, :score, :desc, :mi_ids::uuid[], :first_detected, :last_detected, true
                )
            """)
            db.execute(insert_q, {
                "jid": jid, "did": did, "p_month": p_month, "years": years,
                "r_count": r_count, "score": confidence, "desc": desc,
                "mi_ids": mi_ids, "first_detected": first_dt, "last_detected": last_dt
            })
            
    db.commit()
    logger.info(f"Seasonal trends analysis complete. Processed {len(results)} seasonal patterns.")

def analyze_recurring_failures(db: Session):
    """
    Detects short-term frequent recurring failures (not bound to a specific month).
    Looks at the last 3 months for high volumes of issues in the same jurisdiction/department.
    """
    logger.info("Starting recurring failures analysis...")
    
    # Find groups with >= 3 master issues in the last 90 days
    query = sa_text("""
        SELECT
            jurisdiction_id,
            department_id,
            ARRAY_AGG(DISTINCT EXTRACT(YEAR FROM created_at)::int) AS occurrence_years,
            COUNT(id)::int AS recurrence_count,
            ARRAY_AGG(id) AS mi_ids,
            MIN(created_at) AS first_detected,
            MAX(created_at) AS last_detected
        FROM master_issues
        WHERE created_at >= NOW() - INTERVAL '90 days'
        GROUP BY jurisdiction_id, department_id
        HAVING COUNT(id) >= 3
    """)
    
    results = db.execute(query).fetchall()
    
    for row in results:
        jid = row.jurisdiction_id
        did = row.department_id
        years = row.occurrence_years
        r_count = row.recurrence_count
        mi_ids = row.mi_ids
        first_dt = row.first_detected
        last_dt = row.last_detected
        
        # Confidence score based heavily on volume, as it's short-term
        confidence = round(min((r_count / 15.0) * 0.8 + 0.1, 0.99), 4)
        
        desc = f"Frequent recurring failure: {r_count} issues detected within a 90-day window."

        # Check if a non-seasonal pattern exists
        check_q = sa_text("""
            SELECT id FROM recurring_issue_patterns
            WHERE jurisdiction_id = :jid::uuid
              AND department_id = :did::uuid
              AND pattern_month IS NULL
        """)
        existing = db.execute(check_q, {"jid": jid, "did": did}).fetchone()
        
        if existing:
            update_q = sa_text("""
                UPDATE recurring_issue_patterns
                SET occurrence_years = :years::int[],
                    recurrence_count = :r_count,
                    confidence_score = :score,
                    description = :desc,
                    related_master_issue_ids = :mi_ids::uuid[],
                    last_detected_at = :last_detected,
                    is_active = true
                WHERE id = :id::uuid
            """)
            db.execute(update_q, {
                "years": years,
                "r_count": r_count,
                "score": confidence,
                "desc": desc,
                "mi_ids": mi_ids,
                "last_detected": last_dt,
                "id": existing.id
            })
        else:
            insert_q = sa_text("""
                INSERT INTO recurring_issue_patterns (
                    jurisdiction_id,
                    department_id,
                    pattern_month,
                    occurrence_years,
                    recurrence_count,
                    confidence_score,
                    description,
                    related_master_issue_ids,
                    first_detected_at,
                    last_detected_at,
                    is_active
                ) VALUES (
                    :jid::uuid, :did::uuid, NULL, :years::int[], :r_count, :score, :desc, :mi_ids::uuid[], :first_detected, :last_detected, true
                )
            """)
            db.execute(insert_q, {
                "jid": jid, "did": did, "years": years,
                "r_count": r_count, "score": confidence, "desc": desc,
                "mi_ids": mi_ids, "first_detected": first_dt, "last_detected": last_dt
            })
            
    db.commit()
    logger.info(f"Recurring failures analysis complete. Processed {len(results)} short-term failure patterns.")

def run_full_intelligence_pipeline(db: Session):
    """
    Runs the complete historic intelligence pipeline.
    """
    logger.info("Starting Full Historic Intelligence Pipeline...")
    analyze_seasonal_trends(db)
    analyze_recurring_failures(db)
    logger.info("Full Historic Intelligence Pipeline completed.")
