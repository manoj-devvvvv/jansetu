from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from .enums import (
    JurisdictionLevel, ComplaintInputMode, ComplaintSeverity,
    ComplaintStatus, AiProcessingStatus
)

class CitizenRead(BaseModel):
    id: str
    mobile_hash: str
    preferred_language: str
    total_complaints_filed: int
    is_blocked: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ComplaintCreate(BaseModel):
    department_id: str
    panchayat_id: str
    mandal_id: str
    district_id: str
    location: dict # GeoJSON Point
    input_mode: ComplaintInputMode
    voice_audio_url: Optional[str] = None
    raw_text: Optional[str] = None
    image_url: str

class ComplaintRead(BaseModel):
    id: str
    citizen_id: str
    department_id: str
    panchayat_id: str
    mandal_id: str
    district_id: str
    current_review_level: JurisdictionLevel
    input_mode: ComplaintInputMode
    voice_audio_url: Optional[str] = None
    raw_text: Optional[str] = None
    formalized_text: Optional[str] = None
    detected_language: Optional[str] = None
    transcription_confidence: Optional[float] = None
    severity: ComplaintSeverity
    image_url: str
    status: ComplaintStatus
    wait_count: int
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class ComplaintUpdate(BaseModel):
    formalized_text: Optional[str] = None
    severity: Optional[ComplaintSeverity] = None

class ComplaintImageValidationRead(BaseModel):
    id: str
    complaint_id: str
    model_name: str
    detected_labels: list
    confidence: Optional[float] = None
    is_valid: bool
    rejection_reason: Optional[str] = None
    validated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ComplaintProcessingStatusRead(BaseModel):
    complaint_id: str
    transcription_status: AiProcessingStatus
    formalization_status: AiProcessingStatus
    image_validation_status: AiProcessingStatus
    embedding_status: AiProcessingStatus
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ComplaintStatusHistoryRead(BaseModel):
    id: str
    complaint_id: str
    old_status: Optional[ComplaintStatus] = None
    new_status: ComplaintStatus
    changed_at: datetime
    model_config = ConfigDict(from_attributes=True)
