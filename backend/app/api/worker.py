from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
import uuid

from app.db.session import get_db
from app.models.worker import Worker
from app.auth.worker_auth import get_current_worker
from app.schemas.worker import (
    WorkerRead,
    WorkerAssignmentRead,
    WorkerExcuseCreate,
    WorkerExcuseRead,
)
from app.workers.service import (
    login_worker,
    get_assignments,
    get_assignment_detail,
    accept_assignment,
    reject_assignment,
    request_excuse,
    arrive_at_assignment,
    complete_assignment,
    InvalidCredentials,
    AssignmentNotFound,
    InvalidAction,
)

from app.config.rate_limit import login_rate_limit

router = APIRouter()

# ── Schemas ──────────────────────────────────────────────────────────────────

class WorkerLoginRequest(BaseModel):
    phone: str
    pin: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class RejectRequest(BaseModel):
    reason: str

# ── Auth & Profile ───────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse, dependencies=[Depends(login_rate_limit)])
async def login(
    body: WorkerLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Worker login to receive a JWT."""
    try:
        token = await login_worker(db, body.phone, body.pin)
        return {"access_token": token}
    except InvalidCredentials as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@router.get("/me", response_model=WorkerRead)
async def get_profile(
    worker: Worker = Depends(get_current_worker),
):
    """Get current worker profile."""
    return WorkerRead.model_validate(worker)

# ── Assignments ──────────────────────────────────────────────────────────────

@router.get("/assignments")
async def list_assignments(
    status_filter: Optional[str] = Query(None, alias="status"),
    worker: Worker = Depends(get_current_worker),
    db: AsyncSession = Depends(get_db),
):
    """List worker's assignments."""
    assignments = await get_assignments(db, worker.id, status_filter)
    return [WorkerAssignmentRead.model_validate(a) for a in assignments]


@router.get("/assignments/{assignment_id}")
async def assignment_detail(
    assignment_id: str,
    worker: Worker = Depends(get_current_worker),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed view of a specific assignment."""
    try:
        detail = await get_assignment_detail(db, worker.id, assignment_id)
        # Assuming we might want to return complaint ID/info along with assignment
        # For simplicity, returning just the AssignmentRead and embedding complaint_id
        # In a real app we'd build a detailed response model
        res = WorkerAssignmentRead.model_validate(detail["assignment"]).model_dump()
        res["complaint"] = {
            "id": str(detail["complaint"].id),
            "status": detail["complaint"].status,
            "category_id": detail["complaint"].category_id,
            "department_id": str(detail["complaint"].department_id),
            "location": detail["complaint"].location,
            "raw_text": detail["complaint"].raw_text,
            "voice_audio_url": detail["complaint"].voice_audio_url,
            "image_url": detail["complaint"].image_url,
        }
        return res
    except AssignmentNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")


@router.post("/assignments/{assignment_id}/accept", response_model=WorkerAssignmentRead)
async def accept_task(
    assignment_id: str,
    worker: Worker = Depends(get_current_worker),
    db: AsyncSession = Depends(get_db),
):
    try:
        assignment = await accept_assignment(db, worker.id, assignment_id)
        await db.commit()
        await db.refresh(assignment)
        return WorkerAssignmentRead.model_validate(assignment)
    except AssignmentNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    except InvalidAction as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/assignments/{assignment_id}/reject", response_model=WorkerAssignmentRead)
async def reject_task(
    assignment_id: str,
    body: RejectRequest,
    worker: Worker = Depends(get_current_worker),
    db: AsyncSession = Depends(get_db),
):
    try:
        assignment = await reject_assignment(db, worker.id, assignment_id, body.reason)
        await db.commit()
        await db.refresh(assignment)
        return WorkerAssignmentRead.model_validate(assignment)
    except AssignmentNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    except InvalidAction as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/assignments/{assignment_id}/excuse", response_model=WorkerExcuseRead)
async def excuse_task(
    assignment_id: str,
    body: WorkerExcuseCreate,
    worker: Worker = Depends(get_current_worker),
    db: AsyncSession = Depends(get_db),
):
    if body.worker_assignment_id != assignment_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID mismatch")
    
    try:
        excuse = await request_excuse(
            db, worker.id, assignment_id, body.reason_text, body.reason_audio_url
        )
        await db.commit()
        await db.refresh(excuse)
        return WorkerExcuseRead.model_validate(excuse)
    except AssignmentNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    except InvalidAction as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/assignments/{assignment_id}/arrive", response_model=WorkerAssignmentRead)
async def arrive_task(
    assignment_id: str,
    photo: UploadFile = File(...),
    lat: float = Form(...),
    lon: float = Form(...),
    worker: Worker = Depends(get_current_worker),
    db: AsyncSession = Depends(get_db),
):
    if not photo.filename or not (photo.filename.lower().endswith(".jpg") or photo.filename.lower().endswith(".jpeg")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Photo must be a .jpg or .jpeg file")
    
    photo_bytes = await photo.read()
    
    try:
        assignment = await arrive_at_assignment(db, worker.id, assignment_id, photo_bytes, lat, lon)
        await db.commit()
        await db.refresh(assignment)
        return WorkerAssignmentRead.model_validate(assignment)
    except AssignmentNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    except InvalidAction as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/assignments/{assignment_id}/complete", response_model=WorkerAssignmentRead)
async def complete_task(
    assignment_id: str,
    photo: UploadFile = File(...),
    lat: float = Form(...),
    lon: float = Form(...),
    worker: Worker = Depends(get_current_worker),
    db: AsyncSession = Depends(get_db),
):
    if not photo.filename or not (photo.filename.lower().endswith(".jpg") or photo.filename.lower().endswith(".jpeg")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Photo must be a .jpg or .jpeg file")
        
    photo_bytes = await photo.read()
    
    try:
        assignment = await complete_assignment(db, worker.id, assignment_id, photo_bytes, lat, lon)
        await db.commit()
        await db.refresh(assignment)
        return WorkerAssignmentRead.model_validate(assignment)
    except AssignmentNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    except InvalidAction as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
