from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from .enums import NotificationType

class PushSubscriptionCreate(BaseModel):
    endpoint: str
    p256dh: str
    auth_key: str
    user_agent: Optional[str] = None

class PushSubscriptionRead(BaseModel):
    id: str
    citizen_id: Optional[str] = None
    worker_id: Optional[str] = None
    endpoint: str
    p256dh: str
    auth_key: str
    user_agent: Optional[str] = None
    created_at: datetime
    is_active: bool
    invalidated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class NotificationLogRead(BaseModel):
    id: str
    push_subscription_id: Optional[str] = None
    notification_type: NotificationType
    related_complaint_id: Optional[str] = None
    related_worker_assignment_id: Optional[str] = None
    payload: dict
    sent_at: datetime
    delivered: Optional[bool] = None
    failure_reason: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)
