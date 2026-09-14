from sqlalchemy import Column, String, Integer, SmallInteger, Boolean, DateTime, text, ForeignKey, Numeric, BigInteger, CheckConstraint, Computed
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM
from geoalchemy2 import Geometry
from .base import Base

worker_status_enum = ENUM('green', 'yellow', 'red', name='worker_status', create_type=False)
assignment_status_enum = ENUM('assigned', 'accepted', 'worker_excused', 'rejected', 'in_progress', 'completed', name='assignment_status', create_type=False)
anomaly_flag_type_enum = ENUM('impossible_travel', 'fast_completion', 'duplicate_photo', 'model_flagged', name='anomaly_flag_type', create_type=False)
anomaly_severity_enum = ENUM('low', 'medium', 'high', name='anomaly_severity', create_type=False)
anomaly_review_outcome_enum = ENUM('pending', 'confirmed_fraud', 'false_positive', name='anomaly_review_outcome', create_type=False)

class WorkerBulkUpload(Base):
    __tablename__ = 'worker_bulk_uploads'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    officer_id = Column(UUID(as_uuid=True), ForeignKey('officers.id', ondelete='RESTRICT'), nullable=False)
    jurisdiction_id = Column(UUID(as_uuid=True), ForeignKey('jurisdictions.id', ondelete='RESTRICT'), nullable=False)
    file_name = Column(String, nullable=False)
    total_rows = Column(Integer, nullable=False)
    success_count = Column(Integer, nullable=False)
    failed_count = Column(Integer, nullable=False)
    error_report = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    uploaded_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class Worker(Base):
    __tablename__ = 'workers'
    __table_args__ = (
        CheckConstraint("profile_score between 0 and 100", name='chk_workers_profile_score'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    mobile_hash = Column(String(64), unique=True, nullable=False)
    login_pin_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey('departments.id', ondelete='RESTRICT'), nullable=False)
    jurisdiction_id = Column(UUID(as_uuid=True), ForeignKey('jurisdictions.id', ondelete='RESTRICT'), nullable=False)
    preferred_language = Column(String, nullable=False, server_default='en')
    profile_score = Column(SmallInteger, nullable=False, server_default='100')
    profile_status = Column(worker_status_enum, Computed('compute_worker_status(profile_score)', persisted=True))
    bulk_upload_id = Column(UUID(as_uuid=True), ForeignKey('worker_bulk_uploads.id', ondelete='SET NULL'))
    is_active = Column(Boolean, nullable=False, server_default='true')
    created_by_officer_id = Column(UUID(as_uuid=True), ForeignKey('officers.id', ondelete='SET NULL'))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class WorkerScoreHistory(Base):
    __tablename__ = 'worker_score_history'
    __table_args__ = (
        CheckConstraint("change_amount <> 0", name='chk_worker_score_change_nonzero'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    worker_id = Column(UUID(as_uuid=True), ForeignKey('workers.id', ondelete='CASCADE'), nullable=False)
    change_amount = Column(SmallInteger, nullable=False)
    reason = Column(String, nullable=False)
    related_assignment_id = Column(UUID(as_uuid=True), ForeignKey('worker_assignments.id', ondelete='SET NULL'))
    changed_by = Column(UUID(as_uuid=True), ForeignKey('officers.id', ondelete='SET NULL'))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class WorkerAssignment(Base):
    __tablename__ = 'worker_assignments'
    __table_args__ = (
        CheckConstraint("status <> 'rejected' or rejected_reason is not null", name='chk_worker_assignments_rejection'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    complaint_id = Column(UUID(as_uuid=True), ForeignKey('complaints.id', ondelete='RESTRICT'), nullable=False)
    worker_id = Column(UUID(as_uuid=True), ForeignKey('workers.id', ondelete='RESTRICT'), nullable=False)
    status = Column(assignment_status_enum, nullable=False, server_default='assigned')
    assigned_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    accepted_at = Column(DateTime(timezone=True))
    excuse_used = Column(Boolean, nullable=False, server_default='false')
    rejected_at = Column(DateTime(timezone=True))
    rejected_reason = Column(String)
    arrival_photo_url = Column(String)
    arrival_location = Column(Geometry('POINT', srid=4326))
    arrived_at = Column(DateTime(timezone=True))
    completion_photo_url = Column(String)
    completion_location = Column(Geometry('POINT', srid=4326))
    completed_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, nullable=False, server_default='true')
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class WorkerExcuse(Base):
    __tablename__ = 'worker_excuses'
    __table_args__ = (
        CheckConstraint("extension_hours > 0"),
        CheckConstraint("reason_text is not null or reason_audio_url is not null", name='chk_worker_excuse_reason')
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    worker_assignment_id = Column(UUID(as_uuid=True), ForeignKey('worker_assignments.id', ondelete='CASCADE'), unique=True, nullable=False)
    reason_text = Column(String)
    reason_audio_url = Column(String)
    extension_hours = Column(SmallInteger, nullable=False, server_default='24')
    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class WorkerCompletionFeatures(Base):
    __tablename__ = 'worker_completion_features'
    __table_args__ = (
        CheckConstraint("anomaly_score between 0 and 1"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    worker_assignment_id = Column(UUID(as_uuid=True), ForeignKey('worker_assignments.id', ondelete='CASCADE'), unique=True, nullable=False)
    distance_from_previous_job_meters = Column(Numeric)
    time_since_previous_job_seconds = Column(Integer)
    implied_travel_speed_kmph = Column(Numeric)
    completion_duration_seconds = Column(Integer)
    is_duplicate_photo = Column(Boolean, nullable=False, server_default='false')
    anomaly_score = Column(Numeric(5, 4))
    feature_vector = Column(JSONB, nullable=False)
    computed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    model_version = Column(String, nullable=False, server_default='xgboost-v1')

class AnomalyFlag(Base):
    __tablename__ = 'anomaly_flags'
    __table_args__ = (
        CheckConstraint("anomaly_score between 0 and 1"),
        CheckConstraint("review_outcome = 'pending' or (reviewed_by is not null and reviewed_at is not null)")
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    worker_id = Column(UUID(as_uuid=True), ForeignKey('workers.id', ondelete='RESTRICT'), nullable=False)
    worker_assignment_id = Column(UUID(as_uuid=True), ForeignKey('worker_assignments.id', ondelete='RESTRICT'), nullable=False)
    flag_type = Column(anomaly_flag_type_enum, nullable=False)
    severity = Column(anomaly_severity_enum, nullable=False)
    anomaly_score = Column(Numeric(5, 4))
    review_outcome = Column(anomaly_review_outcome_enum, nullable=False, server_default='pending')
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey('officers.id', ondelete='SET NULL'))
    reviewed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class PhotoHashRegistry(Base):
    __tablename__ = 'photo_hash_registry'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    worker_id = Column(UUID(as_uuid=True), ForeignKey('workers.id', ondelete='CASCADE'), nullable=False)
    worker_assignment_id = Column(UUID(as_uuid=True), ForeignKey('worker_assignments.id', ondelete='CASCADE'), unique=True, nullable=False)
    photo_sha256 = Column(String(64), nullable=False)
    photo_phash = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
