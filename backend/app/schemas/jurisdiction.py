from pydantic import BaseModel, ConfigDict
from typing import Optional, Dict
from datetime import datetime
from .enums import JurisdictionLevel

class DepartmentRead(BaseModel):
    id: str
    code: str
    name_i18n: Dict[str, str]
    icon_key: str
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class JurisdictionCreate(BaseModel):
    level: JurisdictionLevel
    parent_id: Optional[str] = None
    name_i18n: Dict[str, str]
    lgd_code: Optional[str] = None
    # boundary & centroid handling is typically done out of band or via specific GeoJSON payloads

class JurisdictionRead(BaseModel):
    id: str
    level: JurisdictionLevel
    parent_id: Optional[str] = None
    name_i18n: Dict[str, str]
    lgd_code: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
