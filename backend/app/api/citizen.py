from fastapi import APIRouter, Depends, UploadFile, Form, File, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.config.rate_limit import complaint_rate_limit, login_rate_limit
from app.schemas.complaint import ComplaintRead, ComplaintProcessingStatusRead, ComplaintStatusHistoryRead
from app.citizens.service import (
    create_complaint as service_create_complaint,
    get_citizen_complaints,
    get_complaint_detail,
    verify_closure as service_verify_closure,
    CitizenBlocked,
    CitizenNotFound,
    ComplaintNotFound,
    InvalidInput,
    ClosureExpired,
)
from typing import Optional
from pydantic import BaseModel, model_validator

router = APIRouter()


class ClosureVerificationPayload(BaseModel):
    phone: str
    confirmed: bool
    reopen_reason: Optional[str] = None

    @model_validator(mode='after')
    def check_reopen_reason(self) -> 'ClosureVerificationPayload':
        if not self.confirmed and not self.reopen_reason:
            raise ValueError('reopen_reason is required if confirmed is false')
        return self


@router.post("/complaints", response_model=ComplaintRead)
async def create_complaint(
    request: Request,
    department: str = Form(...),
    input_mode: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    phone: str = Form(...),
    preferred_language: str = Form("en"),
    raw_text: Optional[str] = Form(None),
    image: UploadFile = File(...),
    voice_audio: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(complaint_rate_limit),
):
    image_bytes = await image.read()
    voice_bytes = await voice_audio.read() if voice_audio else None
    client_ip = request.client.host if request.client else "127.0.0.1"

    try:
        complaint = await service_create_complaint(
            db=db,
            phone=phone,
            department_code=department,
            input_mode=input_mode,
            latitude=latitude,
            longitude=longitude,
            image_bytes=image_bytes,
            image_filename=image.filename or "image.jpg",
            image_content_type=image.content_type or "image/jpeg",
            voice_bytes=voice_bytes,
            voice_filename=voice_audio.filename if voice_audio else None,
            voice_content_type=voice_audio.content_type if voice_audio else None,
            raw_text=raw_text,
            preferred_language=preferred_language,
            submitter_ip=client_ip,
        )
        return ComplaintRead.model_validate(complaint)
    except CitizenBlocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User is blocked"
        )
    except InvalidInput as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )


@router.get("/complaints", response_model=list[ComplaintRead])
async def list_complaints(
    phone: str,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(login_rate_limit),
):
    complaints = await get_citizen_complaints(db, phone)
    return [ComplaintRead.model_validate(c) for c in complaints]


@router.get("/complaints/{complaint_id}")
async def get_complaint(
    complaint_id: str,
    phone: str,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(login_rate_limit),
):
    try:
        detail = await get_complaint_detail(db, phone, complaint_id)
        return {
            "complaint": ComplaintRead.model_validate(detail["complaint"]),
            "processing_status": (
                ComplaintProcessingStatusRead.model_validate(detail["processing_status"])
                if detail["processing_status"]
                else None
            ),
            "history": [
                ComplaintStatusHistoryRead.model_validate(h)
                for h in detail["history"]
            ],
        }
    except (CitizenNotFound, ComplaintNotFound) as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/complaints/{complaint_id}/verify-closure")
async def verify_closure(
    complaint_id: str,
    payload: ClosureVerificationPayload,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(login_rate_limit),
):
    try:
        complaint = await service_verify_closure(
            db,
            payload.phone,
            complaint_id,
            payload.confirmed,
            payload.reopen_reason,
        )
        return {"status": "success", "complaint_status": complaint.status}
    except (CitizenNotFound, ComplaintNotFound) as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ClosureExpired as e:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(e))
    except InvalidInput as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
