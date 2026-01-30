"""
Dashboard Notifier Service.

Broadcasts real-time updates to connected clinician dashboards via Redis Pub/Sub.
Clinicians connect via WebSocket and receive instant notifications when:
- New agent actions are created
- New alerts are generated
- Actions are resolved
"""
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from uuid import UUID
from enum import Enum

from app.core.redis import RedisManager
from app.utils.logger import logger


class DashboardEventType(str, Enum):
    """Types of events pushed to dashboard."""
    NEW_ACTION = "new_action"
    NEW_ALERT = "new_alert"
    ACTION_RESOLVED = "action_resolved"
    ALERT_RESOLVED = "alert_resolved"
    CYCLE_STARTED = "cycle_started"
    CYCLE_COMPLETED = "cycle_completed"


class DashboardNotifier:
    """
    Publishes dashboard updates to Redis for WebSocket subscribers.
    
    Usage:
        notifier = DashboardNotifier(organization_id)
        await notifier.notify_new_action(action_data)
        
    Channel format: dashboard:{organization_id}
    All clinicians in an org subscribe to the same channel.
    
    Performance:
        - Fire-and-forget: Failures don't block workflows
        - O(1) per notification
    """
    
    def __init__(self, organization_id: UUID):
        self.organization_id = organization_id
        self._channel = f"dashboard:{organization_id}"
    
    async def _publish(self, event_type: DashboardEventType, data: Dict[str, Any]) -> bool:
        """
        Publish event to Redis channel.
        
        Returns:
            True if published successfully, False otherwise
        """
        payload = {
            "type": event_type.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "organization_id": str(self.organization_id),
            "data": data
        }
        
        try:
            redis = RedisManager.get_client()
            await redis.publish(self._channel, json.dumps(payload))
            logger.debug(f"[DASHBOARD] Published {event_type.value} to {self._channel}")
            return True
        except RuntimeError:
            logger.debug("Redis not available for dashboard notifications")
            return False
        except Exception as e:
            logger.warning(f"Dashboard notification failed (non-blocking): {e}")
            return False
    
    async def notify_new_action(
        self,
        action_id: UUID,
        action_type: str,
        patient_id: UUID,
        patient_name: Optional[str] = None,
        ai_reasoning: Optional[str] = None,
        status: str = "pending"
    ) -> bool:
        """
        Notify dashboard of a new agent action.
        
        Complexity: O(1) time, O(1) space
        """
        return await self._publish(
            DashboardEventType.NEW_ACTION,
            {
                "action_id": str(action_id),
                "action_type": action_type,
                "patient_id": str(patient_id),
                "patient_name": patient_name,
                "ai_reasoning": ai_reasoning[:200] if ai_reasoning else None,
                "status": status
            }
        )
    
    async def notify_new_alert(
        self,
        alert_id: UUID,
        severity: str,
        title: str,
        patient_id: UUID,
        patient_name: Optional[str] = None
    ) -> bool:
        """
        Notify dashboard of a new alert.
        
        Complexity: O(1) time, O(1) space
        """
        return await self._publish(
            DashboardEventType.NEW_ALERT,
            {
                "alert_id": str(alert_id),
                "severity": severity,
                "title": title,
                "patient_id": str(patient_id),
                "patient_name": patient_name
            }
        )
    
    async def notify_action_resolved(
        self,
        action_id: UUID,
        action_type: str,
        reason: str
    ) -> bool:
        """
        Notify dashboard that an action was resolved.
        
        Complexity: O(1) time, O(1) space
        """
        return await self._publish(
            DashboardEventType.ACTION_RESOLVED,
            {
                "action_id": str(action_id),
                "action_type": action_type,
                "reason": reason
            }
        )
    
    async def notify_cycle_started(self, cycle_id: UUID) -> bool:
        """Notify that morning rounds have started."""
        return await self._publish(
            DashboardEventType.CYCLE_STARTED,
            {"cycle_id": str(cycle_id)}
        )
    
    async def notify_cycle_completed(
        self,
        cycle_id: UUID,
        actions_count: int,
        alerts_count: int
    ) -> bool:
        """Notify that morning rounds are complete with summary."""
        return await self._publish(
            DashboardEventType.CYCLE_COMPLETED,
            {
                "cycle_id": str(cycle_id),
                "actions_count": actions_count,
                "alerts_count": alerts_count
            }
        )
    
    @property
    def channel(self) -> str:
        """Get the Redis channel name for this organization."""
        return self._channel
