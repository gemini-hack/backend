"""
Reminder Schemas.

Pydantic models for reminder API requests and responses.
"""
from datetime import datetime
from typing import Optional, Dict, List
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.reminder import ReminderChannel, ReminderStatus


class ReminderAttempt(BaseModel):
    """Schema for a single channel attempt."""
    sent_at: Optional[str] = None
    status: Optional[str] = None
    message_id: Optional[str] = None
    error: Optional[str] = None


class ReminderResponse(BaseModel):
    """Response schema for a single reminder."""
    id: UUID
    appointment_id: UUID
    patient_id: UUID
    organization_id: UUID
    channels: List[str]
    scheduled_send_time: datetime
    status: ReminderStatus
    attempts: Dict[str, ReminderAttempt] = {}
    created_by_agent: str
    reminder_type: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ReminderListResponse(BaseModel):
    """Paginated list of reminders."""
    reminders: List[ReminderResponse]
    total: int
    skip: int
    limit: int


class SendReminderNowRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    """Request to send an immediate reminder."""
    channel: Optional[ReminderChannel] = None  # If None, uses patient preference


class ReminderCancelRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    """Request to cancel a pending reminder."""
    reason: Optional[str] = None
