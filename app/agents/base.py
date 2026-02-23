from abc import ABC, abstractmethod
from typing import Any, List
from app.agents.context import AgentContext, WorkerResult

class BaseAgent(ABC):
    """Base class for all agents."""
    def __init__(self, name: str):
        self.name = name

class BaseWorker(BaseAgent):
    """Base class for specialist worker agents (Specialist Doctors)."""
    
    @abstractmethod
    async def run(self, context: AgentContext) -> WorkerResult:
        """Run the specialized analysis and return findings."""
        pass

class BaseSupervisor(BaseAgent):
    """Base class for supervisor agents (Head Doctor)."""
    
    def __init__(self, name: str, workers: List[BaseWorker]):
        super().__init__(name)
        self.workers = workers
        
    @abstractmethod
    async def run_cycle(self, organization_id: Any) -> AgentContext:
        """Coordinate the analysis cycle across all workers."""
        pass
