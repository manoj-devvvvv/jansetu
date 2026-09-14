from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import supabase
from app.config.security import hash_mobile
from app.core.location.jurisdiction_lookup import lookup_jurisdiction
from app.models.complaint import Complaint, Citizen, ComplaintStatusHistory, ComplaintProcessingStatus
from app.models.jurisdiction import Department
from app.models.master_issue import ClosureVerification
from sqlalchemy import select
from datetime import datetime, timezone
import uuid


# ── Custom exceptions for precise HTTP status mapping ────────────────────────


class CitizenBlocked(Exception):
    """Citizen's account has been blocked."""
    pass


class CitizenNotFound(Exception):
    """No citizen record matches the given phone hash."""

    def __init__(self) -> None:
        super().__init__("Citizen not found")


class ComplaintNotFound(Exception):
    """Complaint does not exist or doesn't belong to this citizen."""

    def __init__(self) -> None:
        super().__init__("Complaint not found")


class InvalidInput(Exception):
    """Generic bad-request: invalid department, mode, location, etc."""
    pass


class ClosureExpired(Exception):
    """The 24-hour citizen verification window has elapsed."""

    def __init__(self) -> None:
        super().__init__("Closure verification deadline has expired")


# ── Service functions ────────────────────────────────────────────────────────


async def create_complaint(
    db: AsyncSession,
    phone: str,
    department_code: str,
    input_mode: str,
    latitude: float,
    longitude: float,
    image_bytes: bytes,
    image_filename: str,
    image_content_type: str,
    voice_bytes: bytes | None,
    voice_filename: str | None,
    voice_content_type: str | None,
    raw_text: str | None,
    preferred_language: str,
    submitter_ip: str,
) -> Complaint:
    """Create a new citizen complaint with file uploads and jurisdiction resolution."""

    if input_mode not in ("text", "voice"):
        raise InvalidInput("input_mode must be 'text' or 'voice'")

    if input_mode == "text" and not raw_text:
        raise InvalidInput("raw_text is required for text mode")

    if input_mode == "voice" and not voice_bytes:
        raise InvalidInput("voice_audio is required for voice mode")

    mobile_hash = hash_mobile(phone)

    # ── Upsert citizen ───────────────────────────────────────────────────
    citizen = await db.scalar(
        select(Citizen).where(Citizen.mobile_hash == mobile_hash)
    )
    if not citizen:
        citizen = Citizen(mobile_hash=mobile_hash, preferred_language=preferred_language)
        db.add(citizen)
        await db.flush()
    elif citizen.is_blocked:
        raise CitizenBlocked()

    # ── Department lookup ────────────────────────────────────────────────
    dept = await db.scalar(
        select(Department).where(Department.code == department_code)
    )
    if not dept:
        raise InvalidInput(
            f"Invalid department code '{department_code}'. "
            "Must be one of: water, drainage, roads, electricity, hospital"
        )

    # ── Jurisdiction resolution via PostGIS ───────────────────────────────
    jurisdictions = await lookup_jurisdiction(db, lng=longitude, lat=latitude)
    if not jurisdictions:
        raise InvalidInput("Location is outside the service area")

    # ── Upload image to Supabase Storage ─────────────────────────────────
    image_path = f"{uuid.uuid4()}-{image_filename}"
    await run_in_threadpool(
        supabase.storage.from_("complaint-images").upload,
        image_path,
        image_bytes,
        {"content-type": image_content_type},
    )
    image_url = supabase.storage.from_("complaint-images").get_public_url(image_path)

    # ── Upload voice audio (if voice mode) ───────────────────────────────
    voice_audio_url = None
    if input_mode == "voice" and voice_bytes:
        audio_path = f"{uuid.uuid4()}-{voice_filename}"
        await run_in_threadpool(
            supabase.storage.from_("complaint-audio").upload,
            audio_path,
            voice_bytes,
            {"content-type": voice_content_type},
        )
        voice_audio_url = supabase.storage.from_("complaint-audio").get_public_url(
            audio_path
        )

    # ── Create complaint row ─────────────────────────────────────────────
    # DB triggers will automatically:
    #   - Validate jurisdiction chain (panchayat→mandal→district)
    #   - Bump citizens.total_complaints_filed
    #   - Create complaint_processing_status row
    #   - Log initial status to complaint_status_history
    new_complaint = Complaint(
        citizen_id=citizen.id,
        department_id=dept.id,
        panchayat_id=jurisdictions["panchayat_id"],
        mandal_id=jurisdictions["mandal_id"],
        district_id=jurisdictions["district_id"],
        location=f"SRID=4326;POINT({longitude} {latitude})",
        input_mode=input_mode,
        voice_audio_url=voice_audio_url,
        raw_text=raw_text,
        image_url=image_url,
        submitter_ip=submitter_ip,
        status="submitted",
    )

    db.add(new_complaint)
    await db.commit()
    await db.refresh(new_complaint)

    # ── Trigger clustering pipeline (async via Celery) ────────────────
    # This runs embedding generation + master issue clustering in background.
    # Must be AFTER commit so the complaint row exists in DB for the worker.
    try:
        from app.tasks.complaint_tasks import process_complaint_clustering
        process_complaint_clustering.delay(str(new_complaint.id))
    except Exception:
        # Don't block complaint submission if Celery/Redis is down
        pass

    return new_complaint


