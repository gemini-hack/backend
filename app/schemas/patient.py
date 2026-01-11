from datetime import date, datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, ConfigDict

from app.models.patient import Condition, Gender, PatientStatus, CommunicationPreference

class PatientBase(BaseModel):
    """Base schema for patient."""
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    date_of_birth: date
    gender: Optional[Gender] = None
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    
    primary_condition: Condition
    secondary_conditions: List[str] = Field(default_factory=list)
    medical_history: Optional[str] = None
    current_medications: List[str] = Field(default_factory=list)
    allergies: List[str] = Field(default_factory=list)

class PatientCreate(PatientBase):
    """Schema for creating a patient."""
    patient_uid: str = Field(..., min_length=1, max_length=50)
    emergency_contact_name: Optional[str] = Field(None, max_length=200)
    emergency_contact_phone: Optional[str] = Field(None, max_length=20)
    emergency_contact_relationship: Optional[str] = Field(None, max_length=50)
    
    primary_physician_id: Optional[UUID] = None
    assigned_nurse_id: Optional[UUID] = None
    care_coordinator_id: Optional[UUID] = None
    
    monitoring_frequency: str = Field("daily", max_length=50)
    preferred_contact_method: CommunicationPreference = Field(CommunicationPreference.SMS)
    preferred_language: str = Field("en", max_length=10)

class PatientResponse(PatientBase):
    """Schema for patient response."""
    id: UUID
    organization_id: UUID
    patient_uid: str
    status: PatientStatus
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class PatientListResponse(BaseModel):
    """Schema for list of patients response."""
    patients: List[PatientResponse]
    total: int
