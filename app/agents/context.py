from typing import Any, Dict, List, Optional, TYPE_CHECKING
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
import uuid

if TYPE_CHECKING:
    from app.agents.thought_emitter import ThoughtEmitter


class AgentAction(BaseModel):
    """A proposed action from an agent."""
    model_config = ConfigDict(extra='forbid')

    type: str
    target_id: str
    content: Dict[str, Any] = Field(default_factory=dict)
    reasoning: str
    confidence: float = 1.0
    status: str = "pending"


class WorkerResult(BaseModel):
    """Result of a worker agent's analysis."""
    worker_name: str
    findings: List[str] = Field(default_factory=list)
    flagged_patients: List[uuid.UUID] = Field(default_factory=list)
    proposed_actions: List[AgentAction] = Field(default_factory=list)
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)


class StepResult(BaseModel):
    """Result of a single step in the agent loop."""
    step_name: str
    status: str  # "success", "failed", "skipped"
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class ReflectionVerdict(BaseModel):
    """The LLM's verdict after reflecting on a completed round."""
    model_config = ConfigDict(extra='forbid')

    is_complete: bool
    reasoning: str
    gaps: List[str] = Field(default_factory=list)
    retry_workers: List[str] = Field(default_factory=list)
    additional_context: Dict[str, Any] = Field(default_factory=dict)


class AgentContext(BaseModel):
    """The 'Whiteboard' - shared context for the multi-agent analysis cycle."""
    organization_id: uuid.UUID
    cycle_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    start_time: datetime = Field(default_factory=datetime.now)

    # The whiteboard data
    data: Dict[str, Any] = Field(default_factory=dict)

    # Results from various workers
    worker_results: Dict[str, WorkerResult] = Field(default_factory=dict)

    # Final decisions made by the Supervisor
    final_actions: List[AgentAction] = Field(default_factory=list)

    # Multi-step tracking
    step_history: List[StepResult] = Field(default_factory=list)
    current_round: int = 0
    max_rounds: int = 3  # Hard cap — never exceed this

    # Thought emitter for streaming (private, not serialized)
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Internal emitter reference (set via set_emitter)
    _emitter: Optional["ThoughtEmitter"] = None

    def set_emitter(self, emitter: "ThoughtEmitter") -> None:
        """Attach a ThoughtEmitter for real-time streaming."""
        object.__setattr__(self, '_emitter', emitter)

    @property
    def emitter(self) -> Optional["ThoughtEmitter"]:
        """Get the attached ThoughtEmitter, if any."""
        return getattr(self, '_emitter', None)

    def set(self, key: str, value: Any):
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def add_worker_result(self, result: WorkerResult):
        self.worker_results[result.worker_name] = result

    def add_step(self, step_name: str, status: str, output: Dict[str, Any] = None, error: str = None):
        """Record a completed step for reflection."""
        self.step_history.append(StepResult(
            step_name=step_name,
            status=status,
            output=output or {},
            error=error
        ))
