from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from .enums import AssignmentStatus, WorkerStatus, AnomalyFlagType, AnomalySeverity, AnomalyReviewOutcome

class WorkerCreate(BaseModel):
    mobile_hash: str
    full_name: str
    department_id: str
    jurisdiction_id: str
    preferred_language: Optional[str] = "en"
    login_pin_hash: str # Note: In a real flow, you'd accept PIN and hash it

class WorkerUpdate(BaseModel):
    is_active: Optional[bool] = None
    preferred_language: Optional[str] = None

class WorkerRead(BaseModel):
    id: str
    mobile_hash: str
    full_name: str
    department_id: str
    jurisdiction_id: str
    preferred_language: str
    profile_score: int
    profile_status: WorkerStatus
    bulk_upload_id: Optional[str] = None
    is_active: bool
    created_by_officer_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class WorkerAssignmentRead(BaseModel):
    id: str
    complaint_id: str
    worker_id: str
    status: AssignmentStatus
    assigned_at: datetime
    accepted_at: Optional[datetime] = None
    excuse_used: bool
    rejected_at: Optional[datetime] = None
    rejected_reason: Optional[str] = None
    arrival_photo_url: Optional[str] = None
    arrived_at: Optional[datetime] = None
    completion_photo_url: Optional[str] = None
    completed_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class WorkerExcuseCreate(BaseModel):
    worker_assignment_id: str
    reason_text: Optional[str] = None
    reason_audio_url: Optional[str] = None

class WorkerExcuseRead(BaseModel):
    id: str
    worker_assignment_id: str
    reason_text: Optional[str] = None
    reason_audio_url: Optional[str] = None
    extension_hours: int
    requested_at: datetime
    model_config = ConfigDict(from_attributes=True)

class WorkerScoreHistoryRead(BaseModel):
    id: str
    worker_id: str
    change_amount: int
    reason: str
    related_assignment_id: Optional[str] = None
    changed_by: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class WorkerCompletionFeaturesRead(BaseModel):
    id: str
    worker_assignment_id: str
    distance_from_previous_job_meters: Optional[float] = None
    time_since_previous_job_seconds: Optional[int] = None
    implied_travel_speed_kmph: Optional[float] = None
    completion_duration_seconds: Optional[int] = None
    is_duplicate_photo: bool
    anomaly_score: Optional[float] = None
    feature_vector: dict
    computed_at: datetime
    model_version: str
    model_config = ConfigDict(from_attributes=True)

class AnomalyFlagRead(BaseModel):
    id: str
    worker_id: str
    worker_assignment_id: str
    flag_type: AnomalyFlagType
    severity: AnomalySeverity
    anomaly_score: Optional[float] = None
    review_outcome: AnomalyReviewOutcome
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
