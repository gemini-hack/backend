from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict

from app.models.agent import AlertSeverity, AlertStatus

class AlertBase(BaseModel):
    """Base schema for alert."""
    severity: AlertSeverity
    status: AlertStatus = AlertStatus.PENDING
    title: str = Field(..., max_length=255)
    description: Optional[str] = None
    ai_assessment: Optional[dict] = None
    recommended_actions: List[dict] = Field(default_factory=list)

class AlertResponse(AlertBase):
    """Schema for alert response."""
    id: UUID
    patient_id: UUID
    organization_id: UUID
    health_reading_id: Optional[UUID] = None
    acknowledged_by_id: Optional[UUID] = None
    acknowledged_at: Optional[datetime] = None
    resolved_by_id: Optional[UUID] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    
    # Enriched fields (populated by router)
    patient_name: Optional[str] = None
    patient_uid: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class AgentActionBase(BaseModel):
    """Base schema for agent action."""
    action_type: str = Field(..., max_length=50)
    status: str = Field("pending", max_length=20)
    content: Optional[dict] = None
    recipient: Optional[str] = Field(None, max_length=255)
    ai_reasoning: Optional[str] = None
    confidence_score: Optional[float] = None

class AgentActionResponse(AgentActionBase):
    """Schema for agent action response."""
    id: UUID
    patient_id: UUID
    organization_id: UUID
    triggered_by_reading_id: Optional[UUID] = None
    triggered_by_alert_id: Optional[UUID] = None
    scheduled_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    created_at: datetime
    
    # Decision trace: Full audit trail of agent reasoning
    decision_trace: Optional[Dict[str, Any]] = None
    
    # Enriched fields (populated by router)
    patient_name: Optional[str] = None
    patient_uid: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class ScheduledCheckBase(BaseModel):
    """Base schema for scheduled check."""
    check_type: str = Field(..., max_length=50)
    scheduled_time: datetime
    recurrence: Optional[str] = Field(None, max_length=50)
    recurrence_config: Optional[dict] = None
    is_active: bool = True

class ScheduledCheckResponse(ScheduledCheckBase):
    """Schema for scheduled check response."""
    id: UUID
    patient_id: UUID
    organization_id: UUID
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
