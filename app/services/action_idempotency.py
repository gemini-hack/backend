"""
Action Idempotency Service.

Provides utilities for checking if an action should be skipped
because a similar action was recently taken for the same patient.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
) -> dict:
    """
    Get set of patient IDs that have recent unresolved actions.
    
    Useful for batch checking before processing a list of patients.
    
    Returns:
        Dict mapping patient_id -> set of action_types they have
    
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


async def detect_and_resolve_outcomes(
    db: AsyncSession,
    organization_id: uuid.UUID
) -> Dict[str, int]:
    """
    Auto-detect and resolve actions based on patient data changes.
    
    Checks pending/sent actions and resolves them if:
    - Appointment reminders: appointment marked COMPLETED/ATTENDED
    - Engagement nudges: patient.last_reading_at updated since action
    - VL interventions: new lab result submitted since action
    
    Returns:
        Dict with counts of resolved actions by type
    

    """
    from app.models.patient import Patient
    from app.models.appointments import Appointment, AppointmentStatus
    
    resolved_counts = {
        "appointment_reminder": 0,
        "engagement_nudge": 0,
        "onboarding_reminder": 0,
        "vl_intervention": 0,
        "total": 0
    }
    
    # Get all pending/sent actions for this org
    query = select(AgentAction).options(
        selectinload(AgentAction.patient)
    ).where(
        and_(
            AgentAction.organization_id == organization_id,
            AgentAction.outcome.in_([ActionOutcome.PENDING, ActionOutcome.SENT])
        )
    )
    
    result = await db.execute(query)
    actions = result.scalars().all()
    
    for action in actions:
        patient = action.patient
        if not patient:
            continue
        
        resolved = False
        reason = ""
        
        # 1. Appointment Reminders - check if appointment is completed
        if action.action_type == "appointment_reminder":
            # Check if the appointment was completed
            if action.content and "appointment_id" in action.content:
                apt_id = action.content["appointment_id"]
                apt_query = select(Appointment).where(Appointment.id == apt_id)
                apt_result = await db.execute(apt_query)
                appointment = apt_result.scalar_one_or_none()
                
                if appointment and appointment.status in [
                    AppointmentStatus.COMPLETED,
                    AppointmentStatus.ATTENDED
                ]:
                    resolved = True
                    reason = f"Patient attended appointment on {appointment.scheduled_date}"
                    resolved_counts["appointment_reminder"] += 1
        
        # 2. Engagement/Onboarding Nudges - check if patient submitted reading
        elif action.action_type in ["engagement_nudge", "onboarding_reminder"]:
            if patient.last_reading_at and patient.last_reading_at > action.created_at:
                resolved = True
                reason = f"Patient submitted health reading on {patient.last_reading_at.date()}"
                resolved_counts[action.action_type] += 1
        
        # 3. VL Interventions - check for new lab results
        elif action.action_type in ["unsuppressed_vl_intervention", "low_level_viremia_review"]:
            # Check if HIV profile has newer VL result
            if hasattr(patient, 'hiv_profile') and patient.hiv_profile:
                profile = patient.hiv_profile
                if profile.last_viral_load_result_date and profile.last_viral_load_result_date > action.created_at.date():
                    resolved = True
                    reason = f"New VL result received: {profile.last_viral_load_result} on {profile.last_viral_load_result_date}"
                    resolved_counts["vl_intervention"] += 1
        
        # Mark as resolved if detected
        if resolved:
            action.outcome = ActionOutcome.RESOLVED
            action.outcome_detected_at = datetime.now(timezone.utc)
            action.outcome_reason = reason
            resolved_counts["total"] += 1
            logger.info(f"Auto-resolved action {action.id}: {reason}")
    
    return resolved_counts

