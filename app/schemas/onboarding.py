from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class OnboardingCompleteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    """Single-step onboarding completion.
    
    All fields optional - timezone auto-detected from IP.
    """
    address: Optional[str] = Field(None, max_length=500)
    license_number: Optional[str] = Field(None, max_length=100)
    disease_specializations: list[str] = Field(default_factory=list)
    timezone: Optional[str] = Field(None, description="Auto-detected if omitted")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "address": "123 Healthcare Drive, City, State",
                "license_number": "HSP-2024-001",
                "disease_specializations": ["diabetes", "hypertension"],
            }
        }
    )


class OnboardingStatusResponse(BaseModel):
    """Onboarding status check."""
    is_completed: bool
    completed_at: Optional[datetime] = None
    organization_name: str
    organization_type: str
    timezone: Optional[str] = None


class OnboardingCompleteResponse(BaseModel):
    """Onboarding completion result."""
    success: bool
    message: str
    completed_at: datetime
    timezone: str
