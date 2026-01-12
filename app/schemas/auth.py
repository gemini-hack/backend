from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict
import re

from app.models.user import UserRole


# ============== Password Validation ==============

def validate_password(password: str) -> str:
    """Validate password strength."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if len(password) > 128:
        raise ValueError("Password must not exceed 128 characters")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit")
    return password


# ============== Organization Schemas ==============

class OrganizationBase(BaseModel):
    """Base schema for organization."""
    name: str = Field(..., min_length=2, max_length=255)
    type: str = Field(..., min_length=2, max_length=50)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=20)
    license_number: Optional[str] = Field(None, max_length=100)


class OrganizationCreate(OrganizationBase):
    """Schema for creating an organization during registration."""
    pass


class OrganizationResponse(OrganizationBase):
    """Schema for organization response."""
    id: UUID
    is_active: bool
    is_onboarded: bool
    disease_specializations: List[str] = Field(default_factory=list)
    created_at: datetime
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "St. Mary's Hospital",
                "type": "hospital",
                "email": "admin@stmarys.com",
                "phone": "+1234567890",
                "license_number": "HSP-2024-001",
                "is_active": True,
                "is_onboarded": True,
                "created_at": "2024-01-10T10:00:00Z"
            }
        }
    )


# ============== User Schemas ==============

class UserBase(BaseModel):
    """Base schema for user."""
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)


class UserCreate(UserBase):
    """Schema for creating a user (owner during registration)."""
    password: str = Field(..., min_length=8, max_length=128)
    
    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        return validate_password(v)


class UserResponse(UserBase):
    """Schema for user response."""
    id: UUID
    role: UserRole
    is_active: bool
    email_verified: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "987e6543-e21c-45d6-b789-123456789abc",
                "email": "dr.smith@stmarys.com",
                "first_name": "John",
                "last_name": "Smith",
                "phone": "+1234567890",
                "role": "doctor",
                "is_active": True,
                "email_verified": True,
                "created_at": "2024-01-10T10:00:00Z",
                "last_login_at": "2024-01-10T15:30:00Z"
            }
        }
    )


class UserWithOrgResponse(UserResponse):
    """Schema for user response including organization."""
    organization: OrganizationResponse
    
    model_config = ConfigDict(from_attributes=True)


class UserProfileUpdate(BaseModel):
    """Schema for updating user profile."""
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)


# ============== Registration Schemas ==============

class RegisterRequest(BaseModel):
    """Schema for organization + owner registration."""
    # Organization details
    organization_name: str = Field(..., min_length=2, max_length=255)
    organization_type: str = Field(..., min_length=2, max_length=50)
    
    # Owner details
    owner_email: EmailStr
    owner_password: str = Field(..., min_length=8, max_length=128)
    owner_first_name: str = Field(..., min_length=1, max_length=100)
    owner_last_name: str = Field(..., min_length=1, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    
    @field_validator("owner_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        return validate_password(v)
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "organization_name": "St. Mary's Hospital",
                "organization_type": "hospital",
                "owner_email": "admin@stmarys.com",
                "owner_password": "SecurePass123",
                "owner_first_name": "Jane",
                "owner_last_name": "Doe",
                "phone": "+1234567890"
            }
        }
    )


class RegisterResponse(BaseModel):
    """Schema for registration response."""
    message: str
    organization_id: UUID
    user_id: UUID
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Registration successful. Please verify your email.",
                "organization_id": "123e4567-e89b-12d3-a456-426614174000",
                "user_id": "987e6543-e21c-45d6-b789-123456789abc"
            }
        }
    )


# ============== Login Schemas ==============

class LoginRequest(BaseModel):
    """Schema for login request."""
    email: EmailStr
    password: str
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "dr.smith@stmarys.com",
                "password": "SecurePass123"
            }
        }
    )


class TokenResponse(BaseModel):
    """Schema for token response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4...",
                "token_type": "bearer",
                "expires_in": 1800
            }
        }
    )


class LoginResponse(TokenResponse):
    """Schema for login response including user info."""
    user: UserWithOrgResponse
    
    model_config = ConfigDict(from_attributes=True)


