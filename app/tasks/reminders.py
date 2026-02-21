"""
Reminder Celery Tasks.

Handles scheduling and sending appointment reminders with cascade logic.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from celery import shared_task
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.celery_app import celery_app
from app.db.database import get_celery_session
from app.models.appointment import Appointment, AppointmentStatus
from app.models.patient import Patient
from app.models.reminder import AppointmentReminder, ReminderChannel, ReminderStatus
from app.services.notification_manager import NotificationManager
# from app.services.reminder_service import ReminderService  <-- MOVED TO TASK
from app.utils.logger import logger


@celery_app.task(name="app.tasks.reminders.schedule_daily_reminders")
def schedule_daily_reminders():
    """
    Runs at 5am daily via Celery Beat.
    Creates reminder records for appointments in next 48 hours.
    Then schedules individual send tasks at appropriate times.
    
    Complexity Analysis:
    - Time: O(n) where n = appointments in next 48h
    - Space: O(1) - records created in DB, not memory
    """
    logger.info("Celery task: schedule_daily_reminders started")
    
    async def _schedule():
        async with get_celery_session() as db:
            now = datetime.now(timezone.utc)
            cutoff = now + timedelta(hours=48)
            
            # Query scheduled appointments in next 48 hours
            query = (
                select(Appointment)
                .where(
                    and_(
                        Appointment.status == AppointmentStatus.SCHEDULED,
                        Appointment.scheduled_time >= now,
                        Appointment.scheduled_time <= cutoff,
                    )
                )
                .options(selectinload(Appointment.patient))
            )
            
            result = await db.execute(query)
            appointments = result.scalars().all()
            
            logger.info(f"Found {len(appointments)} appointments in next 48 hours")
            
            reminders_created = 0
            
            results_count = 0
            from app.services.reminder_service import ReminderService
            reminder_service = ReminderService(db)
            
            for appt in appointments:
                # Use centralized service to handle logic
                # It handles checking for status and creating if needed
                await reminder_service.schedule_reminders_for_appointment(appt.id)
                results_count += 1
            
            logger.info(f"Daily sweep processed {results_count} appointments")
    
    try:
        asyncio.run(_schedule())
        logger.info("Celery task: schedule_daily_reminders completed")
    except Exception as e:
        logger.exception(f"Celery task: schedule_daily_reminders failed: {e}")
        raise


@celery_app.task(
    name="app.tasks.reminders.send_reminder",
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 minutes
)
def send_reminder(self, reminder_id: str):
    """
    Execute a single reminder with cascade logic.
    
    Tries each channel in order until one succeeds.
    Retries on failure with exponential backoff.
    
    Args:
        reminder_id: UUID of the AppointmentReminder record
    """
    logger.info(f"Celery task: send_reminder started for {reminder_id}")
    
    async def _send():
        async with get_celery_session() as db:
            # Fetch reminder with relationships
            reminder = await AppointmentReminder.fetch_one_with(
                db,
                "appointment",
                "patient",
                id=UUID(reminder_id)
            )
            
            if not reminder:
                logger.error(f"Reminder {reminder_id} not found")
                return False
            
            if reminder.status != ReminderStatus.SCHEDULED:
                logger.info(f"Reminder {reminder_id} already processed (status: {reminder.status})")
                return True
            
            patient = reminder.patient
            appointment = reminder.appointment
            
            if not patient or not appointment:
                logger.error(f"Reminder {reminder_id} missing patient or appointment")
                reminder.status = ReminderStatus.FAILED
                reminder.mark_channel_attempt(
                    ReminderChannel.EMAIL, "failed", error="Missing patient or appointment"
                )
                await reminder.save(db)
                return False
            
            # Use NotificationManager for cascade logic
            manager = NotificationManager(db)
            success = await manager.send_appointment_reminder(
                reminder=reminder,
                patient=patient,
                appointment=appointment,
            )
            
            return success
    
    try:
        result = asyncio.run(_send())
        if result:
            logger.info(f"Celery task: send_reminder completed for {reminder_id}")
        else:
            logger.warning(f"Celery task: send_reminder failed for {reminder_id}")
            # Retry on failure
            raise self.retry(exc=Exception("Reminder send failed"))
        return result
        
    except Exception as e:
        logger.error(f"Celery task: send_reminder error: {e}")
        raise self.retry(exc=e)


@celery_app.task(name="app.tasks.reminders.escalate_no_shows")
def escalate_no_shows():
    """
    Runs at 7am daily via Celery Beat.
    Bumps priority of appointments where patient was a no-show yesterday.
    Creates follow-up reminders for rescheduling.
    
    Escalation Logic:
    - Mark appointment as NO_SHOW
    - Increment patient's no_show_count on future appointments
    - Bump priority_level on future scheduled appointments
    - Send no-show follow-up notification
    """
    logger.info("Celery task: escalate_no_shows started")
    
    async def _escalate():
        async with get_celery_session() as db:
            now = datetime.now(timezone.utc)
            yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0)
            yesterday_end = yesterday_start + timedelta(days=1)
            
            # Find appointments from yesterday that are still SCHEDULED (missed)
            query = (
                select(Appointment)
                .where(
                    and_(
                        Appointment.status == AppointmentStatus.SCHEDULED,
                        Appointment.scheduled_time >= yesterday_start,
                        Appointment.scheduled_time < yesterday_end,
                    )
                )
                .options(selectinload(Appointment.patient))
            )
            
            result = await db.execute(query)
            missed_appointments = result.scalars().all()
            
            logger.info(f"Found {len(missed_appointments)} missed appointments from yesterday")
            
            manager = NotificationManager(db)
            
            for appt in missed_appointments:
                # Mark as no-show
                appt.status = AppointmentStatus.NO_SHOW
                appt.no_show_count += 1
                await appt.save(db, commit=False)
                
                patient = appt.patient
                
                # Bump priority on future appointments for this patient
                future_query = (
                    select(Appointment)
                    .where(
                        and_(
                            Appointment.patient_id == patient.id,
                            Appointment.status == AppointmentStatus.SCHEDULED,
                            Appointment.scheduled_time > now,
                        )
                    )
                )
                future_result = await db.execute(future_query)
                future_appts = future_result.scalars().all()
                
                for future_appt in future_appts:
                    future_appt.priority_level = max(future_appt.priority_level, 2)  # Bump to at least 2
                    await future_appt.save(db, commit=False)
                
                # Send no-show follow-up notification
                await manager.send_no_show_followup(
                    patient=patient,
                    organization_id=appt.organization_id,
                )
                
                logger.info(f"Escalated no-show for patient {patient.id}, appointment {appt.id}")
            
            await db.commit()
    
    try:
        asyncio.run(_escalate())
        logger.info("Celery task: escalate_no_shows completed")
    except Exception as e:
        logger.exception(f"Celery task: escalate_no_shows failed: {e}")
        raise


@celery_app.task(name="app.tasks.reminders.create_reminder_from_agent_action")
def create_reminder_from_agent_action(action_details: dict):
    """
    Create an AppointmentReminder from an approved agent action.
    
    Called when the FollowUpSpecialist's proposed action is approved
    by the supervisor/critic flow.
    
    Args:
        action_details: Dict with appointment_id, channels, send_time, etc.
    """
    logger.info(f"Creating reminder from agent action: {action_details}")
    
    async def _create():
        async with get_celery_session() as db:
            appointment_id = UUID(action_details["appointment_id"])
            
            # Fetch appointment
            appointment = await Appointment.fetch_one_with(
                db, "patient",
                id=appointment_id
            )
            
            if not appointment:
                logger.error(f"Appointment {appointment_id} not found")
                return
            
            # Check for existing reminder
            existing = await AppointmentReminder.fetch_unique(
                db,
                appointment_id=appointment_id,
                status=ReminderStatus.SCHEDULED
            )
            if existing:
                logger.info(f"Reminder already exists for appointment {appointment_id}")
                return
            
            send_time = datetime.fromisoformat(action_details["send_time"])
            idempotency_key = f"agent_reminder:{appointment_id}:{send_time.isoformat()}"
            
            reminder = AppointmentReminder(
                appointment_id=appointment_id,
                patient_id=appointment.patient_id,
                organization_id=appointment.organization_id,
                channels=action_details["channels"],
                scheduled_send_time=send_time,
                status=ReminderStatus.SCHEDULED,
                idempotency_key=idempotency_key,
                created_by_agent="followup_specialist",
            )
            await reminder.insert(db)
            
            # Schedule the send task
            send_reminder.apply_async(
                args=[str(reminder.id)],
                eta=send_time,
            )
            
            logger.info(f"Created agent reminder {reminder.id} for appointment {appointment_id}")
    
    try:
        asyncio.run(_create())
    except Exception as e:
        logger.exception(f"Failed to create reminder from agent action: {e}")
        raise


@celery_app.task(name="app.tasks.reminders.send_booking_confirmation_task")
def send_booking_confirmation_task(appointment_id: str):
    """
    Send an immediate booking confirmation to the patient.
    """
    logger.info(f"Sending booking confirmation for {appointment_id}")
    
    async def _send():
        async with get_celery_session() as db:
            appointment = await Appointment.fetch_one_with(
                db, "patient",
                id=UUID(appointment_id)
            )
            
            if not appointment or not appointment.patient:
                logger.warning(f"Appointment {appointment_id} or patient not found")
                return
            
            manager = NotificationManager(db)
            await manager.send_booking_confirmation(
                patient=appointment.patient,
                appointment=appointment
            )
            
    try:
        asyncio.run(_send())
    except Exception as e:
        logger.error(f"Failed to send booking confirmation task: {e}")
