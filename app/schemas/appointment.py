"""
Appointment Schemas.

Pydantic models for appointment API requests and responses.
"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.appointment import AppointmentStatus


class AppointmentCreate(BaseModel):
    """Request schema for creating an appointment."""
    patient_id: UUID
    provider_id: Optional[UUID] = None
    scheduled_time: datetime
    type: str = Field(..., min_length=1, max_length=100, description="e.g., 'Follow-up', 'Lab Review'")
    notes: Optional[str] = None


class AppointmentUpdate(BaseModel):
    """Request schema for updating an appointment."""
    provider_id: Optional[UUID] = None
    scheduled_time: Optional[datetime] = None
    type: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None
    status: Optional[AppointmentStatus] = None


class AppointmentResponse(BaseModel):
    """Response schema for a single appointment."""
    id: UUID
    patient_id: UUID
    organization_id: UUID
    provider_id: Optional[UUID] = None
    scheduled_time: datetime
    type: str
    status: AppointmentStatus
    notes: Optional[str] = None
    priority_level: int = 0
    no_show_count: int = 0
    reminder_sent_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class AppointmentWithPatient(AppointmentResponse):
    """Response with embedded patient info."""
    patient_name: Optional[str] = None
    patient_phone: Optional[str] = None


class AppointmentListResponse(BaseModel):
    """Paginated list of appointments."""
    appointments: List[AppointmentResponse]
    total: int
    skip: int
    limit: int