class RefreshRequest(BaseModel):
    """Schema for token refresh request."""
    refresh_token: str
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4..."
            }
        }
    )


class RefreshResponse(BaseModel):
    """Schema for token refresh response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 1800
            }
        }
    )


# ============== Password Schemas ==============

class ChangePasswordRequest(BaseModel):
    """Schema for changing password."""
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)
    
    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        return validate_password(v)
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "current_password": "OldPass123",
                "new_password": "NewSecurePass123"
            }
        }
    )


class ForgotPasswordRequest(BaseModel):
    """Schema for forgot password request."""
    email: EmailStr
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "dr.smith@stmarys.com"
            }
        }
    )


class ResetPasswordRequest(BaseModel):
    """Schema for password reset."""
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)
    
    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        return validate_password(v)
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "token": "reset-token-abc123",
                "new_password": "NewSecurePass123"
            }
        }
    )


# ============== Email Verification Schemas ==============

class VerifyEmailRequest(BaseModel):
    """Schema for email verification."""
    token: str
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "token": "verify-token-xyz789"
            }
        }
    )


class ResendVerificationRequest(BaseModel):
    """Schema for resending verification email."""
    email: EmailStr
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "dr.smith@stmarys.com"
            }
        }
    )


# ============== Invitation Schemas ==============

class InviteWorkerRequest(BaseModel):
    """Schema for inviting a worker."""
    email: EmailStr
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    role: UserRole = Field(...)
    
    @field_validator("role")
    @classmethod
    def validate_role(cls, v: UserRole) -> UserRole:
        if v == UserRole.ORG_OWNER:
            raise ValueError("Cannot invite someone as organization owner")
        return v
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "nurse@stmarys.com",
                "first_name": "Sarah",
                "last_name": "Johnson",
                "role": "nurse"
            }
        }
    )


class InvitationResponse(BaseModel):
    """Schema for invitation response."""
    id: UUID
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    role: UserRole
    status: str
    expires_at: datetime
    created_at: datetime
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "456e7890-f12g-34h5-i678-901234567def",
                "email": "nurse@stmarys.com",
                "first_name": "Sarah",
                "last_name": "Johnson",
                "role": "nurse",
                "status": "pending",
                "expires_at": "2024-01-17T10:00:00Z",
                "created_at": "2024-01-10T10:00:00Z"
            }
        }
    )


class InvitationDetailsResponse(BaseModel):
    """Schema for invitation details (for accept page)."""
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    role: UserRole
    organization_name: str
    inviter_name: str
    expires_at: datetime
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "nurse@stmarys.com",
                "first_name": "Sarah",
                "last_name": "Johnson",
                "role": "nurse",
                "organization_name": "St. Mary's Hospital",
                "inviter_name": "Jane Doe",
                "expires_at": "2024-01-17T10:00:00Z"
            }
        }
    )


class AcceptInvitationRequest(BaseModel):
    """Schema for accepting an invitation."""
    token: str
    password: str = Field(..., min_length=8, max_length=128)
    
    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        return validate_password(v)
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "token": "invite-token-abc123",
                "password": "SecurePass123"
            }
        }
    )


# ============== Session Schemas ==============

class SessionResponse(BaseModel):
    """Schema for session response."""
    id: UUID
    device_info: Optional[str]
    ip_address: Optional[str]
    last_used_at: Optional[datetime]
    created_at: datetime
    is_current: bool = False
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "789e0123-g45h-67i8-j901-234567890ghi",
                "device_info": "Chrome 120.0 on Windows 10",
                "ip_address": "192.168.1.100",
                "last_used_at": "2024-01-10T15:30:00Z",
                "created_at": "2024-01-10T10:00:00Z",
                "is_current": True
            }
        }
    )


# ============== Generic Responses ==============

class MessageResponse(BaseModel):
    """Generic message response."""
    message: str
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Operation completed successfully"
            }
        }
    )


class ErrorResponse(BaseModel):
    """Error response."""
    detail: str
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "Invalid credentials"
            }
        }
    )
