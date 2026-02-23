"""
Appointment Reminder Model.

Tracks multi-channel reminders for appointments with cascade logic.
"""
import uuid
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, Enum, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_model import BaseModel


class ReminderChannel(str, enum.Enum):
    """Available notification channels for reminders."""
    EMAIL = "email"
    SMS = "sms"
    VOICE = "voice"


class ReminderStatus(str, enum.Enum):
    """Status of reminder execution."""
    SCHEDULED = "scheduled"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AppointmentReminder(BaseModel):
    """
    Tracks multi-channel reminders for appointments.
    
    Design:
    - One record per appointment reminder (can have multiple for different send times)
    - channels: ordered preference list (e.g., [email, sms, voice])
    - attempts: JSONB tracking per-channel delivery results
    
    Example attempts structure:
    {
        "email": {"sent_at": "2025-01-22T10:00:00Z", "status": "success", "message_id": "abc123"},
        "sms": {"sent_at": "2025-01-22T12:00:00Z", "status": "failed", "error": "Rate limit exceeded"},
        "voice": null
    }
    """
    __tablename__ = "appointment_reminders"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), 
        index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), 
        index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), 
        index=True
    )
    
    # Reminder strategy
    channels: Mapped[list] = mapped_column(JSONB, default=list)  # Ordered preference
    scheduled_send_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    
    # Execution tracking
    status: Mapped[ReminderStatus] = mapped_column(
        Enum(ReminderStatus), 
        default=ReminderStatus.SCHEDULED,
        index=True
    )
    attempts: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    # Idempotency key for preventing duplicate sends 
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    
    # Metadata
    created_by_agent: Mapped[str] = mapped_column(String(50), default="followup_specialist")
    reminder_type: Mapped[str] = mapped_column(String(50), default="appointment")  # appointment, followup, medication
    
    # Relationships
    appointment = relationship("Appointment", back_populates="reminders")
    patient = relationship("Patient")
    organization = relationship("Organization")
    
    __table_args__ = (
        Index("idx_reminder_scheduled_status", "scheduled_send_time", "status"),
        Index("idx_reminder_org_status", "organization_id", "status"),
    )
    
    def mark_channel_attempt(
        self, 
        channel: ReminderChannel, 
        status: str, 
        message_id: Optional[str] = None,
        error: Optional[str] = None
    ) -> None:
        """Record an attempt for a specific channel."""
        existing = self.attempts.get(channel.value, {})
        retry_count = existing.get("retry_count", 0)
        if status == "failed":
            retry_count += 1
        
        self.attempts[channel.value] = {
            "sent_at": datetime.now().isoformat(),
            "status": status,
            "message_id": message_id,
            "error": error,
            "retry_count": retry_count,
        }
    
    def get_next_channel(self) -> Optional[ReminderChannel]:
        """Get next untried channel from the preference list."""
        for channel in self.channels:
            channel_enum = ReminderChannel(channel) if isinstance(channel, str) else channel
            if channel_enum.value not in self.attempts:
                return channel_enum
            # Also try if previous attempt failed
            attempt = self.attempts.get(channel_enum.value, {})
            if attempt.get("status") == "failed":
                # Check retry count
                retry_count = attempt.get("retry_count", 0)
                if retry_count < 3:
                    return channel_enum
        return None
