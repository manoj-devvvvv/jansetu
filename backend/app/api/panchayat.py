from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.auth.officer_auth import get_current_officer
from app.models.officer import Officer
from app.officers.shared.verify_service import (
    perform_verification_action,
    ComplaintNotFound as VerifyComplaintNotFound,
    OfficerNotAuthorized,
    InvalidAction,
)
from app.officers.panchayat.service import (
    get_complaint_queue,
    get_complaint_detail,
    list_workers,
    get_worker_detail,
    register_worker,
    bulk_upload_workers,
    get_dashboard_stats,
    ComplaintNotInJurisdiction,
    WorkerNotFound,
    InvalidInput,
)
from app.core.sla.assign_worker import NoWorkerAvailable
from app.schemas.complaint import ComplaintRead, ComplaintProcessingStatusRead, ComplaintStatusHistoryRead
from app.schemas.worker import WorkerRead, WorkerAssignmentRead, WorkerScoreHistoryRead
from app.schemas.officer import VerificationActionCreate
from typing import Optional
from pydantic import BaseModel

router = APIRouter()


# ── Request schemas (not in app/schemas because these are route-level) ───────


class WorkerRegisterRequest(BaseModel):
    phone: str
    pin: str
    full_name: str
    department_id: str
    preferred_language: Optional[str] = "en"


# ── Guards ───────────────────────────────────────────────────────────────────


def _require_panchayat(officer: Officer) -> None:
    if officer.level != "panchayat":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only panchayat-level officers can access this endpoint",
        )


# ── Dashboard ────────────────────────────────────────────────────────────────


@router.get("/dashboard")
async def dashboard(
    officer: Officer = Depends(get_current_officer),
    db: AsyncSession = Depends(get_db),
):
    _require_panchayat(officer)
    stats = await get_dashboard_stats(db, officer)
    return stats


# ── Complaints ───────────────────────────────────────────────────────────────


@router.get("/complaints")
async def complaints_queue(
    status_filter: Optional[str] = Query(None, alias="status"),
    department: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    officer: Officer = Depends(get_current_officer),
    db: AsyncSession = Depends(get_db),
):
    _require_panchayat(officer)
    result = await get_complaint_queue(
        db, officer, status_filter=status_filter,
        department_filter=department, page=page, page_size=page_size,
    )
    return {
        "complaints": [ComplaintRead.model_validate(c) for c in result["complaints"]],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    }


@router.get("/complaints/{complaint_id}")
async def complaint_detail(
    complaint_id: str,
    officer: Officer = Depends(get_current_officer),
    db: AsyncSession = Depends(get_db),
):
    _require_panchayat(officer)
    try:
        detail = await get_complaint_detail(db, officer, complaint_id)
    except ComplaintNotInJurisdiction as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return {
        "complaint": ComplaintRead.model_validate(detail["complaint"]),
        "processing_status": (
            ComplaintProcessingStatusRead.model_validate(detail["processing_status"])
            if detail["processing_status"]
            else None
        ),
        "history": [
            ComplaintStatusHistoryRead.model_validate(h) for h in detail["history"]
        ],
        "active_assignment": (
            WorkerAssignmentRead.model_validate(detail["active_assignment"])
            if detail["active_assignment"]
            else None
        ),
    }


@router.post("/complaints/{complaint_id}/action")
async def complaint_action(
    complaint_id: str,
    body: VerificationActionCreate,
    officer: Officer = Depends(get_current_officer),
    db: AsyncSession = Depends(get_db),
):
    _require_panchayat(officer)
    try:
        result = await perform_verification_action(
            db, officer, complaint_id, body.action_type, body.reason,
        )
        await db.commit()
        return result
    except VerifyComplaintNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OfficerNotAuthorized as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except InvalidAction as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except NoWorkerAvailable as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


# ── Workers ──────────────────────────────────────────────────────────────────


@router.get("/workers")
async def workers_list(
    department: Optional[str] = Query(None),
    worker_status: Optional[str] = Query(None, alias="status"),
    officer: Officer = Depends(get_current_officer),
    db: AsyncSession = Depends(get_db),
):
    _require_panchayat(officer)
    workers = await list_workers(db, officer, department_filter=department, status_filter=worker_status)
    return [WorkerRead.model_validate(w) for w in workers]


@router.get("/workers/{worker_id}")
async def worker_detail(
    worker_id: str,
    officer: Officer = Depends(get_current_officer),
    db: AsyncSession = Depends(get_db),
):
    _require_panchayat(officer)
    try:
        detail = await get_worker_detail(db, officer, worker_id)
    except WorkerNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return {
        "worker": WorkerRead.model_validate(detail["worker"]),
        "score_history": [
            WorkerScoreHistoryRead.model_validate(s) for s in detail["score_history"]
        ],
        "active_assignments": [
            WorkerAssignmentRead.model_validate(a)
            for a in detail["active_assignments"]
        ],
    }


@router.post("/workers", response_model=WorkerRead)
async def worker_register(
    body: WorkerRegisterRequest,
    officer: Officer = Depends(get_current_officer),
    db: AsyncSession = Depends(get_db),
):
    _require_panchayat(officer)
    try:
        worker = await register_worker(
            db, officer,
            phone=body.phone,
            pin=body.pin,
            full_name=body.full_name,
            department_id=body.department_id,
            preferred_language=body.preferred_language or "en",
        )
        await db.commit()
        await db.refresh(worker)
        return WorkerRead.model_validate(worker)
    except InvalidInput as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/workers/bulk-upload")
async def worker_bulk_upload(
    file: UploadFile = File(...),
    officer: Officer = Depends(get_current_officer),
    db: AsyncSession = Depends(get_db),
):
    _require_panchayat(officer)

    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a .csv file",
        )

    file_bytes = await file.read()

    try:
        upload_record = await bulk_upload_workers(
            db, officer, file_name=file.filename, file_bytes=file_bytes,
        )
        await db.commit()
        await db.refresh(upload_record)
        return {
            "id": str(upload_record.id),
            "file_name": upload_record.file_name,
            "total_rows": upload_record.total_rows,
            "success_count": upload_record.success_count,
            "failed_count": upload_record.failed_count,
            "error_report": upload_record.error_report,
        }
    except InvalidInput as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
