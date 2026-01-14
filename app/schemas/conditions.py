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
