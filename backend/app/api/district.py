from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from app.officers.district.service import (
    get_complaint_queue,
    get_complaint_detail,
    get_escalations,
    get_historical_data,
    get_dashboard_stats,
    ComplaintNotInJurisdiction,
)
from app.core.sla.assign_worker import NoWorkerAvailable
from app.schemas.complaint import ComplaintRead, ComplaintProcessingStatusRead, ComplaintStatusHistoryRead
from app.schemas.worker import WorkerAssignmentRead
from app.schemas.officer import VerificationActionCreate, EscalationRead
from typing import Optional

router = APIRouter()


# ── Guards ───────────────────────────────────────────────────────────────────


def _require_district(officer: Officer) -> None:
    if officer.level != "district":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only district-level officers can access this endpoint",
        )


def _block_escalate(action_type: str) -> None:
    """District is the top level — cannot escalate further."""
    if action_type == "escalate":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="District is the highest level — cannot escalate further",
        )


# ── Dashboard ────────────────────────────────────────────────────────────────


@router.get("/dashboard")
async def dashboard(
    officer: Officer = Depends(get_current_officer),
    db: AsyncSession = Depends(get_db),
):
    _require_district(officer)
    return await get_dashboard_stats(db, officer)


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
    _require_district(officer)
    result = await get_complaint_queue(
        db, officer,
        status_filter=status_filter,
        department_filter=department,
        page=page,
        page_size=page_size,
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
    _require_district(officer)
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
    _require_district(officer)
    _block_escalate(body.action_type)

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


# ── Escalations ──────────────────────────────────────────────────────────────


@router.get("/escalations")
async def escalation_list(
    resolved: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    officer: Officer = Depends(get_current_officer),
    db: AsyncSession = Depends(get_db),
):
    _require_district(officer)
    result = await get_escalations(
        db, officer, resolved=resolved, page=page, page_size=page_size,
    )
    return {
        "escalations": [
            EscalationRead.model_validate(e) for e in result["escalations"]
        ],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    }


# ── Historical Data ──────────────────────────────────────────────────────────


@router.get("/historical-data")
async def historical_data(
    department: Optional[str] = Query(None),
    officer: Officer = Depends(get_current_officer),
    db: AsyncSession = Depends(get_db),
):
    _require_district(officer)
    return await get_historical_data(db, officer, department_filter=department)
