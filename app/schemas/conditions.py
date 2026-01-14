from datetime import date, datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from app.models.conditions import Condition

class HIVProfileBase(BaseModel):
    """Base schema for HIV Profile."""
    date_of_diagnosis: Optional[date] = None
    art_start_date: Optional[date] = None
    baseline_viral_load: Optional[int] = None
    baseline_cd4_count: Optional[int] = None
    initial_art_regimen: Optional[str] = None
    current_art_regimen: Optional[str] = None
    
    last_refill_date: Optional[date] = None
    refill_months: Optional[int] = None
    next_refill_date: Optional[date] = None
    
    last_viral_load_sample_date: Optional[date] = None
    last_viral_load_result_date: Optional[date] = None
    last_viral_load_result: Optional[int] = None

class HIVProfileCreate(HIVProfileBase):
    """Schema for creating HIV Profile."""
    pass

class HIVProfileUpdate(HIVProfileBase):
    """Schema for updating HIV Profile."""
    pass

class HIVProfileResponse(HIVProfileBase):
    """Schema for HIV Profile response."""
    id: UUID
    patient_id: UUID
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# Hypertension Profile Schemas
class HypertensionProfileBase(BaseModel):
    """Base schema for Hypertension Profile."""
    date_of_diagnosis: Optional[date] = None
    baseline_systolic: Optional[int] = None
    baseline_diastolic: Optional[int] = None
    target_systolic: Optional[int] = Field(default=130)
    target_diastolic: Optional[int] = Field(default=80)
    current_medication: Optional[str] = None
    medication_start_date: Optional[date] = None
    has_diabetes: bool = False
    has_kidney_disease: bool = False
    has_heart_disease: bool = False
    last_checkup_date: Optional[date] = None
    next_checkup_date: Optional[date] = None

class HypertensionProfileCreate(HypertensionProfileBase):
    """Schema for creating Hypertension Profile."""
    pass

class HypertensionProfileUpdate(HypertensionProfileBase):
    """Schema for updating Hypertension Profile."""
    pass

class HypertensionProfileResponse(HypertensionProfileBase):
    """Schema for Hypertension Profile response."""
    id: UUID
    patient_id: UUID
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# Diabetes Profile Schemas
class DiabetesProfileBase(BaseModel):
    """Base schema for Diabetes Profile."""
    date_of_diagnosis: Optional[date] = None
    diabetes_type: Optional[str] = None
    baseline_hba1c: Optional[float] = None
    target_hba1c: Optional[float] = Field(default=7.0)
    baseline_fasting_glucose: Optional[float] = None
    target_fasting_glucose: Optional[float] = Field(default=100.0)
    current_treatment: Optional[str] = None
    insulin_regimen: Optional[str] = None
    last_hba1c_date: Optional[date] = None
    last_hba1c_result: Optional[float] = None
    last_eye_exam_date: Optional[date] = None
    last_foot_exam_date: Optional[date] = None
    last_kidney_function_date: Optional[date] = None

class DiabetesProfileCreate(DiabetesProfileBase):
    """Schema for creating Diabetes Profile."""
    pass

class DiabetesProfileUpdate(DiabetesProfileBase):
    """Schema for updating Diabetes Profile."""
    pass

class DiabetesProfileResponse(DiabetesProfileBase):
    """Schema for Diabetes Profile response."""
    id: UUID
    patient_id: UUID
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
