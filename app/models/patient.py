import uuid
import enum
from datetime import datetime, date

from sqlalchemy import (
    String, Text, Boolean, Integer, Float, Date, DateTime, ForeignKey, Enum, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_model import BaseModel


class Condition(str, enum.Enum):
    """Chronic conditions supported by the platform."""
    DIABETES = "diabetes"
    HYPERTENSION = "hypertension"
    HEART_DISEASE = "heart_disease"
    COPD = "copd"
    KIDNEY_DISEASE = "kidney_disease"
    ASTHMA = "asthma"
    OTHER = "other"


class Gender(str, enum.Enum):
    """Patient gender options."""
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class PatientStatus(str, enum.Enum):
    """Patient monitoring status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PAUSED = "paused"
    DISCHARGED = "discharged"


class AlertSeverity(str, enum.Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    URGENT = "urgent"
    CRITICAL = "critical"


class AlertStatus(str, enum.Enum):
    """Alert handling status."""
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


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
    preferred_contact_method: Mapped[str] = mapped_column(String(20), default="sms")
    preferred_contact_time: Mapped[str | None] = mapped_column(String(50))
    preferred_language: Mapped[str] = mapped_column(String(10), default="en")
    
    # Agent
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
    health_readings = relationship("HealthReading", back_populates="patient", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="patient", cascade="all, delete-orphan")
    agent_actions = relationship("AgentAction", back_populates="patient", cascade="all, delete-orphan")
    
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


class Alert(BaseModel):
    """Alerts generated by the system or AI agent."""
    __tablename__ = "alerts"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    health_reading_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("health_readings.id", ondelete="SET NULL"))
    
    # Alert
    severity: Mapped[AlertSeverity] = mapped_column(Enum(AlertSeverity), index=True)
    status: Mapped[AlertStatus] = mapped_column(Enum(AlertStatus), default=AlertStatus.PENDING, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    
    # AI
    ai_assessment: Mapped[dict | None] = mapped_column(JSONB)
    recommended_actions: Mapped[list] = mapped_column(JSONB, default=list)
    
    # Resolution
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    
    # Relationships
    patient = relationship("Patient", back_populates="alerts")
    organization = relationship("Organization")
    health_reading = relationship("HealthReading")
    acknowledged_by = relationship("User", foreign_keys=[acknowledged_by_id])
    resolved_by = relationship("User", foreign_keys=[resolved_by_id])


class AgentAction(BaseModel):
    """Actions taken by the AI health agent."""
    __tablename__ = "agent_actions"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    triggered_by_reading_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("health_readings.id", ondelete="SET NULL"))
    triggered_by_alert_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alerts.id", ondelete="SET NULL"))
    
    # Action
    action_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    content: Mapped[dict | None] = mapped_column(JSONB)
    recipient: Mapped[str | None] = mapped_column(String(255))
    
    # Execution
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # AI
    ai_reasoning: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    
    # Relationships
    patient = relationship("Patient", back_populates="agent_actions")
    organization = relationship("Organization")
    triggered_by_reading = relationship("HealthReading")
    triggered_by_alert = relationship("Alert")


class ScheduledCheck(BaseModel):
    """Scheduled health checks for patients."""
    __tablename__ = "scheduled_checks"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    
    # Schedule
    check_type: Mapped[str] = mapped_column(String(50))
    scheduled_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recurrence: Mapped[str | None] = mapped_column(String(50))
    recurrence_config: Mapped[dict | None] = mapped_column(JSONB)
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    
    # Relationships
    patient = relationship("Patient")
    organization = relationship("Organization")
