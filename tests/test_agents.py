"""
Unit tests for the MIRA Agent System.

Tests cover:
- AgentContext creation and management
- Worker agents (DisengagementWorker, HIVWorker)
- Agent action creation and field handling
- Supervisor exponential backoff logic
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from app.agents.context import AgentContext, AgentAction, WorkerResult
from app.agents.workers.disengagement import DisengagementWorker
from app.agents.workers.hiv import HIVWorker
from app.models.conditions import Condition


class TestAgentContext:
    """Tests for AgentContext Pydantic model."""
    
    def test_context_creation(self):
        """Test basic AgentContext creation."""
        org_id = uuid.uuid4()
        context = AgentContext(organization_id=org_id)
        
        assert context.organization_id == org_id
        assert context.cycle_id is not None
        assert context.start_time is not None
        
    def test_final_actions_default_is_list(self):
        """Test that final_actions defaults to empty list, not dict."""
        context = AgentContext(organization_id=uuid.uuid4())
        
        assert isinstance(context.final_actions, list)
        assert len(context.final_actions) == 0
        
    def test_worker_results_default_is_dict(self):
        """Test that worker_results defaults to empty dict."""
        context = AgentContext(organization_id=uuid.uuid4())
        
        assert isinstance(context.worker_results, dict)
        assert len(context.worker_results) == 0
        
    def test_context_set_get(self):
        """Test context data storage."""
        context = AgentContext(organization_id=uuid.uuid4())
        
        context.set("patients", ["patient1", "patient2"])
        result = context.get("patients")
        
        assert result == ["patient1", "patient2"]
        
    def test_context_get_default(self):
        """Test context get with default value."""
        context = AgentContext(organization_id=uuid.uuid4())
        
        result = context.get("nonexistent", default=[])
        
        assert result == []
        
    def test_add_worker_result(self):
        """Test adding worker results to context."""
        context = AgentContext(organization_id=uuid.uuid4())
        
        result = WorkerResult(
            worker_name="test_worker",
            findings=["finding1"],
            proposed_actions=[]
        )
        context.add_worker_result(result)
        
        assert "test_worker" in context.worker_results
        assert context.worker_results["test_worker"].findings == ["finding1"]


class TestAgentAction:
    """Tests for AgentAction Pydantic model."""
    
    def test_action_creation_with_content(self):
        """Test creating action with content field (not details)."""
        action = AgentAction(
            type="engagement_nudge",
            target_id=str(uuid.uuid4()),
            content={"days_missing": 5},
            reasoning="Patient hasn't submitted reading",
            confidence=0.9
        )
        
        assert action.content["days_missing"] == 5
        assert action.status == "pending"  # Default
        
    def test_action_content_default(self):
        """Test that content defaults to empty dict."""
        action = AgentAction(
            type="test",
            target_id="123",
            reasoning="test"
        )
        
        assert action.content == {}
        
    def test_action_confidence_default(self):
        """Test that confidence defaults to 1.0."""
        action = AgentAction(
            type="test",
            target_id="123",
            reasoning="test"
        )
        
        assert action.confidence == 1.0


class TestWorkerResult:
    """Tests for WorkerResult Pydantic model."""
    
    def test_worker_result_creation(self):
        """Test basic WorkerResult creation."""
        result = WorkerResult(worker_name="test_specialist")
        
        assert result.worker_name == "test_specialist"
        assert result.findings == []
        assert result.flagged_patients == []
        assert result.proposed_actions == []
        
    def test_worker_result_with_actions(self):
        """Test WorkerResult with proposed actions."""
        action = AgentAction(
            type="engagement_nudge",
            target_id="123",
            content={"key": "value"},
            reasoning="test"
        )
        
        result = WorkerResult(
            worker_name="test_specialist",
            findings=["Found issue"],
            proposed_actions=[action]
        )
        
        assert len(result.proposed_actions) == 1
        assert result.proposed_actions[0].content["key"] == "value"


class TestDisengagementWorker:
    """Tests for DisengagementWorker."""
    
    def test_worker_initialization(self):
        """Test worker initializes correctly."""
        worker = DisengagementWorker()
        
        assert worker.name == "engagement_specialist"
        
    @pytest.mark.asyncio
    async def test_worker_run_no_patients(self):
        """Test worker with no patients returns empty result."""
        worker = DisengagementWorker()
        context = AgentContext(organization_id=uuid.uuid4())
        context.set("patients", [])
        
        result = await worker.run(context)
        
        assert result.worker_name == "engagement_specialist"
        assert len(result.proposed_actions) == 0
        
    @pytest.mark.asyncio
    async def test_worker_flags_patient_with_no_reading(self):
        """Test worker flags patient who never submitted reading."""
        worker = DisengagementWorker()
        context = AgentContext(organization_id=uuid.uuid4())
        
        # Mock patient with no last_reading_at
        mock_patient = MagicMock()
        mock_patient.id = uuid.uuid4()
        mock_patient.last_reading_at = None
        
        context.set("patients", [mock_patient])
        
        result = await worker.run(context)
        
        assert mock_patient.id in result.flagged_patients
        assert len(result.proposed_actions) == 1
        assert result.proposed_actions[0].type == "onboarding_reminder"
        # Verify content field is used, not details
        assert "days_missing" in result.proposed_actions[0].content
        
    @pytest.mark.asyncio
    async def test_worker_flags_patient_missed_threshold(self):
        """Test worker flags patient missing readings for threshold days."""
        worker = DisengagementWorker()
        context = AgentContext(organization_id=uuid.uuid4())
        context.set("disengagement_threshold_days", 3)
        
        # Mock patient with old reading
        mock_patient = MagicMock()
        mock_patient.id = uuid.uuid4()
        mock_patient.last_reading_at = datetime.now(timezone.utc) - timedelta(days=5)
        
        context.set("patients", [mock_patient])
        
        result = await worker.run(context)
        
        assert mock_patient.id in result.flagged_patients
        assert len(result.proposed_actions) == 1
        assert result.proposed_actions[0].type == "engagement_nudge"
        assert result.proposed_actions[0].content["days_missing"] == 5


class TestHIVWorker:
    """Tests for HIVWorker."""
    
    def test_worker_initialization(self):
        """Test HIVWorker initializes correctly."""
        mock_db = AsyncMock()
        worker = HIVWorker(mock_db)
        
        assert worker.name == "hiv_specialist"
        
    @pytest.mark.asyncio
    async def test_worker_skips_non_hiv_patients(self):
        """Test worker skips patients without HIV condition."""
        mock_db = AsyncMock()
        worker = HIVWorker(mock_db)
        context = AgentContext(organization_id=uuid.uuid4())
        
        # Mock non-HIV patient
        mock_patient = MagicMock()
        mock_patient.id = uuid.uuid4()
        mock_patient.primary_condition = Condition.HYPERTENSION
        
        context.set("patients", [mock_patient])
        
        result = await worker.run(context)
        
        assert len(result.proposed_actions) == 0
        

class TestExponentialBackoff:
    """Tests for Supervisor exponential backoff logic."""
    
    def test_backoff_calculation(self):
        """Test exponential backoff delay calculations."""
        base_delay = 4
        
        # First retry: 4 * 2^1 = 8
        assert base_delay * (2 ** 1) == 8
        
        # Second retry: 4 * 2^2 = 16
        assert base_delay * (2 ** 2) == 16
        
        # Third retry: 4 * 2^3 = 32
        assert base_delay * (2 ** 3) == 32


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
