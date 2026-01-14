import uuid
import enum
from datetime import date, datetime

from sqlalchemy import (
    String, Integer, Date, DateTime, ForeignKey, Enum, Text, Boolean, Float
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_model import BaseModel


class Condition(str, enum.Enum):
    """Chronic conditions supported by the platform."""
    DIABETES = "diabetes"
    HYPERTENSION = "hypertension"
    HEART_DISEASE = "heart_disease"
    COPD = "copd"
    KIDNEY_DISEASE = "kidney_disease"
    ASTHMA = "asthma"
    HIV = "hiv"
    OTHER = "other"


class HIVProfile(BaseModel):
    """HIV-specific clinical data."""
    __tablename__ = "hiv_profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), unique=True, index=True)
    
    # Diagnosis & Treatment
    date_of_diagnosis: Mapped[date | None] = mapped_column(Date)
    art_start_date: Mapped[date | None] = mapped_column(Date)
    
    # Baseline Metrics
    baseline_viral_load: Mapped[int | None] = mapped_column(Integer)
    baseline_cd4_count: Mapped[int | None] = mapped_column(Integer)
    
    # Regimen
    initial_art_regimen: Mapped[str | None] = mapped_column(String(255))
    current_art_regimen: Mapped[str | None] = mapped_column(String(255))
    
    # Refill Tracking
    last_refill_date: Mapped[date | None] = mapped_column(Date)
    refill_months: Mapped[int | None] = mapped_column(Integer)
    next_refill_date: Mapped[date | None] = mapped_column(Date)
    
    # Viral Load History
    last_viral_load_sample_date: Mapped[date | None] = mapped_column(Date)
    last_viral_load_result_date: Mapped[date | None] = mapped_column(Date)
    last_viral_load_result: Mapped[int | None] = mapped_column(Integer)
    
    # Relationships
    patient = relationship("Patient", back_populates="hiv_profile")


class HypertensionProfile(BaseModel):
    """Hypertension-specific clinical data."""
    __tablename__ = "hypertension_profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), unique=True, index=True)
    
    # Diagnosis
    date_of_diagnosis: Mapped[date | None] = mapped_column(Date)
    
    # Baseline & Targets
    baseline_systolic: Mapped[int | None] = mapped_column(Integer)
    baseline_diastolic: Mapped[int | None] = mapped_column(Integer)
    target_systolic: Mapped[int | None] = mapped_column(Integer, default=130)
    target_diastolic: Mapped[int | None] = mapped_column(Integer, default=80)
    
    # Treatment
    current_medication: Mapped[str | None] = mapped_column(String(255))
    medication_start_date: Mapped[date | None] = mapped_column(Date)
    
    # Comorbidities (affect treatment targets)
    has_diabetes: Mapped[bool] = mapped_column(Boolean, default=False)
    has_kidney_disease: Mapped[bool] = mapped_column(Boolean, default=False)
    has_heart_disease: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Last Checkup
    last_checkup_date: Mapped[date | None] = mapped_column(Date)
    next_checkup_date: Mapped[date | None] = mapped_column(Date)
    
    # Relationships
    patient = relationship("Patient", back_populates="hypertension_profile")


class DiabetesProfile(BaseModel):
    """Diabetes-specific clinical data."""
    __tablename__ = "diabetes_profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), unique=True, index=True)
    
    # Diagnosis
    date_of_diagnosis: Mapped[date | None] = mapped_column(Date)
    diabetes_type: Mapped[str | None] = mapped_column(String(20))
    
    # Baseline & Targets
    baseline_hba1c: Mapped[float | None] = mapped_column(Float)
    target_hba1c: Mapped[float | None] = mapped_column(Float, default=7.0)
    baseline_fasting_glucose: Mapped[float | None] = mapped_column(Float)
    target_fasting_glucose: Mapped[float | None] = mapped_column(Float, default=100.0)
    
    # Treatment
    current_treatment: Mapped[str | None] = mapped_column(String(255))
    insulin_regimen: Mapped[str | None] = mapped_column(String(255))
    
    # Monitoring
    last_hba1c_date: Mapped[date | None] = mapped_column(Date)
    last_hba1c_result: Mapped[float | None] = mapped_column(Float)
    
    # Complications Screening
    last_eye_exam_date: Mapped[date | None] = mapped_column(Date)
    last_foot_exam_date: Mapped[date | None] = mapped_column(Date)
    last_kidney_function_date: Mapped[date | None] = mapped_column(Date)
    
    # Relationships
    patient = relationship("Patient", back_populates="diabetes_profile")
