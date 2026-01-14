import uuid
import enum
from datetime import date, datetime

from sqlalchemy import (
    String, Integer, Date, DateTime, ForeignKey, Enum, Text
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
