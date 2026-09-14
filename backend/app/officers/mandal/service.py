import uuid as _uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, text

from app.models.complaint import Complaint, ComplaintStatusHistory, ComplaintProcessingStatus
from app.models.jurisdiction import Department
from app.models.officer import Officer
from app.models.worker import WorkerAssignment
from app.models.sla import Escalation, SlaTracker


# ── Exceptions ───────────────────────────────────────────────────────────────


class ComplaintNotInJurisdiction(Exception):
    def __init__(self) -> None:
        super().__init__("Complaint not in officer's mandal")


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
    """Paginated complaint queue for this mandal — complaints at mandal review level."""

    base = select(Complaint).where(
        Complaint.mandal_id == officer.jurisdiction_id,
        Complaint.current_review_level == "mandal",
    )
    count_base = select(func.count()).select_from(Complaint).where(
        Complaint.mandal_id == officer.jurisdiction_id,
        Complaint.current_review_level == "mandal",
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
    """Single complaint detail — must be in this mandal's jurisdiction."""

    try:
        complaint_uuid = _uuid.UUID(complaint_id)
    except ValueError:
        raise ComplaintNotInJurisdiction()

    complaint = await db.scalar(
        select(Complaint).where(
            Complaint.id == complaint_uuid,
            Complaint.mandal_id == officer.jurisdiction_id,
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
    """Escalations received at mandal level (to_level='mandal')."""

    base = (
        select(Escalation)
        .join(Complaint, Escalation.complaint_id == Complaint.id)
        .where(
            Escalation.to_level == "mandal",
            Complaint.mandal_id == officer.jurisdiction_id,
        )
    )
    count_base = (
        select(func.count())
        .select_from(Escalation)
        .join(Complaint, Escalation.complaint_id == Complaint.id)
        .where(
            Escalation.to_level == "mandal",
            Complaint.mandal_id == officer.jurisdiction_id,
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


# ── Dashboard Stats ──────────────────────────────────────────────────────────


async def get_dashboard_stats(db: AsyncSession, officer: Officer) -> dict:
    """Aggregate stats across all panchayats in this mandal."""

    jid = officer.jurisdiction_id

    status_counts_result = await db.execute(
        text("""
            SELECT status, COUNT(*) as count
            FROM complaints
            WHERE mandal_id = :jid
            GROUP BY status
        """),
        {"jid": jid},
    )
    status_counts = {row.status: row.count for row in status_counts_result}

    pending_review = await db.scalar(
        select(func.count()).select_from(Complaint).where(
            Complaint.mandal_id == jid,
            Complaint.current_review_level == "mandal",
            Complaint.status.in_(["submitted", "waiting", "reopened", "escalated"]),
        )
    )

    pending_escalations = await db.scalar(
        select(func.count())
        .select_from(Escalation)
        .join(Complaint, Escalation.complaint_id == Complaint.id)
        .where(
            Escalation.to_level == "mandal",
            Complaint.mandal_id == jid,
            Escalation.resolved_at.is_(None),
        )
    )

    sla_breaches = await db.scalar(
        text("""
            SELECT COUNT(*) FROM sla_trackers st
            JOIN worker_assignments wa ON st.worker_assignment_id = wa.id
            JOIN complaints c ON wa.complaint_id = c.id
            WHERE c.mandal_id = :jid
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
