import uuid as _uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, text

from app.models.complaint import Complaint, ComplaintStatusHistory, ComplaintProcessingStatus
from app.models.jurisdiction import Department
from app.models.officer import Officer
from app.models.worker import WorkerAssignment
from app.models.sla import Escalation, SlaTracker
from app.models.master_issue import RecurringIssuePattern


# ── Exceptions ───────────────────────────────────────────────────────────────


class ComplaintNotInJurisdiction(Exception):
    def __init__(self) -> None:
        super().__init__("Complaint not in officer's district")


class InvalidInput(Exception):
    pass


# ── Complaint Queue ──────────────────────────────────────────────────────────


async def get_complaint_queue(
    db: AsyncSession,
    officer: Officer,
    status_filter: str | None = None,
    department_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Paginated complaint queue — complaints at district review level."""

    base = select(Complaint).where(
        Complaint.district_id == officer.jurisdiction_id,
        Complaint.current_review_level == "district",
    )
    count_base = select(func.count()).select_from(Complaint).where(
        Complaint.district_id == officer.jurisdiction_id,
        Complaint.current_review_level == "district",
    )

    if status_filter:
        base = base.where(Complaint.status == status_filter)
        count_base = count_base.where(Complaint.status == status_filter)

    if department_filter:
        dept = await db.scalar(
            select(Department).where(Department.code == department_filter)
        )
        if dept:
            base = base.where(Complaint.department_id == dept.id)
            count_base = count_base.where(Complaint.department_id == dept.id)

    total = await db.scalar(count_base)
    offset = (page - 1) * page_size
    result = await db.scalars(
        base.order_by(Complaint.created_at.asc()).offset(offset).limit(page_size)
    )

    return {
        "complaints": list(result.all()),
        "total": total or 0,
        "page": page,
        "page_size": page_size,
    }


# ── Complaint Detail ─────────────────────────────────────────────────────────


async def get_complaint_detail(
    db: AsyncSession, officer: Officer, complaint_id: str
) -> dict:
    """Single complaint detail — must be in this district's jurisdiction."""

    try:
        complaint_uuid = _uuid.UUID(complaint_id)
    except ValueError:
        raise ComplaintNotInJurisdiction()

    complaint = await db.scalar(
        select(Complaint).where(
            Complaint.id == complaint_uuid,
            Complaint.district_id == officer.jurisdiction_id,
        )
    )
    if not complaint:
        raise ComplaintNotInJurisdiction()

    processing_status = await db.scalar(
        select(ComplaintProcessingStatus).where(
            ComplaintProcessingStatus.complaint_id == complaint_uuid
        )
    )
    history_result = await db.scalars(
        select(ComplaintStatusHistory)
        .where(ComplaintStatusHistory.complaint_id == complaint_uuid)
        .order_by(ComplaintStatusHistory.changed_at.asc())
    )
    active_assignment = await db.scalar(
        select(WorkerAssignment).where(
            WorkerAssignment.complaint_id == complaint_uuid,
            WorkerAssignment.is_active == True,  # noqa: E712
        )
    )

    return {
        "complaint": complaint,
        "processing_status": processing_status,
        "history": list(history_result.all()),
        "active_assignment": active_assignment,
    }


# ── Escalation History ───────────────────────────────────────────────────────


async def get_escalations(
    db: AsyncSession,
    officer: Officer,
    resolved: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Escalations received at district level (to_level='district')."""

    base = (
        select(Escalation)
        .join(Complaint, Escalation.complaint_id == Complaint.id)
        .where(
            Escalation.to_level == "district",
            Complaint.district_id == officer.jurisdiction_id,
        )
    )
    count_base = (
        select(func.count())
        .select_from(Escalation)
        .join(Complaint, Escalation.complaint_id == Complaint.id)
        .where(
            Escalation.to_level == "district",
            Complaint.district_id == officer.jurisdiction_id,
        )
    )

    if resolved is True:
        base = base.where(Escalation.resolved_at.isnot(None))
        count_base = count_base.where(Escalation.resolved_at.isnot(None))
    elif resolved is False:
        base = base.where(Escalation.resolved_at.is_(None))
        count_base = count_base.where(Escalation.resolved_at.is_(None))

    total = await db.scalar(count_base)
    offset = (page - 1) * page_size
    result = await db.scalars(
        base.order_by(Escalation.created_at.desc()).offset(offset).limit(page_size)
    )

    return {
        "escalations": list(result.all()),
        "total": total or 0,
        "page": page,
        "page_size": page_size,
    }


# ── Historical Data ──────────────────────────────────────────────────────────


async def get_historical_data(
    db: AsyncSession,
    officer: Officer,
    department_filter: str | None = None,
) -> dict:
    """Query quarterly summaries and recurring patterns for the district.

    This reads existing materialized view / table data.
    The actual intelligence processing (HDBSCAN, pattern detection) is deferred.
    """

    jid = officer.jurisdiction_id

    # Recurring issue patterns for jurisdictions within this district
    pattern_stmt = (
        select(RecurringIssuePattern)
        .where(RecurringIssuePattern.is_active == True)  # noqa: E712
    )
    # Filter by jurisdictions in this district via raw SQL subquery
    pattern_stmt = pattern_stmt.where(
        RecurringIssuePattern.jurisdiction_id.in_(
            select(text("id")).select_from(text("jurisdictions")).where(
                text("id = :jid OR parent_id = :jid OR parent_id IN (SELECT id FROM jurisdictions WHERE parent_id = :jid)")
            )
        )
    )

    if department_filter:
        dept = await db.scalar(
            select(Department).where(Department.code == department_filter)
        )
        if dept:
            pattern_stmt = pattern_stmt.where(
                RecurringIssuePattern.department_id == dept.id
            )

    # Use raw SQL for the recursive jurisdiction + pattern query for reliability
    patterns_result = await db.execute(
        text("""
            SELECT rip.* FROM recurring_issue_patterns rip
            WHERE rip.is_active = true
              AND rip.jurisdiction_id IN (
                  SELECT id FROM jurisdictions
                  WHERE id = :jid
                     OR parent_id = :jid
                     OR parent_id IN (SELECT id FROM jurisdictions WHERE parent_id = :jid)
              )
            ORDER BY rip.recurrence_count DESC
            LIMIT 50
        """),
        {"jid": jid},
    )
    patterns = [dict(row._mapping) for row in patterns_result]

    # Quarterly complaint summary from materialized view
    quarterly_result = await db.execute(
        text("""
            SELECT * FROM mv_quarterly_complaint_summary
            WHERE district_id = :jid
            ORDER BY quarter_start DESC
            LIMIT 100
        """),
        {"jid": jid},
    )
    quarterly = [dict(row._mapping) for row in quarterly_result]

    # SLA compliance from materialized view
    sla_result = await db.execute(
        text("""
            SELECT * FROM mv_sla_compliance
            WHERE district_id = :jid
            ORDER BY quarter_start DESC
            LIMIT 100
        """),
        {"jid": jid},
    )
    sla_compliance = [dict(row._mapping) for row in sla_result]

    return {
        "recurring_patterns": patterns,
        "quarterly_summary": quarterly,
        "sla_compliance": sla_compliance,
    }


# ── Dashboard Stats ──────────────────────────────────────────────────────────


async def get_dashboard_stats(db: AsyncSession, officer: Officer) -> dict:
    """Aggregate stats across the entire district."""

    jid = officer.jurisdiction_id

    status_counts_result = await db.execute(
        text("""
            SELECT status, COUNT(*) as count
            FROM complaints
            WHERE district_id = :jid
            GROUP BY status
        """),
        {"jid": jid},
    )
    status_counts = {row.status: row.count for row in status_counts_result}

    pending_review = await db.scalar(
        select(func.count()).select_from(Complaint).where(
            Complaint.district_id == jid,
            Complaint.current_review_level == "district",
            Complaint.status.in_(["submitted", "waiting", "reopened", "escalated"]),
        )
    )

    pending_escalations = await db.scalar(
        select(func.count())
        .select_from(Escalation)
        .join(Complaint, Escalation.complaint_id == Complaint.id)
        .where(
            Escalation.to_level == "district",
            Complaint.district_id == jid,
            Escalation.resolved_at.is_(None),
        )
    )

    sla_breaches = await db.scalar(
        text("""
            SELECT COUNT(*) FROM sla_trackers st
            JOIN worker_assignments wa ON st.worker_assignment_id = wa.id
            JOIN complaints c ON wa.complaint_id = c.id
            WHERE c.district_id = :jid
              AND st.breached = true
              AND st.resolved_at IS NULL
        """),
        {"jid": jid},
    )

    return {
        "status_counts": status_counts,
        "pending_review": pending_review or 0,
        "pending_escalations": pending_escalations or 0,
        "active_sla_breaches": sla_breaches or 0,
        "total_complaints": sum(status_counts.values()) if status_counts else 0,
    }
