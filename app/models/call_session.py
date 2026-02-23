import uuid
import enum
from datetime import datetime
from typing import List

from sqlalchemy import String, Text, Integer, ForeignKey, Enum as SAEnum, Index, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_model import BaseModel


class CallType(str, enum.Enum):
    """Type of phone call."""
    OUTBOUND_REMINDER = "outbound_reminder"
    OUTBOUND_FOLLOWUP = "outbound_followup"
    OUTBOUND_ALERT = "outbound_alert"
    OUTBOUND_MANUAL = "outbound_manual"
    INBOUND = "inbound"


class CallStatus(str, enum.Enum):
    """Status of the call session."""
    INITIATED = "initiated"
    RINGING = "ringing"
    ANSWERED = "answered"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    CANCELLED = "cancelled"


class CallSession(BaseModel):
    """
    Tracks phone call sessions via LiveKit SIP.
    
    Each call session represents one phone call between MIRA and a patient.
    """
    __tablename__ = "call_sessions"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    
    # LiveKit room identifier
    room_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    
    # Links
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), 
        index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True
    )
    triggered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    
    # Call details
    call_type: Mapped[CallType] = mapped_column(SAEnum(CallType))
    status: Mapped[CallStatus] = mapped_column(
        SAEnum(CallStatus), 
        default=CallStatus.INITIATED
    )
    from_number: Mapped[str] = mapped_column(String(20))
    to_number: Mapped[str] = mapped_column(String(20))
    
    # Timestamps
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    
    # Context and results
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    transcript: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String(100))
    
    # Error tracking
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationships
    patient = relationship("Patient")
    organization = relationship("Organization")
    triggered_by = relationship("User")
    actions: Mapped[List["CallAction"]] = relationship(
        "CallAction", 
        back_populates="call_session", 
        cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        Index("idx_call_sessions_status", "status"),
        Index("idx_call_sessions_call_type", "call_type"),
        Index("idx_call_sessions_started_at", "started_at"),
    )


class CallAction(BaseModel):
    """
    Tracks agent actions during a call.
    
    Records tool invocations made by MIRA during voice calls for auditability.
    """
    __tablename__ = "call_actions"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    
    # Link to parent call session
    call_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("call_sessions.id", ondelete="CASCADE"),
        index=True
    )
    
    # Action details
    action_type: Mapped[str] = mapped_column(String(50))  # "reschedule", "lookup_patient", etc.
    action_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[str | None] = mapped_column(String(20))  # "success", "failed", "pending"
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    
    # Relationship
    call_session: Mapped["CallSession"] = relationship("CallSession", back_populates="actions")
    
    __table_args__ = (
        Index("idx_call_actions_session", "call_session_id"),
        Index("idx_call_actions_type", "action_type"),
    )
