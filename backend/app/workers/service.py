import uuid as _uuid
from typing import BinaryIO
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
import time

from app.models.worker import Worker, WorkerAssignment, WorkerExcuse
from app.models.complaint import Complaint
from app.models.sla import SlaTracker
from app.config.security import hash_mobile, verify_worker_pin
from app.auth.worker_auth import create_worker_token
from app.db.session import supabase
from starlette.concurrency import run_in_threadpool


class InvalidCredentials(Exception):
    pass

class AssignmentNotFound(Exception):
    pass

class InvalidAction(Exception):
    pass


async def login_worker(db: AsyncSession, phone: str, pin: str) -> str:
    """Verifies phone and PIN, returns JWT token."""
    mobile_hash = hash_mobile(phone)
    result = await db.execute(
        select(Worker).where(Worker.mobile_hash == mobile_hash, Worker.is_active == True)
    )
    worker = result.scalar_one_or_none()

    if not worker:
        raise InvalidCredentials("Invalid phone number or PIN")

    if not verify_worker_pin(pin, worker.login_pin_hash):
        raise InvalidCredentials("Invalid phone number or PIN")

    return create_worker_token(str(worker.id))


async def get_assignments(
    db: AsyncSession, worker_id: _uuid.UUID, status_filter: str | None = None
) -> list[WorkerAssignment]:
    """Returns a list of worker's assignments."""
    stmt = select(WorkerAssignment).where(WorkerAssignment.worker_id == worker_id)
    if status_filter:
        stmt = stmt.where(WorkerAssignment.status == status_filter)
    
    stmt = stmt.order_by(WorkerAssignment.assigned_at.desc())
    result = await db.scalars(stmt)
    return list(result.all())


async def get_assignment_detail(
    db: AsyncSession, worker_id: _uuid.UUID, assignment_id: str
) -> dict:
    """Returns the assignment detail along with its complaint."""
    try:
        assignment_uuid = _uuid.UUID(assignment_id)
    except ValueError:
        raise AssignmentNotFound()

    assignment = await db.scalar(
        select(WorkerAssignment).where(
            WorkerAssignment.id == assignment_uuid,
            WorkerAssignment.worker_id == worker_id,
        )
    )
    if not assignment:
        raise AssignmentNotFound()

    complaint = await db.scalar(
        select(Complaint).where(Complaint.id == assignment.complaint_id)
    )
    
    return {
        "assignment": assignment,
        "complaint": complaint,
    }


async def accept_assignment(
    db: AsyncSession, worker_id: _uuid.UUID, assignment_id: str
) -> WorkerAssignment:
    """Worker accepts an assignment."""
    try:
        assignment_uuid = _uuid.UUID(assignment_id)
    except ValueError:
        raise AssignmentNotFound()

    assignment = await db.scalar(
        select(WorkerAssignment).where(
            WorkerAssignment.id == assignment_uuid,
            WorkerAssignment.worker_id == worker_id,
            WorkerAssignment.is_active == True,
        )
    )
    if not assignment:
        raise AssignmentNotFound()
    
    if assignment.status != 'assigned':
        raise InvalidAction(f"Cannot accept assignment in status '{assignment.status}'")

    assignment.status = 'accepted'
    assignment.accepted_at = func.now()
    
    await db.flush()
    return assignment


async def reject_assignment(
    db: AsyncSession, worker_id: _uuid.UUID, assignment_id: str, reason: str
) -> WorkerAssignment:
    """Worker rejects an assignment."""
    try:
        assignment_uuid = _uuid.UUID(assignment_id)
    except ValueError:
        raise AssignmentNotFound()

    assignment = await db.scalar(
        select(WorkerAssignment).where(
            WorkerAssignment.id == assignment_uuid,
            WorkerAssignment.worker_id == worker_id,
            WorkerAssignment.is_active == True,
        )
    )
    if not assignment:
        raise AssignmentNotFound()

    if assignment.status not in ('assigned', 'accepted'):
        raise InvalidAction(f"Cannot reject assignment in status '{assignment.status}'")

    if not reason.strip():
        raise InvalidAction("Rejection reason is required")

    assignment.status = 'rejected'
    assignment.rejected_at = func.now()
    assignment.rejected_reason = reason.strip()
    
    # Optional: explicitly set is_active=False here, but triggers might also handle it
    assignment.is_active = False

    # Mark the SLA tracker for assignment as resolved (failed/abandoned) since worker rejected it
    # We just update resolved_at. Let triggers handle re-assignment or wait state.
    sla_tracker = await db.scalar(
        select(SlaTracker).where(
            SlaTracker.worker_assignment_id == assignment_uuid,
            SlaTracker.resolved_at.is_(None)
        )
    )
    if sla_tracker:
        sla_tracker.resolved_at = func.now()

    await db.flush()
    return assignment


