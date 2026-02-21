from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment, AppointmentStatus
from app.models.reminder import AppointmentReminder, ReminderChannel, ReminderStatus
from app.utils.logger import logger

class ReminderService:
    """
    Centralized service for managing appointment reminders.
    Handles scheduling, cancellation, and re-priming logic.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def schedule_reminders_for_appointment(self, appointment_id: UUID) -> None:
        """
        Schedule initial reminders for a new or rescheduled appointment.
        Created on-demand to fix the 'Late Booking Gap'.
        """
        # Fetch appointment with patient details
        appointment = await Appointment.fetch_one_with(
            self.db, "patient", id=appointment_id
        )
        if not appointment or appointment.status != AppointmentStatus.SCHEDULED:
            logger.warning(f"Skipping reminder scheduling for invalid/cancelled appointment: {appointment_id}")
            return

        now = datetime.now(timezone.utc)
        if appointment.scheduled_time < now:
            logger.info(f"Skipping reminder scheduling for past appointment: {appointment_id}")
            return
        
        patient = appointment.patient
        
        # Determine channels based on patient contact info
        channels = []
        if patient.email:
            channels.append(ReminderChannel.EMAIL.value)
        if patient.phone:
            channels.append(ReminderChannel.SMS.value)
        
        if not channels:
            logger.warning(f"Patient {patient.id} has no contact methods, skipping reminder")
            return

        # Calculate best send time (24h before or immediately if booked late)
        # Strategy: 24h before, but if appointment is < 25h away, send in 5 mins
        hours_until = (appointment.scheduled_time - now).total_seconds() / 3600
        
        if hours_until <= 25:
            send_time = now + timedelta(minutes=5)
        else:
            send_time = appointment.scheduled_time - timedelta(hours=24)

        # Create reminder record
        # Idempotency key now includes timestamp to allow same-day rescheduling
        idempotency_key = f"rem:{appointment_id}:{send_time.timestamp()}"
        
        reminder = AppointmentReminder(
            appointment_id=appointment.id,
            patient_id=patient.id,
            organization_id=appointment.organization_id,
            channels=channels,
            scheduled_send_time=send_time,
            status=ReminderStatus.SCHEDULED,
            idempotency_key=idempotency_key,
            created_by_agent="reminder_service",
        )
        
        try:
            self.db.add(reminder)
            await self.db.flush()
            
            # Only dispatch immediately for near-future reminders (< 25 min).
            # Far-future reminders are picked up by the daily sweep task
            # (schedule_daily_reminders at 5am) which checks scheduled_send_time.
            # This avoids RabbitMQ consumer_timeout kills from long ETA waits.
            minutes_until_send = (send_time - now).total_seconds() / 60
            if minutes_until_send <= 25:
                from app.tasks.reminders import send_reminder
                send_reminder.apply_async(
                    args=[str(reminder.id)],
                    eta=send_time,
                )
                logger.info(f"Dispatched immediate reminder {reminder.id} (ETA {send_time})")
            else:
                logger.info(
                    f"Stored reminder {reminder.id} for {send_time} "
                    f"— daily sweep will dispatch it"
                )
        except Exception as e:
            if "unique constraint" not in str(e).lower():
                logger.error(f"Failed to schedule reminder: {e}")


    async def cancel_reminders_for_appointment(self, appointment_id: UUID) -> int:
        """
        Cancel all pending reminders for an appointment.
        Used when 'The Hand' reschedules or cancels an appointment.
        """
        # Batch update pending reminders to CANCELLED
        stmt = (
            update(AppointmentReminder)
            .where(
                AppointmentReminder.appointment_id == appointment_id,
                AppointmentReminder.status == ReminderStatus.SCHEDULED
            )
            .values(status=ReminderStatus.CANCELLED)
        )
        
        result = await self.db.execute(stmt)
        await self.db.flush()
        
        count = result.rowcount
        if count > 0:
            logger.info(f"Cancelled {count} pending reminders for appointment {appointment_id}")
        
        return count

    async def reprime_reminders(self, appointment_id: UUID) -> None:
        """
        Orchestration helper for rescheduling.
        """
        await self.cancel_reminders_for_appointment(appointment_id)
        await self.schedule_reminders_for_appointment(appointment_id)
