from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, computed_field, field_validator
from app.models.appointment import AppointmentStatus, VisitMode

class AppointmentCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    """Schema used by The Hand (Agent) or Frontend to book."""
    patient_id: UUID
    provider_id: Optional[UUID] = None
    scheduled_time: datetime
    appointment_type: str = Field(..., min_length=1, max_length=100)
    duration_minutes: int = Field(30, ge=1, le=480)
    visit_mode: VisitMode = VisitMode.IN_PERSON
    notes: Optional[str] = None

    @field_validator('scheduled_time')
    @classmethod
    def scheduled_time_must_be_future(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        if v <= datetime.now(timezone.utc):
            raise ValueError('Appointment time must be in the future')
        return v

class AppointmentResponse(BaseModel):
    id: UUID
    patient_id: UUID
    organization_id: UUID
    provider_id: Optional[UUID] = None
    scheduled_time: datetime
    appointment_type: str
    visit_mode: VisitMode
    status: AppointmentStatus
    duration_minutes: int
    notes: Optional[str] = None
    priority_level: int
    google_event_id: Optional[str] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class AppointmentWithPatient(AppointmentResponse):
    @computed_field
    def patient_name(self) -> Optional[str]:
        if hasattr(self, 'patient') and self.patient:
            return f"{self.patient.first_name} {self.patient.last_name}"
        return None

class AppointmentUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    """Schema for updating an appointment."""
    scheduled_time: Optional[datetime] = None
    appointment_type: Optional[str] = None
    visit_mode: Optional[VisitMode] = None
    status: Optional[AppointmentStatus] = None
    notes: Optional[str] = None
    priority_level: Optional[int] = Field(None, ge=0, le=10)
    duration_minutes: Optional[int] = Field(None, ge=1, le=480)
    provider_id: Optional[UUID] = None


class AppointmentListResponse(BaseModel):
    """Paginated list of appointments."""
    items: List[AppointmentWithPatient]
    total: int
    page: int
    size: int
    pages: int