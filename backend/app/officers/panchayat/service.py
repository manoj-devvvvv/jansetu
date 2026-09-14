import csv
import io
import uuid as _uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, text

from app.config.security import hash_mobile, hash_worker_pin
from app.models.complaint import Complaint, ComplaintStatusHistory, ComplaintProcessingStatus
from app.models.jurisdiction import Department
from app.models.officer import Officer
from app.models.worker import Worker, WorkerAssignment, WorkerBulkUpload, WorkerScoreHistory
from app.models.sla import SlaTracker


# ── Exceptions ───────────────────────────────────────────────────────────────


class ComplaintNotInJurisdiction(Exception):
    def __init__(self) -> None:
        super().__init__("Complaint not in officer's panchayat")


class WorkerNotFound(Exception):
    def __init__(self) -> None:
        super().__init__("Worker not found")


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
    """Paginated complaint queue for this officer's panchayat — oldest first (FIFO)."""

    base = select(Complaint).where(
        Complaint.panchayat_id == officer.jurisdiction_id,
        Complaint.current_review_level == "panchayat",
    )
    count_base = select(func.count()).select_from(Complaint).where(
        Complaint.panchayat_id == officer.jurisdiction_id,
        Complaint.current_review_level == "panchayat",
    )

    if status_filter:
        base = base.where(Complaint.status == status_filter)
        count_base = count_base.where(Complaint.status == status_filter)

    if department_filter:
        # Look up department by code
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

    return {"complaints": list(result.all()), "total": total or 0, "page": page, "page_size": page_size}


# ── Complaint Detail ─────────────────────────────────────────────────────────


