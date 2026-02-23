"""
Reminders API Routes.

Endpoints for manual reminder management and status checking.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.encoders import jsonable_encoder

from app.api.dependencies import CurrentUser, DbSession, require_permission
from app.models.appointment import Appointment, AppointmentStatus
from app.models.reminder import AppointmentReminder, ReminderChannel, ReminderStatus
from app.schemas.reminder import (
    ReminderResponse,
    ReminderListResponse,
    SendReminderNowRequest,
    ReminderCancelRequest,
)
from app.tasks.reminders import send_reminder
from app.utils.responses import success_response
from app.utils.exceptions import NotFoundException, BadRequestException
from app.utils.logger import logger


router = APIRouter(prefix="/reminders", tags=["Reminders"])


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=ReminderListResponse,
    summary="List reminders",
    dependencies=[Depends(require_permission("appointments:read"))],
)
async def list_reminders(
    user: CurrentUser,
    db: DbSession,
    reminder_status: Optional[ReminderStatus] = Query(None, alias="status"),
    patient_id: Optional[UUID] = Query(None),
    appointment_id: Optional[UUID] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
):
    """
    List reminders with filtering.
    
    Complexity: O(n) where n = matching reminders (limited to 100)
    """
    conditions = [AppointmentReminder.organization_id == user.organization_id]
    
    if reminder_status:
        conditions.append(AppointmentReminder.status == reminder_status)
    if patient_id:
        conditions.append(AppointmentReminder.patient_id == patient_id)
    if appointment_id:
        conditions.append(AppointmentReminder.appointment_id == appointment_id)
    
    # Count
    total = await AppointmentReminder.query(db).filter(*conditions).count()
    
    # Fetch
    reminders = await (
        AppointmentReminder.query(db)
        .filter(*conditions)
        .order_by(AppointmentReminder.scheduled_send_time, desc=False)
        .offset(skip)
        .limit(limit)
        .all()
    )
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Reminders retrieved successfully",
        data=jsonable_encoder(ReminderListResponse(
            reminders=[ReminderResponse.model_validate(r) for r in reminders],
            total=total,
            skip=skip,
            limit=limit,
        )),
    )


@router.get(
    "/{reminder_id}",
    status_code=status.HTTP_200_OK,
    summary="Get reminder",
    dependencies=[Depends(require_permission("appointments:read"))],
)
async def get_reminder(
    reminder_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    """Get a single reminder with full attempt details."""
    reminder = await AppointmentReminder.fetch_unique(
        db,
        id=reminder_id,
        organization_id=user.organization_id
    )
    
    if not reminder:
        raise NotFoundException("Reminder not found")
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Reminder retrieved successfully",
        data=jsonable_encoder(ReminderResponse.model_validate(reminder)),
    )


@router.post(
    "/appointments/{appointment_id}/send-now",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send reminder now",
    dependencies=[Depends(require_permission("appointments:update"))],
)
async def send_reminder_now(
    appointment_id: UUID,
    user: CurrentUser,
    db: DbSession,
    request: SendReminderNowRequest = None,
):
    """
    Manually trigger an immediate reminder for an appointment.
    
    Creates an adhoc reminder record and triggers immediate send.
    """
    # Fetch appointment
    appointment = await Appointment.fetch_one_with(
        db, "patient",
        id=appointment_id,
        organization_id=user.organization_id
    )
    
    if not appointment:
        raise NotFoundException("Appointment not found")
    
    if appointment.status != AppointmentStatus.SCHEDULED:
        raise BadRequestException("Cannot send reminder for non-scheduled appointment")
    
    patient = appointment.patient
    
    # Determine channel
    if request and request.channel:
        channels = [request.channel.value]
    else:
        # Use patient preference or default order
        channels = []
        if patient.email:
            channels.append(ReminderChannel.EMAIL.value)
        if patient.phone:
            channels.append(ReminderChannel.SMS.value)
    
    if not channels:
        raise BadRequestException("Patient has no contact methods available")
    
    # Create immediate reminder
    idempotency_key = f"manual:{appointment_id}:{datetime.now(timezone.utc).isoformat()}"
    
    reminder = AppointmentReminder(
        appointment_id=appointment_id,
        patient_id=patient.id,
        organization_id=user.organization_id,
        channels=channels,
        scheduled_send_time=datetime.now(timezone.utc),
        status=ReminderStatus.SCHEDULED,
        idempotency_key=idempotency_key,
        created_by_agent="manual",
    )
    await reminder.insert(db)
    
    # Trigger immediate send via Celery
    send_reminder.delay(str(reminder.id))
    
    logger.info(f"Manual reminder triggered: {reminder.id} for appointment {appointment_id}")
    
    return success_response(
        status_code=status.HTTP_202_ACCEPTED,
        message="Reminder triggered, sending in background",
        data=jsonable_encoder(ReminderResponse.model_validate(reminder)),
    )


@router.patch(
    "/{reminder_id}/cancel",
    status_code=status.HTTP_200_OK,
    summary="Cancel reminder",
    dependencies=[Depends(require_permission("appointments:update"))],
)
async def cancel_reminder(
    reminder_id: UUID,
    user: CurrentUser,
    db: DbSession,
    request: ReminderCancelRequest = None,
):
    """Cancel a pending reminder (e.g., patient confirmed attendance)."""
    reminder = await AppointmentReminder.fetch_unique(
        db,
        id=reminder_id,
        organization_id=user.organization_id
    )
    
    if not reminder:
        raise NotFoundException("Reminder not found")
    
    if reminder.status != ReminderStatus.SCHEDULED:
        raise BadRequestException(f"Cannot cancel {reminder.status.value} reminder")
    
    reminder.status = ReminderStatus.CANCELLED
    if request and request.reason:
        reminder.attempts["cancelled"] = {
            "reason": request.reason,
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
            "cancelled_by": str(user.id),
        }
    await reminder.save(db)
    
    logger.info(f"Reminder {reminder_id} cancelled")
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Reminder cancelled",
        data=jsonable_encoder(ReminderResponse.model_validate(reminder)),
    )


# Debug endpoint for observability
@router.get(
    "/debug/action/{action_id}/trace",
    status_code=status.HTTP_200_OK,
    summary="Get action decision trace",
    dependencies=[Depends(require_permission("admin:read"))],
)
async def get_action_trace(
    action_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    """
    Get full decision trace for an agent action.
    
    Returns the decision_trace JSONB field showing:
    - Specialist findings
    - Supervisor reasoning
    - Critic validation result
    """
    from app.models.agent import AgentAction
    
    action = await AgentAction.fetch_unique(
        db,
        id=action_id,
        organization_id=user.organization_id
    )
    
    if not action:
        raise NotFoundException("Action not found")
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Decision trace retrieved",
        data={
            "action_id": str(action.id),
            "action_type": action.action_type,
            "patient_id": str(action.patient_id),
            "ai_reasoning": action.ai_reasoning,
            "decision_trace": action.decision_trace,
            "created_at": action.created_at.isoformat(),
        },
    )
