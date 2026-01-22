from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PhoneProvisionRequest(BaseModel):
    """Request to provision a phone number."""
    phone_number: str = Field(..., description="E.164 format (+1234567890)")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"phone_number": "+18305550001"}
        }
    )


class PhoneStatusResponse(BaseModel):
    """Phone calling status for organization."""
    enabled: bool
    phone_number: Optional[str] = None
    provisioned_at: Optional[str] = None
    sip_trunk_id: Optional[str] = None
    status: str = "disabled"  # disabled, active, suspended


class AvailableNumberResponse(BaseModel):
    """Available phone number from search."""
    phone_number: str
    friendly_name: str
    locality: Optional[str] = None
    region: Optional[str] = None
    capabilities: dict = Field(default_factory=dict)


class AvailableNumbersResponse(BaseModel):
    """List of available phone numbers."""
    numbers: list[AvailableNumberResponse]


class PhoneProvisionResponse(BaseModel):
    """Phone provisioning result."""
    success: bool
    phone_number: str
    sip_trunk_id: Optional[str] = None


class PhoneDisableResponse(BaseModel):
    """Phone disable result."""
    success: bool
    message: str
