"""
Thought Emitter for Real-Time Agent Streaming.

Broadcasts agent thoughts via Redis Pub/Sub for real-time frontend observation.
Uses the existing RedisManager for connection pooling.
"""
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import UUID

from app.core.redis import RedisManager
from app.schemas.thought_stream import ThoughtEvent, ThoughtStage
from app.utils.logger import logger


class ThoughtEmitter:
    """
    Emits agent thoughts to Redis Pub/Sub for real-time streaming.
    
    Usage:
        emitter = ThoughtEmitter(cycle_id, organization_id)
        await emitter.emit("hiv_specialist", ThoughtStage.SPECIALIST_ANALYSIS, "Analyzing viral load...")
        
    Performance:
        - Fire-and-forget: Failures don't block the workflow
        - Buffered locally: Thoughts are stored for persistence even if Redis fails
        - O(1) per emit operation
    """
    
    def __init__(self, cycle_id: UUID, organization_id: UUID):
        self.cycle_id = cycle_id
        self.organization_id = organization_id
        self._channel = f"thoughts:org:{organization_id}:cycle:{cycle_id}"
        self._thoughts: List[Dict[str, Any]] = []  # Local buffer for persistence
        self._enabled = True
    
    async def emit(
        self,
        agent_name: str,
        stage: ThoughtStage,
        content: str,
        patient_id: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Emit a thought event.
        
        Args:
            agent_name: Name of the agent emitting the thought
            stage: Current stage in the pipeline
            content: Human-readable thought content
            patient_id: Optional patient this thought relates to
            metadata: Optional additional data
            
        Complexity: O(1) time, O(1) space per event
        """
        if not self._enabled:
            return
            
        event = ThoughtEvent(
            cycle_id=self.cycle_id,
            timestamp=datetime.now(timezone.utc),
            agent_name=agent_name,
            stage=stage,
            content=content,
            patient_id=patient_id,
            metadata=metadata
        )
        
        # Buffer locally for persistence (always succeeds)
        event_dict = event.model_dump(mode="json")
        self._thoughts.append(event_dict)
        
        # Publish to Redis (non-blocking, failures are logged but don't break workflow)
        try:
            redis = RedisManager.get_client()
            await redis.publish(self._channel, json.dumps(event_dict))
            logger.debug(f"[THOUGHT] {agent_name}/{stage.value}: {content[:50]}...")
        except RuntimeError:
            # Redis not initialized - skip streaming but keep buffering
            logger.debug("Redis not available for thought streaming, events buffered locally")
        except Exception as e:
            # Any other Redis error - log and continue
            logger.warning(f"Thought publish failed (non-blocking): {e}")
    
    def get_all_thoughts(self) -> List[Dict[str, Any]]:
        """
        Return all buffered thoughts for persistence.
        
        Returns:
            List of thought event dictionaries
        """
        return self._thoughts.copy()
    
    def get_thoughts_for_patient(self, patient_id: UUID) -> List[Dict[str, Any]]:
        """
        Get thoughts related to a specific patient.
        
        Args:
            patient_id: Patient UUID to filter by
            
        Returns:
            List of thought events for this patient
        """
        patient_str = str(patient_id)
        return [
            t for t in self._thoughts 
            if t.get("patient_id") == patient_str
        ]
    
    def disable(self) -> None:
        """Disable thought emission (useful for testing)."""
        self._enabled = False
    
    def enable(self) -> None:
        """Re-enable thought emission."""
        self._enabled = True
    
    @property
    def channel(self) -> str:
        """Get the Redis channel name for this cycle."""
        return self._channel
