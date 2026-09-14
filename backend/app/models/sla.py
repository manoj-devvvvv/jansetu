from sqlalchemy import Column, String, Integer, Boolean, DateTime, text, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, ENUM
from .base import Base

sla_tracker_type_enum = ENUM('worker_assignment', 'panchayat_verification', 'mandal_verification', 'district_verification', name='sla_tracker_type', create_type=False)
verification_action_type_enum = ENUM('verify', 'dismiss', 'wait', 'escalate', name='verification_action_type', create_type=False)
jurisdiction_level_enum = ENUM('panchayat', 'mandal', 'district', name='jurisdiction_level', create_type=False)
escalation_trigger_type_enum = ENUM('manual', 'sla_breach', name='escalation_trigger_type', create_type=False)

class SlaConfig(Base):
    __tablename__ = 'sla_configs'
    __table_args__ = (
        CheckConstraint("duration_hours > 0"),
    )

    tracker_type = Column(sla_tracker_type_enum, primary_key=True)
    duration_hours = Column(Integer, nullable=False)
    description = Column(String)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class SlaTracker(Base):
    __tablename__ = 'sla_trackers'
    __table_args__ = (
        CheckConstraint(
            "(tracker_type = 'worker_assignment' and worker_assignment_id is not null and complaint_id is null) or "
            "(tracker_type <> 'worker_assignment' and complaint_id is not null and worker_assignment_id is null)",
            name='chk_sla_tracker_reference'
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tracker_type = Column(sla_tracker_type_enum, nullable=False)
    worker_assignment_id = Column(UUID(as_uuid=True), ForeignKey('worker_assignments.id', ondelete='CASCADE'))
    complaint_id = Column(UUID(as_uuid=True), ForeignKey('complaints.id', ondelete='CASCADE'))
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    due_at = Column(DateTime(timezone=True), nullable=False)
    breached = Column(Boolean, nullable=False, server_default='false')
    breach_processed_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class ComplaintVerificationAction(Base):
    __tablename__ = 'complaint_verification_actions'
    __table_args__ = (
        CheckConstraint(
            "action_type = 'verify' or (reason is not null and length(trim(reason)) > 0)",
            name='chk_verification_action_reason'
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    complaint_id = Column(UUID(as_uuid=True), ForeignKey('complaints.id', ondelete='CASCADE'), nullable=False)
    officer_id = Column(UUID(as_uuid=True), ForeignKey('officers.id', ondelete='RESTRICT'), nullable=False)
    action_type = Column(verification_action_type_enum, nullable=False)
    reason = Column(String)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    review_level = Column(jurisdiction_level_enum)

class Escalation(Base):
    __tablename__ = 'escalations'
    __table_args__ = (
        CheckConstraint(
            "(from_level = 'panchayat' and to_level = 'mandal') or (from_level = 'mandal' and to_level = 'district')",
            name='chk_escalation_direction'
        ),
        CheckConstraint(
            "trigger_type <> 'manual' or escalated_by is not null"
        )
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    complaint_id = Column(UUID(as_uuid=True), ForeignKey('complaints.id', ondelete='CASCADE'), nullable=False)
    from_level = Column(jurisdiction_level_enum, nullable=False)
    to_level = Column(jurisdiction_level_enum, nullable=False)
    trigger_type = Column(escalation_trigger_type_enum, nullable=False)
    escalated_by = Column(UUID(as_uuid=True), ForeignKey('officers.id', ondelete='SET NULL'))
    reason = Column(String, nullable=False)
    sla_tracker_id = Column(UUID(as_uuid=True), ForeignKey('sla_trackers.id', ondelete='SET NULL'))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    resolved_at = Column(DateTime(timezone=True))
    resolved_by = Column(UUID(as_uuid=True), ForeignKey('officers.id', ondelete='SET NULL'))
