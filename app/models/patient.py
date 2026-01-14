import uuid
import enum
from datetime import datetime, date
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    String, Text, Boolean, Integer, Float, Date, DateTime, ForeignKey, Enum, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_model import BaseModel
from app.models.conditions import Condition

if TYPE_CHECKING:
    from app.models.conditions import HIVProfile, HypertensionProfile, DiabetesProfile
    from app.models.agent import Alert, AgentAction, ScheduledCheck


class Gender(str, enum.Enum):
    """Patient gender options."""
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class PatientStatus(str, enum.Enum):
    """Patient monitoring status."""
    ACTIVE = "active"
    ACTIVE_DEFAULTER = "active_defaulter"
    IIT = "iit"
    INACTIVE = "inactive"
    PAUSED = "paused"
    DISCHARGED = "discharged"
    TRANSFERRED_OUT = "transferred_out"
    DEAD = "dead"


class CommunicationPreference(str, enum.Enum):
    """Communication preferences."""
    SMS = "sms"
    CALL = "call"
    EMAIL = "email"
    IN_APP = "in_app"


class Patient(BaseModel):
    """
    Patient model - represents a patient record managed by an organization.
    
    Note: Patients are DATA RECORDS, not platform users. They don't log in.
    Healthcare workers manage patient records on their behalf.
    """
    __tablename__ = "patients"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    
    patient_uid: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    
    # Demographics
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    date_of_birth: Mapped[date] = mapped_column(Date)
    gender: Mapped[Gender | None] = mapped_column(Enum(Gender))
    
    # Contact
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    
    # Emergency contact
    emergency_contact_name: Mapped[str | None] = mapped_column(String(200))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(20))
    emergency_contact_relationship: Mapped[str | None] = mapped_column(String(50))
    
    # Medical
    primary_condition: Mapped[Condition] = mapped_column(Enum(Condition))
    secondary_conditions: Mapped[list] = mapped_column(JSONB, default=list)
    medical_history: Mapped[str | None] = mapped_column(Text)
    current_medications: Mapped[list] = mapped_column(JSONB, default=list)
    allergies: Mapped[list] = mapped_column(JSONB, default=list)
    
    # Care team
    primary_physician_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assigned_nurse_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    care_coordinator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    
    # Monitoring
    status: Mapped[PatientStatus] = mapped_column(Enum(PatientStatus), default=PatientStatus.ACTIVE)
    monitoring_frequency: Mapped[str] = mapped_column(String(50), default="daily")
    preferred_contact_method: Mapped[CommunicationPreference] = mapped_column(Enum(CommunicationPreference), default=CommunicationPreference.SMS)
    preferred_contact_time: Mapped[str | None] = mapped_column(String(50))
    preferred_language: Mapped[str] = mapped_column(String(10), default="en")
    
    # Agent Settings
    agent_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_call_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_thresholds: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    # Metadata
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    custom_fields: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reading_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    organization = relationship("Organization", back_populates="patients")
    primary_physician = relationship("User", foreign_keys=[primary_physician_id])
    assigned_nurse = relationship("User", foreign_keys=[assigned_nurse_id])
    care_coordinator = relationship("User", foreign_keys=[care_coordinator_id])
    
    # Modular Relationships
    hiv_profile: Mapped[Optional["HIVProfile"]] = relationship("HIVProfile", back_populates="patient", uselist=False, cascade="all, delete-orphan")
    hypertension_profile: Mapped[Optional["HypertensionProfile"]] = relationship("HypertensionProfile", back_populates="patient", uselist=False, cascade="all, delete-orphan")
    diabetes_profile: Mapped[Optional["DiabetesProfile"]] = relationship("DiabetesProfile", back_populates="patient", uselist=False, cascade="all, delete-orphan")
    health_readings = relationship("HealthReading", back_populates="patient", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="patient", cascade="all, delete-orphan")
    agent_actions = relationship("AgentAction", back_populates="patient", cascade="all, delete-orphan")
    scheduled_checks = relationship("ScheduledCheck", back_populates="patient", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_patients_primary_condition", "primary_condition"),
        Index("idx_patients_status", "status"),
        Index("idx_patients_last_reading", "last_reading_at"),
    )


class HealthReading(BaseModel):
    """Health data readings for a patient."""
    __tablename__ = "health_readings"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    
    # Reading
    reading_type: Mapped[str] = mapped_column(String(50), index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    secondary_value: Mapped[float | None] = mapped_column(Float)
    secondary_unit: Mapped[str | None] = mapped_column(String(20))
    
    # Context
    reading_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    context: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    
    # Source
    source: Mapped[str] = mapped_column(String(50), default="manual")
    device_id: Mapped[str | None] = mapped_column(String(100))
    
    # Analysis
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    anomaly_score: Mapped[float | None] = mapped_column(Float)
    ai_analysis: Mapped[dict | None] = mapped_column(JSONB)
    
    # Relationships
    patient = relationship("Patient", back_populates="health_readings")
    organization = relationship("Organization")
    recorded_by = relationship("User")
