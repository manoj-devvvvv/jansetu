from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from .enums import JurisdictionLevel

class OfficerCreate(BaseModel):
    id: str # From Supabase Auth
    full_name: str
    level: JurisdictionLevel
    jurisdiction_id: str

class OfficerRead(BaseModel):
    id: str
    full_name: str
    level: JurisdictionLevel
    jurisdiction_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class VerificationActionCreate(BaseModel):
    action_type: str # 'verify', 'dismiss', 'wait', 'escalate'
    reason: Optional[str] = None

class VerificationActionRead(BaseModel):
    id: str
    complaint_id: str
    officer_id: str
    action_type: str
    reason: Optional[str] = None
    review_level: Optional[JurisdictionLevel] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class EscalationCreate(BaseModel):
    complaint_id: str
    to_level: JurisdictionLevel
    reason: str

class EscalationRead(BaseModel):
    id: str
    complaint_id: str
    from_level: JurisdictionLevel
    to_level: JurisdictionLevel
    trigger_type: str
    escalated_by: Optional[str] = None
    reason: str
    sla_tracker_id: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)
