import uuid
import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, Enum, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_model import BaseModel

if TYPE_CHECKING:
    from app.models.calendar import CalendarIntegration


class UserRole(str, enum.Enum):
    """User roles within an organization."""
    ORG_OWNER = "org_owner"
    ORG_ADMIN = "org_admin"
    DOCTOR = "doctor"
    NURSE = "nurse"
    COORDINATOR = "coordinator"


class Organization(BaseModel):
    """Organization model - tenants of the platform."""
    __tablename__ = "organizations"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    license_number: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Specializations (e.g., ["hiv", "hypertension"])
    disease_specializations: Mapped[list] = mapped_column(JSONB, default=list)
    
    phone_settings: Mapped[dict | None] = mapped_column(JSONB)
    agent_settings: Mapped[dict | None] = mapped_column(JSONB)
    
    timezone: Mapped[str | None] = mapped_column(String(50), default="UTC")
    
    # Relationships
    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    teams = relationship("Team", back_populates="organization", cascade="all, delete-orphan")
    invitations = relationship("Invitation", back_populates="organization", cascade="all, delete-orphan")
    patients = relationship("Patient", back_populates="organization", cascade="all, delete-orphan")


class Team(BaseModel):
    """Team/Department within an organization (e.g., Psychiatry, Surgery)."""
    __tablename__ = "teams"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Relationships
    organization = relationship("Organization", back_populates="teams")
    members = relationship("User", back_populates="team", foreign_keys="User.team_id")
    patients = relationship("Patient", back_populates="team")
    invitations = relationship("Invitation", back_populates="team", foreign_keys="Invitation.team_id")
    
    __table_args__ = (
        Index("idx_teams_org_name", "organization_id", "name", unique=True),
    )


class User(BaseModel):
    """User model - healthcare workers who use the platform."""
    __tablename__ = "users"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True)
    
    # Identity
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    
    # Profile
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(20))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    
    # Role
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.COORDINATOR)
    
    # Specialization & Skills
    specialization: Mapped[str | None] = mapped_column(String(255))
    skills: Mapped[list] = mapped_column(JSONB, default=list)
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Security
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    failed_login_attempts: Mapped[int] = mapped_column(default=0)
    lockout_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Metadata
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_ip: Mapped[str | None] = mapped_column(String(45))
    
    # Relationships
    organization = relationship("Organization", back_populates="users")
    team = relationship("Team", back_populates="members", foreign_keys=[team_id])
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    sent_invitations = relationship("Invitation", back_populates="invited_by_user", foreign_keys="Invitation.invited_by")
    calendar_integrations: Mapped[list["CalendarIntegration"]] = relationship(
        "CalendarIntegration", back_populates="user", cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        Index("idx_users_org_role", "organization_id", "role"),
        Index("idx_users_team", "team_id"),
    )
    
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class RefreshToken(BaseModel):
    """Refresh token model for session management."""
    __tablename__ = "refresh_tokens"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    
    token: Mapped[str] = mapped_column(Text, unique=True, index=True)
    device_info: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    user = relationship("User", back_populates="refresh_tokens")
    
    __table_args__ = (
        Index("idx_refresh_tokens_expires", "expires_at"),
    )


class InvitationStatus(str, enum.Enum):
    """Invitation status."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class Invitation(BaseModel):
    """Invitation model for inviting workers to an organization."""
    __tablename__ = "invitations"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True)
    
    email: Mapped[str] = mapped_column(String(255), index=True)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole))
    
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[InvitationStatus] = mapped_column(Enum(InvitationStatus), default=InvitationStatus.PENDING)
    
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    organization = relationship("Organization", back_populates="invitations")
    team = relationship("Team", back_populates="invitations", foreign_keys=[team_id])
    invited_by_user = relationship("User", back_populates="sent_invitations", foreign_keys=[invited_by])


class PasswordResetToken(BaseModel):
    """Password reset token model."""
    __tablename__ = "password_reset_tokens"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    user = relationship("User")


class EmailVerificationToken(BaseModel):
    """Email verification token model."""
    __tablename__ = "email_verification_tokens"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    user = relationship("User")


class AuditLog(BaseModel):
    """Audit log for tracking authentication and authorization events."""
    __tablename__ = "audit_logs"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), index=True)
    
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict | None] = mapped_column(JSONB)
    
    ip_address: Mapped[str | None] = mapped_column(String(45))


# Import Patient at end to avoid circular imports
from app.models.patient import Patient  # noqa: E402, F401