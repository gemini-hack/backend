from datetime import datetime, date
from typing import Optional
from uuid import UUID
import enum

from sqlalchemy import (
    Column,
    String,
    Text,
    Boolean,
    Integer,
    Float,
    Date,
    DateTime,
    ForeignKey,
    Enum,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base_model import Base


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


class Patient(Base):
    """
    Patient model - represents a patient record managed by an organization.
    
    Note: Patients are DATA RECORDS, not platform users. They don't log in.
    Healthcare workers manage patient records on their behalf.
    """
    __tablename__ = "patients"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    
    # Organization ownership
    organization_id = Column(PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    
    # Unique patient identifier (for external reference, not PII)
    patient_uid = Column(String(50), unique=True, nullable=False, index=True)
    
    # Demographics
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    date_of_birth = Column(Date, nullable=False)
    gender = Column(Enum(Gender), nullable=True)
    
    # Contact information
    phone = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    address = Column(Text, nullable=True)
    
    # Emergency contact
    emergency_contact_name = Column(String(200), nullable=True)
    emergency_contact_phone = Column(String(20), nullable=True)
    emergency_contact_relationship = Column(String(50), nullable=True)
    
    # Medical information
    primary_condition = Column(Enum(Condition), nullable=False)
    secondary_conditions = Column(JSONB, default=list)  # List of additional conditions
    medical_history = Column(Text, nullable=True)
    current_medications = Column(JSONB, default=list)  # List of medications
    allergies = Column(JSONB, default=list)  # List of allergies
    
    # Care team
    primary_physician_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_nurse_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    care_coordinator_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Monitoring settings
    status = Column(Enum(PatientStatus), default=PatientStatus.ACTIVE, nullable=False)
    monitoring_frequency = Column(String(50), default="daily")  # daily, twice_daily, weekly
    preferred_contact_method = Column(String(20), default="sms")  # sms, call, email
    preferred_contact_time = Column(String(50), nullable=True)  # e.g., "morning", "9:00-12:00"
    preferred_language = Column(String(10), default="en")
    
    # Agent settings
    agent_enabled = Column(Boolean, default=True)
    auto_call_enabled = Column(Boolean, default=False)
    alert_thresholds = Column(JSONB, default=dict)  # Custom thresholds per metric
    
    # Metadata
    notes = Column(Text, nullable=True)
    tags = Column(JSONB, default=list)
    custom_fields = Column(JSONB, default=dict)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_contact_at = Column(DateTime(timezone=True), nullable=True)
    last_reading_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    organization = relationship("Organization", back_populates="patients")
    primary_physician = relationship("User", foreign_keys=[primary_physician_id])
    assigned_nurse = relationship("User", foreign_keys=[assigned_nurse_id])
    care_coordinator = relationship("User", foreign_keys=[care_coordinator_id])
    health_readings = relationship("HealthReading", back_populates="patient", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="patient", cascade="all, delete-orphan")
    agent_actions = relationship("AgentAction", back_populates="patient", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index("ix_patients_organization_id", "organization_id"),
        Index("ix_patients_primary_condition", "primary_condition"),
        Index("ix_patients_status", "status"),
        Index("ix_patients_last_reading_at", "last_reading_at"),
    )


class HealthReading(Base):
    """Health data readings for a patient."""
    __tablename__ = "health_readings"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    
    # Relationships
    patient_id = Column(PGUUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    recorded_by_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Reading data
    reading_type = Column(String(50), nullable=False)  # blood_glucose, blood_pressure, heart_rate, etc.
    value = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False)
    
    # Additional values for compound readings (e.g., BP systolic/diastolic)
    secondary_value = Column(Float, nullable=True)
    secondary_unit = Column(String(20), nullable=True)
    
    # Context
    reading_time = Column(DateTime(timezone=True), nullable=False)  # When the reading was taken
    context = Column(String(50), nullable=True)  # fasting, post_meal, resting, etc.
    notes = Column(Text, nullable=True)
    
    # Source
    source = Column(String(50), default="manual")  # manual, device, csv_import, api
    device_id = Column(String(100), nullable=True)
    
    # Analysis
    is_anomaly = Column(Boolean, default=False)
    anomaly_score = Column(Float, nullable=True)  # 0-1 score from AI analysis
    ai_analysis = Column(JSONB, nullable=True)  # Full AI analysis result
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    patient = relationship("Patient", back_populates="health_readings")
    organization = relationship("Organization")
    recorded_by = relationship("User")
    
    # Indexes
    __table_args__ = (
        Index("ix_health_readings_patient_id", "patient_id"),
        Index("ix_health_readings_organization_id", "organization_id"),
        Index("ix_health_readings_reading_type", "reading_type"),
        Index("ix_health_readings_reading_time", "reading_time"),
        Index("ix_health_readings_is_anomaly", "is_anomaly"),
    )


class Alert(Base):
    """Alerts generated by the system or AI agent."""
    __tablename__ = "alerts"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    
    # Relationships
    patient_id = Column(PGUUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    health_reading_id = Column(PGUUID(as_uuid=True), ForeignKey("health_readings.id", ondelete="SET NULL"), nullable=True)
    
    # Alert details
    severity = Column(Enum(AlertSeverity), nullable=False)
    status = Column(Enum(AlertStatus), default=AlertStatus.PENDING, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # AI analysis
    ai_assessment = Column(JSONB, nullable=True)
    recommended_actions = Column(JSONB, default=list)
    
    # Resolution
    acknowledged_by_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    patient = relationship("Patient", back_populates="alerts")
    organization = relationship("Organization")
    health_reading = relationship("HealthReading")
    acknowledged_by = relationship("User", foreign_keys=[acknowledged_by_id])
    resolved_by = relationship("User", foreign_keys=[resolved_by_id])
    
    # Indexes
    __table_args__ = (
        Index("ix_alerts_patient_id", "patient_id"),
        Index("ix_alerts_organization_id", "organization_id"),
        Index("ix_alerts_severity", "severity"),
        Index("ix_alerts_status", "status"),
        Index("ix_alerts_created_at", "created_at"),
    )


class AgentAction(Base):
    """Actions taken by the AI health agent."""
    __tablename__ = "agent_actions"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    
    # Relationships
    patient_id = Column(PGUUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    triggered_by_reading_id = Column(PGUUID(as_uuid=True), ForeignKey("health_readings.id", ondelete="SET NULL"), nullable=True)
    triggered_by_alert_id = Column(PGUUID(as_uuid=True), ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True)
    
    # Action details
    action_type = Column(String(50), nullable=False)  # send_sms, send_email, schedule_call, alert_provider, etc.
    status = Column(String(20), default="pending")  # pending, in_progress, completed, failed
    
    # Content
    content = Column(JSONB, nullable=True)  # Message content, call script, etc.
    recipient = Column(String(255), nullable=True)  # Phone, email, or user ID
    
    # Execution
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)
    result = Column(JSONB, nullable=True)  # API response, call outcome, etc.
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    
    # AI context
    ai_reasoning = Column(Text, nullable=True)  # Why the agent took this action
    confidence_score = Column(Float, nullable=True)  # 0-1 confidence in decision
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    patient = relationship("Patient", back_populates="agent_actions")
    organization = relationship("Organization")
    triggered_by_reading = relationship("HealthReading")
    triggered_by_alert = relationship("Alert")
    
    # Indexes
    __table_args__ = (
        Index("ix_agent_actions_patient_id", "patient_id"),
        Index("ix_agent_actions_organization_id", "organization_id"),
        Index("ix_agent_actions_action_type", "action_type"),
        Index("ix_agent_actions_status", "status"),
        Index("ix_agent_actions_created_at", "created_at"),
    )


class ScheduledCheck(Base):
    """Scheduled health checks for patients."""
    __tablename__ = "scheduled_checks"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    
    # Relationships
    patient_id = Column(PGUUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    
    # Schedule
    check_type = Column(String(50), nullable=False)  # daily_check, weekly_review, medication_reminder
    scheduled_time = Column(DateTime(timezone=True), nullable=False)
    recurrence = Column(String(50), nullable=True)  # daily, weekly, monthly, custom
    recurrence_config = Column(JSONB, nullable=True)  # Custom recurrence settings
    
    # Status
    is_active = Column(Boolean, default=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    patient = relationship("Patient")
    organization = relationship("Organization")
    
    # Indexes
    __table_args__ = (
        Index("ix_scheduled_checks_patient_id", "patient_id"),
        Index("ix_scheduled_checks_next_run_at", "next_run_at"),
        Index("ix_scheduled_checks_is_active", "is_active"),
    )
