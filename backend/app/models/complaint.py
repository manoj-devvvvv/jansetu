from sqlalchemy import Column, String, Integer, SmallInteger, Boolean, DateTime, text, ForeignKey, Numeric, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM, INET
from geoalchemy2 import Geometry
from pgvector.sqlalchemy import Vector
from .base import Base

jurisdiction_level_enum = ENUM('panchayat', 'mandal', 'district', name='jurisdiction_level', create_type=False)
complaint_input_mode_enum = ENUM('voice', 'text', name='complaint_input_mode', create_type=False)
complaint_severity_enum = ENUM('low', 'medium', 'high', 'critical', name='complaint_severity', create_type=False)
complaint_status_enum = ENUM('submitted', 'waiting', 'escalated', 'dismissed', 'assigned', 'in_progress', 'pending_citizen_confirmation', 'reopened', 'closed', name='complaint_status', create_type=False)
ai_processing_status_enum = ENUM('pending', 'processing', 'completed', 'failed', name='ai_processing_status', create_type=False)

class Citizen(Base):
    __tablename__ = 'citizens'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    mobile_hash = Column(String(64), unique=True, nullable=False)
    preferred_language = Column(String, nullable=False, server_default='en')
    total_complaints_filed = Column(Integer, nullable=False, server_default='0')
    is_blocked = Column(Boolean, nullable=False, server_default='false')
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class Complaint(Base):
    __tablename__ = 'complaints'
    __table_args__ = (
        CheckConstraint("input_mode <> 'voice' or voice_audio_url is not null", name='chk_complaints_voice_has_audio'),
        CheckConstraint("wait_count between 0 and 2", name='chk_complaints_wait_count_range')
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    citizen_id = Column(UUID(as_uuid=True), ForeignKey('citizens.id', ondelete='RESTRICT'), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey('departments.id', ondelete='RESTRICT'), nullable=False)
    panchayat_id = Column(UUID(as_uuid=True), ForeignKey('jurisdictions.id', ondelete='RESTRICT'), nullable=False)
    mandal_id = Column(UUID(as_uuid=True), ForeignKey('jurisdictions.id', ondelete='RESTRICT'), nullable=False)
    district_id = Column(UUID(as_uuid=True), ForeignKey('jurisdictions.id', ondelete='RESTRICT'), nullable=False)
    current_review_level = Column(jurisdiction_level_enum, nullable=False, server_default='panchayat')
    location = Column(Geometry('POINT', srid=4326), nullable=False)
    input_mode = Column(complaint_input_mode_enum, nullable=False)
    voice_audio_url = Column(String)
    raw_text = Column(String)
    formalized_text = Column(String)
    detected_language = Column(String)
    transcription_confidence = Column(Numeric(4, 3))
    severity = Column(complaint_severity_enum, nullable=False, server_default='medium')
    image_url = Column(String, nullable=False)
    submitter_ip = Column(INET, nullable=False)
    status = Column(complaint_status_enum, nullable=False, server_default='submitted')
    wait_count = Column(SmallInteger, nullable=False, server_default='0')
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    resolved_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))

class ComplaintImageValidation(Base):
    __tablename__ = 'complaint_image_validations'
    __table_args__ = (
        CheckConstraint("confidence between 0 and 1"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    complaint_id = Column(UUID(as_uuid=True), ForeignKey('complaints.id', ondelete='CASCADE'), unique=True, nullable=False)
    model_name = Column(String, nullable=False, server_default='yolo11')
    detected_labels = Column(JSONB, nullable=False, server_default='[]')
    confidence = Column(Numeric(5, 4), nullable=False)
    is_valid = Column(Boolean, nullable=False)
    rejection_reason = Column(String)
    validated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class ComplaintStatusTransition(Base):
    __tablename__ = 'complaint_status_transitions'

    from_status = Column(complaint_status_enum, primary_key=True)
    to_status = Column(complaint_status_enum, primary_key=True)

class ComplaintStatusHistory(Base):
    __tablename__ = 'complaint_status_history'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    complaint_id = Column(UUID(as_uuid=True), ForeignKey('complaints.id', ondelete='CASCADE'), nullable=False)
    old_status = Column(complaint_status_enum)
    new_status = Column(complaint_status_enum, nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class ComplaintProcessingStatus(Base):
    __tablename__ = 'complaint_processing_status'

    complaint_id = Column(UUID(as_uuid=True), ForeignKey('complaints.id', ondelete='CASCADE'), primary_key=True)
    transcription_status = Column(ai_processing_status_enum, nullable=False, server_default='pending')
    formalization_status = Column(ai_processing_status_enum, nullable=False, server_default='pending')
    image_validation_status = Column(ai_processing_status_enum, nullable=False, server_default='pending')
    embedding_status = Column(ai_processing_status_enum, nullable=False, server_default='pending')
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class ComplaintEmbedding(Base):
    __tablename__ = 'complaint_embeddings'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    complaint_id = Column(UUID(as_uuid=True), ForeignKey('complaints.id', ondelete='CASCADE'), unique=True, nullable=False)
    embedding = Column(Vector(1024), nullable=False)
    model_version = Column(String, nullable=False, server_default='bge-m3')
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
