from sqlalchemy import Column, String, Boolean, DateTime, text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ENUM
from .base import Base

jurisdiction_level_enum = ENUM('panchayat', 'mandal', 'district', name='jurisdiction_level', create_type=False)

class Officer(Base):
    __tablename__ = 'officers'

    id = Column(UUID(as_uuid=True), primary_key=True)
    full_name = Column(String, nullable=False)
    level = Column(jurisdiction_level_enum, nullable=False)
    jurisdiction_id = Column(UUID(as_uuid=True), ForeignKey('jurisdictions.id', ondelete='RESTRICT'), nullable=False)
    is_active = Column(Boolean, nullable=False, server_default='true')
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
