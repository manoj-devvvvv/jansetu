from sqlalchemy import Column, String, Integer, SmallInteger, Boolean, DateTime, text, ForeignKey, Numeric, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY, ENUM
from geoalchemy2 import Geometry
from .base import Base

jurisdiction_level_enum = ENUM('panchayat', 'mandal', 'district', name='jurisdiction_level', create_type=False)
master_issue_status_enum = ENUM('active', 'fast_tracked', 'resolved', 'closed', name='master_issue_status', create_type=False)
notification_type_enum = ENUM('assignment', 'sla_reminder', 'citizen_verification_reminder', 'escalation', 'general', name='notification_type', create_type=False)

class MasterIssue(Base):
    __tablename__ = 'master_issues'
    __table_args__ = (
        CheckConstraint("cluster_level in ('panchayat', 'mandal')", name='chk_master_issue_cluster_level'),
        CheckConstraint("confidence_score between 0 and 1")
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    department_id = Column(UUID(as_uuid=True), ForeignKey('departments.id', ondelete='RESTRICT'), nullable=False)
    jurisdiction_id = Column(UUID(as_uuid=True), ForeignKey('jurisdictions.id', ondelete='RESTRICT'), nullable=False)
    cluster_level = Column(jurisdiction_level_enum, nullable=False)
    representative_complaint_id = Column(UUID(as_uuid=True), ForeignKey('complaints.id', ondelete='SET NULL'))
    centroid_location = Column(Geometry('POINT', srid=4326))
    confidence_score = Column(Numeric(5, 4))
    member_count = Column(Integer, nullable=False, server_default='0')
    status = Column(master_issue_status_enum, nullable=False, server_default='active')
    is_fast_tracked = Column(Boolean, nullable=False, server_default='false')
    fast_tracked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class MasterIssueMember(Base):
    __tablename__ = 'master_issue_members'
    __table_args__ = (
        CheckConstraint("similarity_score between 0 and 1"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    master_issue_id = Column(UUID(as_uuid=True), ForeignKey('master_issues.id', ondelete='CASCADE'), nullable=False)
    complaint_id = Column(UUID(as_uuid=True), ForeignKey('complaints.id', ondelete='CASCADE'), nullable=False)
    similarity_score = Column(Numeric(5, 4))
    joined_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    is_active = Column(Boolean, nullable=False, server_default='true')
    superseded_at = Column(DateTime(timezone=True))

class RecurringIssuePattern(Base):
    __tablename__ = 'recurring_issue_patterns'
    __table_args__ = (
        CheckConstraint("pattern_month between 1 and 12", name='chk_recurring_patterns_month'),
        CheckConstraint("confidence_score between 0 and 1", name='chk_recurring_patterns_confidence')
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    jurisdiction_id = Column(UUID(as_uuid=True), ForeignKey('jurisdictions.id', ondelete='CASCADE'), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey('departments.id', ondelete='CASCADE'), nullable=False)
    pattern_month = Column(SmallInteger)
    occurrence_years = Column(ARRAY(Integer), nullable=False, server_default='{}')
    recurrence_count = Column(Integer, nullable=False, server_default='0')
    confidence_score = Column(Numeric(5, 4))
    description = Column(String)
    related_master_issue_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=False, server_default='{}')
    first_detected_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    last_detected_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    is_active = Column(Boolean, nullable=False, server_default='true')

class ClosureVerification(Base):
    __tablename__ = 'closure_verifications'
    __table_args__ = (
        CheckConstraint("not (citizen_confirmed and reopened)", name='chk_closure_not_both'),
        CheckConstraint("not reopened or reopen_reason is not null", name='chk_closure_reopen_reason')
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    complaint_id = Column(UUID(as_uuid=True), ForeignKey('complaints.id', ondelete='CASCADE'), nullable=False)
    worker_assignment_id = Column(UUID(as_uuid=True), ForeignKey('worker_assignments.id', ondelete='CASCADE'), unique=True, nullable=False)
    reminder_count = Column(SmallInteger, nullable=False, server_default='0')
    last_reminder_sent_at = Column(DateTime(timezone=True))
    citizen_confirmed = Column(Boolean, nullable=False, server_default='false')
    citizen_confirmed_at = Column(DateTime(timezone=True))
    reopened = Column(Boolean, nullable=False, server_default='false')
    reopened_at = Column(DateTime(timezone=True))
    reopen_reason = Column(String)
    red_flagged = Column(Boolean, nullable=False, server_default='false')
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    verification_due_at = Column(DateTime(timezone=True))

class CitizenVerificationReminder(Base):
    __tablename__ = 'citizen_verification_reminders'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    closure_verification_id = Column(UUID(as_uuid=True), ForeignKey('closure_verifications.id', ondelete='CASCADE'), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class PushSubscription(Base):
    __tablename__ = 'push_subscriptions'
    __table_args__ = (
        CheckConstraint(
            "(citizen_id is not null and worker_id is null) or (citizen_id is null and worker_id is not null)",
            name='chk_push_subscription_owner'
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    citizen_id = Column(UUID(as_uuid=True), ForeignKey('citizens.id', ondelete='CASCADE'))
    worker_id = Column(UUID(as_uuid=True), ForeignKey('workers.id', ondelete='CASCADE'))
    endpoint = Column(String, nullable=False, unique=True)
    p256dh = Column(String, nullable=False)
    auth_key = Column(String, nullable=False)
    user_agent = Column(String)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    is_active = Column(Boolean, nullable=False, server_default='true')
    invalidated_at = Column(DateTime(timezone=True))

class NotificationLog(Base):
    __tablename__ = 'notification_log'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    push_subscription_id = Column(UUID(as_uuid=True), ForeignKey('push_subscriptions.id', ondelete='SET NULL'))
    notification_type = Column(notification_type_enum, nullable=False)
    related_complaint_id = Column(UUID(as_uuid=True), ForeignKey('complaints.id', ondelete='SET NULL'))
    related_worker_assignment_id = Column(UUID(as_uuid=True), ForeignKey('worker_assignments.id', ondelete='SET NULL'))
    payload = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    sent_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    delivered = Column(Boolean)
    failure_reason = Column(String)
