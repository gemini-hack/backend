from datetime import date, datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, ConfigDict

from app.models.patient import Gender, PatientStatus, CommunicationPreference
from app.models.conditions import Condition
from app.schemas.conditions import (
    HIVProfileResponse, HIVProfileCreate,
    HypertensionProfileCreate, HypertensionProfileResponse,
    DiabetesProfileCreate, DiabetesProfileResponse,
)
from app.schemas.agent import AlertResponse, AgentActionResponse, ScheduledCheckResponse

class PatientBase(BaseModel):
    model_config = ConfigDict(extra='forbid')
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
    model_config = ConfigDict(extra='forbid')
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
    preferred_contact_time: Optional[str] = Field(None, max_length=50)
    timezone: str = Field("UTC", max_length=50)
    preferred_language: str = Field("en", max_length=10)
    
    # HIV Specific Initialization (Optional during patient creation)
    hiv_profile: Optional[HIVProfileCreate] = None
    hypertension_profile: Optional[HypertensionProfileCreate] = None
    diabetes_profile: Optional[DiabetesProfileCreate] = None

    team_id: Optional[UUID] = None
    provider_id: Optional[UUID] = None
    status: Optional[PatientStatus] = None

class PatientResponse(PatientBase):
    """Schema for patient response."""
    id: UUID
    organization_id: UUID
    patient_uid: str
    status: PatientStatus
    created_at: datetime
    updated_at: datetime
    
    # Modular Data
    hiv_profile: Optional[HIVProfileResponse] = None
    hypertension_profile: Optional[HypertensionProfileResponse] = None
    diabetes_profile: Optional[DiabetesProfileResponse] = None
    
    model_config = ConfigDict(from_attributes=True)

class PatientDetailResponse(PatientResponse):
    """Detailed patient response including health logs and agent data."""
    alerts: List[AlertResponse] = Field(default_factory=list)
    agent_actions: List[AgentActionResponse] = Field(default_factory=list)
    scheduled_checks: List[ScheduledCheckResponse] = Field(default_factory=list)

class PatientListResponse(BaseModel):
    """Schema for list of patients response."""
    patients: List[PatientResponse]
    total: int
    skip: int = 0
    limit: int = 100


class PatientUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    """Schema for updating a patient."""
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    date_of_birth: Optional[date] = None
    gender: Optional[Gender] = None
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    
    emergency_contact_name: Optional[str] = Field(None, max_length=200)
    emergency_contact_phone: Optional[str] = Field(None, max_length=20)
    emergency_contact_relationship: Optional[str] = Field(None, max_length=50)
    
    primary_physician_id: Optional[UUID] = None
    assigned_nurse_id: Optional[UUID] = None
    care_coordinator_id: Optional[UUID] = None
    
    status: Optional[PatientStatus] = None
    monitoring_frequency: Optional[str] = Field(None, max_length=50)
    preferred_contact_method: Optional[CommunicationPreference] = None
    preferred_language: Optional[str] = Field(None, max_length=10)
    
    secondary_conditions: Optional[List[str]] = None
    medical_history: Optional[str] = None
    current_medications: Optional[List[str]] = None
    allergies: Optional[List[str]] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None

    team_id: Optional[UUID] = None
    provider_id: Optional[UUID] = None
