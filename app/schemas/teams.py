"""Team/Department Pydantic schemas."""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict

from app.models.user import UserRole


# ============== Team Schemas ==============

class TeamCreate(BaseModel):
    """Schema for creating a team."""
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Psychiatry",
                "description": "Mental health and psychiatric care department"
            }
        }
    )


class TeamUpdate(BaseModel):
    """Schema for updating a team."""
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None


# ============== Team Member Schemas ==============

class TeamMemberInfo(BaseModel):
    """Schema for team member info in responses."""
    user_id: UUID
    first_name: str
    last_name: str
    email: str
    role: UserRole
    joined_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ============== Team Response Schemas ==============

class TeamResponse(BaseModel):
    """Schema for team response."""
    id: UUID
    name: str
    description: Optional[str]
    is_active: bool
    member_count: int = 0
    patient_count: int = 0
    created_at: datetime
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "Psychiatry",
                "description": "Mental health and psychiatric care department",
                "is_active": True,
                "member_count": 5,
                "patient_count": 42,
                "created_at": "2024-01-15T10:00:00Z"
            }
        }
    )


class TeamDetailResponse(TeamResponse):
    """Schema for detailed team response with members."""
    members: List[TeamMemberInfo] = []


class TeamListResponse(BaseModel):
    """Schema for paginated team list."""
    teams: List[TeamResponse]
    total: int
    skip: int
    limit: int


# ============== Team Action Schemas ==============

class AddMemberRequest(BaseModel):
    """Schema for adding a member to a team."""
    user_id: UUID
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "987e6543-e21c-45d6-b789-123456789abc"
            }
        }
    )


class AssignPatientRequest(BaseModel):
    """Schema for assigning/reassigning a patient to a team."""
    patient_id: UUID
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "patient_id": "456e7890-f12g-34h5-i678-901234567jkl"
            }
        }
    )


class BulkAssignPatientsRequest(BaseModel):
    """Schema for bulk assigning patients to a team."""
    patient_ids: List[UUID] = Field(..., min_length=1, max_length=100)
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "patient_ids": [
                    "456e7890-f12g-34h5-i678-901234567jkl",
                    "789a0123-b45c-67d8-e901-234567890mno"
                ]
            }
        }
    )
