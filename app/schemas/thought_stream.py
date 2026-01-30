"""
Thought Stream Schemas.

Defines typed schemas for real-time agent thought streaming and decision trace persistence.
"""
from enum import Enum
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List
from uuid import UUID
from pydantic import BaseModel, Field


class ThoughtStage(str, Enum):
    """Stage in the agent decision pipeline."""
    LOADING_DATA = "loading_data"
    SPECIALIST_ANALYSIS = "specialist_analysis"
    SUPERVISOR_SYNTHESIS = "supervisor_synthesis"
    CRITIC_REVIEW = "critic_review"
    AUTO_EXECUTION = "auto_execution"
    COMPLETE = "complete"
    ERROR = "error"


class ThoughtEvent(BaseModel):
    """Real-time thought event for streaming."""
    cycle_id: UUID
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent_name: str
    stage: ThoughtStage
    content: str
    metadata: Optional[Dict[str, Any]] = None
    patient_id: Optional[UUID] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v),
        }


class SpecialistThought(BaseModel):
    """Record of a specialist's analysis."""
    role: str
    thoughts: List[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    patient_ids_flagged: List[str] = Field(default_factory=list)


class SupervisorDecision(BaseModel):
    """Record of supervisor's final decision."""
    reasoning: str
    confidence: float
    action_type: Optional[str] = None


class CriticReview(BaseModel):
    """Record of critic's safety review."""
    decision: str  # APPROVED, REJECTED, BASIC_APPROVED
    reasoning: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DecisionTrace(BaseModel):
    """
    Complete audit trail of agent decision-making.
    
    This is the "brain dump" that shows how each agent contributed
    to the final decision for a specific patient action.
    """
    specialists: List[SpecialistThought] = Field(default_factory=list)
    supervisor: Optional[SupervisorDecision] = None
    critic: Optional[CriticReview] = None
    execution_log: List[str] = Field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSONB storage."""
        return self.model_dump(mode="json")
