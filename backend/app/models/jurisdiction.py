from sqlalchemy import Column, String, Integer, Boolean, DateTime, text, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID, ENUM
from geoalchemy2 import Geometry
from .base import Base

jurisdiction_level_enum = ENUM('panchayat', 'mandal', 'district', name='jurisdiction_level', create_type=False)

class Department(Base):
    __tablename__ = 'departments'
    __table_args__ = (
        CheckConstraint("name_i18n ? 'en'", name='chk_departments_name_en'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    code = Column(String, unique=True, nullable=False)
    name_i18n = Column(JSONB, nullable=False, server_default='{}')
    icon_key = Column(String)
    display_order = Column(Integer, nullable=False, server_default='0')
    is_active = Column(Boolean, nullable=False, server_default='true')
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

class Jurisdiction(Base):
    __tablename__ = 'jurisdictions'
    __table_args__ = (
        CheckConstraint("name_i18n ? 'en'", name='chk_jurisdictions_name_en'),
        CheckConstraint("(level = 'district') = (parent_id is null)", name='chk_jurisdictions_parent_matches_level')
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    level = Column(jurisdiction_level_enum, nullable=False)
    parent_id = Column(UUID(as_uuid=True), ForeignKey('jurisdictions.id', ondelete='CASCADE'))
    name_i18n = Column(JSONB, nullable=False, server_default='{}')
    lgd_code = Column(String)
    boundary = Column(Geometry('MULTIPOLYGON', srid=4326))
    centroid = Column(Geometry('POINT', srid=4326))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
