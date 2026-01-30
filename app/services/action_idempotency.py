"""
Action Idempotency Service.

Provides utilities for checking if an action should be skipped
because a similar action was recently taken for the same patient.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentAction, ActionOutcome
from app.utils.logger import logger


# Cooldown period before same action type can be proposed again
ACTION_COOLDOWN_HOURS = 48


async def has_recent_pending_action(
    db: AsyncSession,
    patient_id: uuid.UUID,
    action_type: str,
    cooldown_hours: int = ACTION_COOLDOWN_HOURS
) -> bool:
    """
    Check if patient has a recent action of the same type that is not resolved.
    
    Returns True if action should be SKIPPED (duplicate), False if OK to proceed.
    
    Args:
        db: Database session
        patient_id: Patient UUID
        action_type: Type of action (e.g., "engagement_nudge", "unsuppressed_vl_intervention")
        cooldown_hours: Hours to look back (default 48)
    
    Time Complexity: O(1) - single DB query with indexes
    Space Complexity: O(1) - returns boolean
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)
    
    query = select(AgentAction.id).where(
        and_(
            AgentAction.patient_id == patient_id,
            AgentAction.action_type == action_type,
            AgentAction.created_at >= cutoff,
            # Skip if action is still pending, sent, or failed (not yet resolved/expired)
            AgentAction.outcome.in_([
                ActionOutcome.PENDING,
                ActionOutcome.SENT,
                ActionOutcome.FAILED  # Allow retry after cooldown even if failed
            ])
        )
    ).limit(1)
    
    result = await db.execute(query)
    existing = result.scalar_one_or_none()
    
    if existing:
        logger.debug(f"Skipping action {action_type} for patient {patient_id}: recent action exists")
        return True
    
    return False


async def get_patients_with_recent_actions(
    db: AsyncSession,
    organization_id: uuid.UUID,
    action_types: List[str],
    cooldown_hours: int = ACTION_COOLDOWN_HOURS
) -> set:
    """
    Get set of patient IDs that have recent unresolved actions.
    
    Useful for batch checking before processing a list of patients.
    
    Returns:
        Set of patient UUIDs that should be skipped
    
    Time Complexity: O(n) where n = number of recent actions
    Space Complexity: O(k) where k = unique patients with recent actions
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)
    
    query = select(AgentAction.patient_id, AgentAction.action_type).where(
        and_(
            AgentAction.organization_id == organization_id,
            AgentAction.action_type.in_(action_types),
            AgentAction.created_at >= cutoff,
            AgentAction.outcome.in_([
                ActionOutcome.PENDING,
                ActionOutcome.SENT,
                ActionOutcome.FAILED
            ])
        )
    )
    
    result = await db.execute(query)
    
    # Return dict mapping patient_id -> set of action_types they have
    patient_actions = {}
    for row in result:
        patient_id = row.patient_id
        action_type = row.action_type
        if patient_id not in patient_actions:
            patient_actions[patient_id] = set()
        patient_actions[patient_id].add(action_type)
    
    return patient_actions


async def mark_action_sent(
    db: AsyncSession,
    action_id: uuid.UUID,
    success: bool = True,
    error_message: Optional[str] = None
):
    """
    Update action outcome after execution attempt.
    
    Args:
        action_id: The AgentAction ID
        success: Whether delivery was successful
        error_message: Error details if failed
    """
    action = await db.get(AgentAction, action_id)
    if not action:
        logger.error(f"Action {action_id} not found for outcome update")
        return
    
    if success:
        action.outcome = ActionOutcome.SENT
        action.outcome_detected_at = datetime.now(timezone.utc)
        action.outcome_reason = "Notification delivered successfully"
    else:
        action.outcome = ActionOutcome.FAILED
        action.outcome_detected_at = datetime.now(timezone.utc)
        action.outcome_reason = error_message or "Delivery failed"
        action.error_message = error_message
    
    logger.info(f"Action {action_id} marked as {action.outcome.value}")


async def resolve_action(
    db: AsyncSession,
    action_id: uuid.UUID,
    reason: str
):
    """
    Mark action as resolved (patient took desired action).
    
    Args:
        action_id: The AgentAction ID
        reason: Human-readable resolution reason
    """
    action = await db.get(AgentAction, action_id)
    if not action:
        logger.error(f"Action {action_id} not found for resolution")
        return
    
    action.outcome = ActionOutcome.RESOLVED
    action.outcome_detected_at = datetime.now(timezone.utc)
    action.outcome_reason = reason
    
    logger.info(f"Action {action_id} resolved: {reason}")