async def get_citizen_complaints(
    db: AsyncSession, phone: str
) -> list[Complaint]:
    """Return all complaints for a citizen, newest first."""

    mobile_hash = hash_mobile(phone)
    citizen = await db.scalar(
        select(Citizen).where(Citizen.mobile_hash == mobile_hash)
    )
    if not citizen:
        return []

    result = await db.scalars(
        select(Complaint)
        .where(Complaint.citizen_id == citizen.id)
        .order_by(Complaint.created_at.desc())
    )
    return list(result.all())


async def get_complaint_detail(
    db: AsyncSession, phone: str, complaint_id: str
) -> dict:
    """Return a single complaint with its processing status and status history."""

    mobile_hash = hash_mobile(phone)
    citizen = await db.scalar(
        select(Citizen).where(Citizen.mobile_hash == mobile_hash)
    )
    if not citizen:
        raise CitizenNotFound()

    try:
        complaint_uuid = uuid.UUID(complaint_id)
    except ValueError:
        raise ComplaintNotFound()

    complaint = await db.scalar(
        select(Complaint).where(
            Complaint.id == complaint_uuid, Complaint.citizen_id == citizen.id
        )
    )
    if not complaint:
        raise ComplaintNotFound()

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
    history = list(history_result.all())

    return {
        "complaint": complaint,
        "processing_status": processing_status,
        "history": history,
    }


async def verify_closure(
    db: AsyncSession,
    phone: str,
    complaint_id: str,
    confirmed: bool,
    reopen_reason: str | None,
) -> Complaint:
    """
    Process citizen's response to a completed task.

    - confirmed=True  → close the complaint
    - confirmed=False → reopen + red-flag back to officer queue
    """

    mobile_hash = hash_mobile(phone)
    citizen = await db.scalar(
        select(Citizen).where(Citizen.mobile_hash == mobile_hash)
    )
    if not citizen:
        raise CitizenNotFound()

    try:
        complaint_uuid = uuid.UUID(complaint_id)
    except ValueError:
        raise ComplaintNotFound()

    complaint = await db.scalar(
        select(Complaint).where(
            Complaint.id == complaint_uuid, Complaint.citizen_id == citizen.id
        )
    )
    if not complaint:
        raise ComplaintNotFound()

    if complaint.status != "pending_citizen_confirmation":
        raise InvalidInput("Complaint is not pending closure confirmation")

    # Fetch the active (pending) closure verification — the one that hasn't
    # been confirmed or reopened yet. A complaint may have multiple over its
    # lifetime if it was previously reopened and re-assigned.
    closure_verif = await db.scalar(
        select(ClosureVerification)
        .where(
            ClosureVerification.complaint_id == complaint_uuid,
            ClosureVerification.citizen_confirmed == False,  # noqa: E712
            ClosureVerification.reopened == False,  # noqa: E712
        )
        .order_by(ClosureVerification.created_at.desc())
    )
    if not closure_verif:
        raise ComplaintNotFound()

    # ── Check 24-hour verification deadline ──────────────────────────────
    now_utc = datetime.now(timezone.utc)
    if closure_verif.verification_due_at is not None:
        due_at = closure_verif.verification_due_at
        # Ensure timezone-aware comparison
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        if now_utc > due_at:
            raise ClosureExpired()

    # ── Apply citizen decision ───────────────────────────────────────────
    if confirmed:
        closure_verif.citizen_confirmed = True
        closure_verif.citizen_confirmed_at = now_utc
        complaint.status = "closed"
        complaint.closed_at = now_utc
    else:
        if not reopen_reason:
            raise InvalidInput("reopen_reason is required when rejecting closure")
        closure_verif.reopened = True
        closure_verif.reopened_at = now_utc
        closure_verif.reopen_reason = reopen_reason
        closure_verif.red_flagged = True
        complaint.status = "reopened"

    await db.commit()
    await db.refresh(complaint)
    return complaint
