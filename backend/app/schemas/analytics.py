from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
from .enums import MasterIssueStatus, JurisdictionLevel, ComplaintStatus, SlaTrackerType

class MasterIssueRead(BaseModel):
    id: str
    department_id: str
    jurisdiction_id: str
    cluster_level: JurisdictionLevel
    representative_complaint_id: Optional[str] = None
    confidence_score: Optional[float] = None
    member_count: int
    status: MasterIssueStatus
    is_fast_tracked: bool
    fast_tracked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class MasterIssueMemberRead(BaseModel):
    id: str
    master_issue_id: str
    complaint_id: str
    similarity_score: Optional[float] = None
    joined_at: datetime
    is_active: bool
    superseded_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class RecurringIssuePatternRead(BaseModel):
    id: str
    jurisdiction_id: str
    department_id: str
    pattern_month: Optional[int] = None
    occurrence_years: List[int]
    recurrence_count: int
    confidence_score: Optional[float] = None
    description: Optional[str] = None
    related_master_issue_ids: List[str]
    first_detected_at: datetime
    last_detected_at: datetime
    is_active: bool
    model_config = ConfigDict(from_attributes=True)

class QuarterlyComplaintSummaryRead(BaseModel):
    panchayat_id: str
    mandal_id: str
    district_id: str
    department_id: str
    quarter_start: datetime
    status: ComplaintStatus
    complaint_count: int
    avg_resolution_hours: Optional[float] = None
    model_config = ConfigDict(from_attributes=True)

class SlaComplianceRead(BaseModel):
    panchayat_id: str
    mandal_id: str
    district_id: str
    department_id: str
    quarter_start: datetime
    tracker_type: SlaTrackerType
    total_trackers: int
    breached_count: int
    model_config = ConfigDict(from_attributes=True)

class ClosureVerificationRead(BaseModel):
    id: str
    complaint_id: str
    worker_assignment_id: str
    reminder_count: int
    last_reminder_sent_at: Optional[datetime] = None
    citizen_confirmed: bool
    citizen_confirmed_at: Optional[datetime] = None
    reopened: bool
    reopened_at: Optional[datetime] = None
    reopen_reason: Optional[str] = None
    red_flagged: bool
    created_at: datetime
    verification_due_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)