async def get_complaint_detail(
    db: AsyncSession, officer: Officer, complaint_id: str
) -> dict:
    """Single complaint detail with history, processing status, and active assignment."""

    try:
        complaint_uuid = _uuid.UUID(complaint_id)
    except ValueError:
        raise ComplaintNotInJurisdiction()

    complaint = await db.scalar(
        select(Complaint).where(
            Complaint.id == complaint_uuid,
            Complaint.panchayat_id == officer.jurisdiction_id,
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


# ── Worker Management ────────────────────────────────────────────────────────


async def list_workers(
    db: AsyncSession,
    officer: Officer,
    department_filter: str | None = None,
    status_filter: str | None = None,
) -> list[Worker]:
    """List all workers in the officer's panchayat."""

    stmt = select(Worker).where(
        Worker.jurisdiction_id == officer.jurisdiction_id,
        Worker.is_active == True,  # noqa: E712
    )

    if department_filter:
        dept = await db.scalar(
            select(Department).where(Department.code == department_filter)
        )
        if dept:
            stmt = stmt.where(Worker.department_id == dept.id)

    if status_filter:
        stmt = stmt.where(Worker.profile_status == status_filter)

    stmt = stmt.order_by(Worker.full_name.asc())
    result = await db.scalars(stmt)
    return list(result.all())


async def get_worker_detail(
    db: AsyncSession, officer: Officer, worker_id: str
) -> dict:
    """Worker detail with score history and active assignments."""

    try:
        worker_uuid = _uuid.UUID(worker_id)
    except ValueError:
        raise WorkerNotFound()

    worker = await db.scalar(
        select(Worker).where(
            Worker.id == worker_uuid,
            Worker.jurisdiction_id == officer.jurisdiction_id,
        )
    )
    if not worker:
        raise WorkerNotFound()

    score_history = await db.scalars(
        select(WorkerScoreHistory)
        .where(WorkerScoreHistory.worker_id == worker_uuid)
        .order_by(WorkerScoreHistory.created_at.desc())
        .limit(50)
    )

    active_assignments = await db.scalars(
        select(WorkerAssignment).where(
            WorkerAssignment.worker_id == worker_uuid,
            WorkerAssignment.is_active == True,  # noqa: E712
        )
    )

    return {
        "worker": worker,
        "score_history": list(score_history.all()),
        "active_assignments": list(active_assignments.all()),
    }


async def register_worker(
    db: AsyncSession,
    officer: Officer,
    phone: str,
    pin: str,
    full_name: str,
    department_id: str,
    preferred_language: str = "en",
) -> Worker:
    """Register a single worker in the officer's panchayat."""

    mobile_hash = hash_mobile(phone)

    # Check for duplicate
    existing = await db.scalar(
        select(Worker).where(Worker.mobile_hash == mobile_hash)
    )
    if existing:
        raise InvalidInput("A worker with this phone number already exists")

    # Validate department
    try:
        dept_uuid = _uuid.UUID(department_id)
    except ValueError:
        raise InvalidInput("Invalid department_id")

    dept = await db.scalar(select(Department).where(Department.id == dept_uuid))
    if not dept:
        raise InvalidInput("Department not found")

    worker = Worker(
        mobile_hash=mobile_hash,
        login_pin_hash=hash_worker_pin(pin),
        full_name=full_name,
        department_id=dept.id,
        jurisdiction_id=officer.jurisdiction_id,
        preferred_language=preferred_language,
        created_by_officer_id=officer.id,
    )
    db.add(worker)
    await db.flush()
    await db.refresh(worker)
    return worker


async def bulk_upload_workers(
    db: AsyncSession,
    officer: Officer,
    file_name: str,
    file_bytes: bytes,
) -> WorkerBulkUpload:
    """Process a CSV file to bulk-register workers.

    Expected columns: full_name, phone, pin, department_code, preferred_language (optional)
    """

    try:
        text_content = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InvalidInput("CSV file must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text_content))

    required_cols = {"full_name", "phone", "pin", "department_code"}
    if not required_cols.issubset(set(reader.fieldnames or [])):
        raise InvalidInput(
            f"CSV must have columns: {', '.join(sorted(required_cols))}"
        )

    # Pre-load departments by code for fast lookup
    dept_result = await db.scalars(select(Department))
    dept_map: dict[str, _uuid.UUID] = {d.code: d.id for d in dept_result.all()}

    rows = list(reader)
    total_rows = len(rows)
    success_count = 0
    failed_count = 0
    error_report: list[dict] = []

    for row_num, row in enumerate(rows, start=1):
        try:
            f_name = (row.get("full_name") or "").strip()
            phone = (row.get("phone") or "").strip()
            pin = (row.get("pin") or "").strip()
            dept_code = (row.get("department_code") or "").strip()
            lang = (row.get("preferred_language") or "en").strip()

            if not f_name or not phone or not pin or not dept_code:
                raise ValueError("Missing required field")

            if dept_code not in dept_map:
                raise ValueError(f"Unknown department_code '{dept_code}'")

            mobile_hash = hash_mobile(phone)

            existing = await db.scalar(
                select(Worker).where(Worker.mobile_hash == mobile_hash)
            )
            if existing:
                raise ValueError("Duplicate phone number")

            worker = Worker(
                mobile_hash=mobile_hash,
                login_pin_hash=hash_worker_pin(pin),
                full_name=f_name,
                department_id=dept_map[dept_code],
                jurisdiction_id=officer.jurisdiction_id,
                preferred_language=lang,
                created_by_officer_id=officer.id,
            )
            db.add(worker)
            success_count += 1

        except (ValueError, KeyError) as e:
            failed_count += 1
            error_report.append({"row": row_num, "error": str(e)})

    upload_record = WorkerBulkUpload(
        officer_id=officer.id,
        jurisdiction_id=officer.jurisdiction_id,
        file_name=file_name,
        total_rows=total_rows,
        success_count=success_count,
        failed_count=failed_count,
        error_report=error_report,
    )
    db.add(upload_record)
    await db.flush()
    await db.refresh(upload_record)
    return upload_record


# ── Dashboard Stats ──────────────────────────────────────────────────────────


async def get_dashboard_stats(db: AsyncSession, officer: Officer) -> dict:
    """Aggregate stats for the officer's panchayat dashboard."""

    jurisdiction_id = officer.jurisdiction_id

    # Complaint counts by status
    status_counts_result = await db.execute(
        text("""
            SELECT status, COUNT(*) as count
            FROM complaints
            WHERE panchayat_id = :jid
            GROUP BY status
        """),
        {"jid": jurisdiction_id},
    )
    status_counts = {row.status: row.count for row in status_counts_result}

    # Pending review (current_review_level = panchayat AND actionable statuses)
    pending_review = await db.scalar(
        select(func.count()).select_from(Complaint).where(
            Complaint.panchayat_id == jurisdiction_id,
            Complaint.current_review_level == "panchayat",
            Complaint.status.in_(["submitted", "waiting", "reopened"]),
        )
    )

    # Active workers count
    active_workers = await db.scalar(
        select(func.count()).select_from(Worker).where(
            Worker.jurisdiction_id == jurisdiction_id,
            Worker.is_active == True,  # noqa: E712
        )
    )

    # SLA breach count (unresolved breaches for worker assignments in this panchayat)
    sla_breaches = await db.scalar(
        text("""
            SELECT COUNT(*) FROM sla_trackers st
            JOIN worker_assignments wa ON st.worker_assignment_id = wa.id
            JOIN complaints c ON wa.complaint_id = c.id
            WHERE c.panchayat_id = :jid
              AND st.breached = true
              AND st.resolved_at IS NULL
        """),
        {"jid": jurisdiction_id},
    )

    return {
        "status_counts": status_counts,
        "pending_review": pending_review or 0,
        "active_workers": active_workers or 0,
        "active_sla_breaches": sla_breaches or 0,
        "total_complaints": sum(status_counts.values()) if status_counts else 0,
    }