async def request_excuse(
    db: AsyncSession, worker_id: _uuid.UUID, assignment_id: str, reason_text: str | None, reason_audio_url: str | None
) -> WorkerExcuse:
    """Worker requests an excuse/extension for an assignment."""
    try:
        assignment_uuid = _uuid.UUID(assignment_id)
    except ValueError:
        raise AssignmentNotFound()

    assignment = await db.scalar(
        select(WorkerAssignment).where(
            WorkerAssignment.id == assignment_uuid,
            WorkerAssignment.worker_id == worker_id,
            WorkerAssignment.is_active == True,
        )
    )
    if not assignment:
        raise AssignmentNotFound()
        
    if assignment.status not in ('accepted', 'in_progress'):
        raise InvalidAction(f"Cannot request excuse in status '{assignment.status}'")
        
    if not reason_text and not reason_audio_url:
        raise InvalidAction("Must provide reason text or audio url")
        
    if assignment.excuse_used:
        raise InvalidAction("Excuse already used for this assignment")

    excuse = WorkerExcuse(
        worker_assignment_id=assignment.id,
        reason_text=reason_text,
        reason_audio_url=reason_audio_url,
    )
    db.add(excuse)
    
    assignment.excuse_used = True
    
    # DB triggers will extend the SLA tracker automatically based on 006_sla_excuses
    await db.flush()
    return excuse


async def _upload_to_storage(file_bytes: bytes, file_ext: str, folder: str) -> str:
    """Uploads a file to Supabase Storage and returns the public URL."""
    file_name = f"{folder}/{int(time.time())}_{_uuid.uuid4().hex[:8]}.{file_ext}"
    bucket = "worker-uploads"
    
    await run_in_threadpool(
        supabase.storage.from_(bucket).upload,
        file_name,
        file_bytes,
        {"content-type": "image/jpeg" if file_ext in ('jpg', 'jpeg') else "application/octet-stream"}
    )
    
    url = supabase.storage.from_(bucket).get_public_url(file_name)
    return url


async def arrive_at_assignment(
    db: AsyncSession, worker_id: _uuid.UUID, assignment_id: str, photo_bytes: bytes, lat: float, lon: float
) -> WorkerAssignment:
    """Worker arrives at location."""
    try:
        assignment_uuid = _uuid.UUID(assignment_id)
    except ValueError:
        raise AssignmentNotFound()

    assignment = await db.scalar(
        select(WorkerAssignment).where(
            WorkerAssignment.id == assignment_uuid,
            WorkerAssignment.worker_id == worker_id,
            WorkerAssignment.is_active == True,
        )
    )
    if not assignment:
        raise AssignmentNotFound()

    if assignment.status != 'accepted':
        raise InvalidAction(f"Cannot mark arrived from status '{assignment.status}'")
        
    photo_url = await _upload_to_storage(photo_bytes, "jpg", "arrival")
    
    assignment.status = 'in_progress'
    assignment.arrived_at = func.now()
    assignment.arrival_photo_url = photo_url
    assignment.arrival_location = f"SRID=4326;POINT({lon} {lat})"
    
    # Update the parent complaint status to 'in_progress'
    complaint = await db.scalar(select(Complaint).where(Complaint.id == assignment.complaint_id))
    if complaint:
        complaint.status = 'in_progress'

    await db.flush()
    return assignment


async def complete_assignment(
    db: AsyncSession, worker_id: _uuid.UUID, assignment_id: str, photo_bytes: bytes, lat: float, lon: float
) -> WorkerAssignment:
    """Worker completes assignment."""
    try:
        assignment_uuid = _uuid.UUID(assignment_id)
    except ValueError:
        raise AssignmentNotFound()

    assignment = await db.scalar(
        select(WorkerAssignment).where(
            WorkerAssignment.id == assignment_uuid,
            WorkerAssignment.worker_id == worker_id,
            WorkerAssignment.is_active == True,
        )
    )
    if not assignment:
        raise AssignmentNotFound()

    if assignment.status != 'in_progress':
        raise InvalidAction(f"Cannot complete assignment from status '{assignment.status}'")
        
    photo_url = await _upload_to_storage(photo_bytes, "jpg", "completion")
    
    assignment.status = 'completed'
    assignment.completed_at = func.now()
    assignment.completion_photo_url = photo_url
    assignment.completion_location = f"SRID=4326;POINT({lon} {lat})"
    
    # Resolve any active SLA tracker for this assignment
    sla_tracker = await db.scalar(
        select(SlaTracker).where(
            SlaTracker.worker_assignment_id == assignment_uuid,
            SlaTracker.resolved_at.is_(None)
        )
    )
    if sla_tracker:
        sla_tracker.resolved_at = func.now()
    
    # Update parent complaint to pending citizen confirmation
    complaint = await db.scalar(select(Complaint).where(Complaint.id == assignment.complaint_id))
    if complaint:
        complaint.status = 'pending_citizen_confirmation'

    await db.flush()
    return assignment
