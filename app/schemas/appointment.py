from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, computed_field
from app.models.appointment import AppointmentStatus, VisitMode

class AppointmentCreate(BaseModel):
    """Schema used by The Hand (Agent) or Frontend to book."""
    patient_id: UUID
    provider_id: Optional[UUID] = None
    scheduled_time: datetime
    appointment_type: str = Field(..., min_length=1, max_length=100)
    visit_mode: VisitMode = VisitMode.IN_PERSON
    notes: Optional[str] = None

class AppointmentResponse(BaseModel):
    id: UUID
    patient_id: UUID
    organization_id: UUID
    provider_id: Optional[UUID] = None
    scheduled_time: datetime
    appointment_type: str
    visit_mode: VisitMode
    status: AppointmentStatus
    notes: Optional[str] = None
    priority_level: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class AppointmentWithPatient(AppointmentResponse):
    @computed_field
    def patient_name(self) -> Optional[str]:
        if hasattr(self, 'patient') and self.patient:
            return f"{self.patient.first_name} {self.patient.last_name}"
        return None

class AppointmentUpdate(BaseModel):
    """Schema for updating an appointment."""
    scheduled_time: Optional[datetime] = None
    appointment_type: Optional[str] = None
    visit_mode: Optional[VisitMode] = None
    status: Optional[AppointmentStatus] = None
    notes: Optional[str] = None
    priority_level: Optional[int] = Field(None, ge=0, le=10)
    provider_id: Optional[UUID] = None


class AppointmentListResponse(BaseModel):
    """Paginated list of appointments."""
    items: List[AppointmentWithPatient]
    total: int
    page: int
    size: int
    pages: int