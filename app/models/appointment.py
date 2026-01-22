import uuid
import enum
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Enum, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_model import BaseModel

class AppointmentStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"

class Appointment(BaseModel):
    """Appointment model for patient visits."""
    __tablename__ = "appointments"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    
    scheduled_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    type: Mapped[str] = mapped_column(String(100))  # e.g., "Follow-up", "Lab Review"
    status: Mapped[AppointmentStatus] = mapped_column(Enum(AppointmentStatus), default=AppointmentStatus.SCHEDULED)
    notes: Mapped[str | None] = mapped_column(Text)
    
    # Priority & Escalation (0 = normal, higher = more urgent)
    priority_level: Mapped[int] = mapped_column(Integer, default=0, index=True)
    no_show_count: Mapped[int] = mapped_column(Integer, default=0)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    patient = relationship("Patient")
    provider = relationship("User")
    organization = relationship("Organization")
    reminders = relationship("AppointmentReminder", back_populates="appointment", cascade="all, delete-orphan")
