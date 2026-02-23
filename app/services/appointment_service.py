from datetime import datetime, timezone
from uuid import UUID
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.appointment import Appointment, AppointmentStatus
from app.schemas.appointment import AppointmentCreate
from app.utils.exceptions import NotFoundException, BadRequestException
from app.utils.logger import logger
from app.tasks.calendar_tasks import dispatch_calendar_sync, dispatch_calendar_delete

class AppointmentService:
    def __init__(self, db: AsyncSession):
        self.db = db



    async def create_appointment(
        self, 
        data: AppointmentCreate, 
        organization_id: UUID,
        created_by_agent: bool = False
    ) -> Appointment:
        """
        Used by: Frontend AND 'The Hand' (Agents).
        """
        # 1. Validation: No past appointments
        if data.scheduled_time.tzinfo is None:
             data.scheduled_time = data.scheduled_time.replace(tzinfo=timezone.utc)
             
        if data.scheduled_time <= datetime.now(timezone.utc):
            raise BadRequestException("Appointment time must be in the future")

        # 2. Create the Record
        appointment = Appointment(
            organization_id=organization_id,
            patient_id=data.patient_id,
            provider_id=data.provider_id,
            scheduled_time=data.scheduled_time,
            duration_minutes=data.duration_minutes,
            appointment_type=data.appointment_type,
            visit_mode=data.visit_mode,
            notes=data.notes,
            priority_level=1 if created_by_agent else 0
        )
        
        if created_by_agent:
            appointment.notes = (appointment.notes or "") + " [Auto-booked by MIRA AI]"

        self.db.add(appointment)
        await self.db.flush() # Get ID
        
        # 3. ORCHESTRATION: Trigger Reminder Creation
        from app.services.reminder_service import ReminderService
        reminder_service = ReminderService(self.db)
        await reminder_service.schedule_reminders_for_appointment(appointment.id)
        
        # 4. CALENDAR SYNC: Push to Google Calendar (async, best-effort)
        dispatch_calendar_sync(appointment.id)
        
        # 5. IMMEDIATE NOTIFICATION: Send booking confirmation (async, best-effort)
        try:
            from app.tasks.reminders import send_booking_confirmation_task
            send_booking_confirmation_task.delay(str(appointment.id))
            logger.info(f"Dispatched booking confirmation for appointment {appointment.id}")
        except Exception as e:
            logger.warning(f"Failed to dispatch booking confirmation for {appointment.id}: {e}")
        
        return appointment

    async def reschedule_appointment(
        self,
        appointment_id: UUID,
        new_scheduled_time: datetime,
        notes: Optional[str] = None,
    ) -> Appointment:
        """
        Reschedule an existing appointment to a new time.
        
        Updates the scheduled_time, sets status to RESCHEDULED,
        and dispatches a Google Calendar update task.
        """
        result = await self.db.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
        appointment = result.scalar_one_or_none()

        if not appointment:
            raise NotFoundException(f"Appointment {appointment_id} not found")

        if appointment.status == AppointmentStatus.CANCELLED:
            raise BadRequestException("Cannot reschedule a cancelled appointment")

        if appointment.status == AppointmentStatus.COMPLETED:
            raise BadRequestException("Cannot reschedule a completed appointment")

        if new_scheduled_time.tzinfo is None:
            new_scheduled_time = new_scheduled_time.replace(tzinfo=timezone.utc)

        if new_scheduled_time <= datetime.now(timezone.utc):
            raise BadRequestException("New appointment time must be in the future")

        old_time = appointment.scheduled_time
        appointment.scheduled_time = new_scheduled_time
        appointment.status = AppointmentStatus.RESCHEDULED
        
        if notes:
            appointment.notes = (appointment.notes or "") + f"\n[Rescheduled] {notes}"
        else:
            appointment.notes = (
                (appointment.notes or "") 
                + f"\n[Rescheduled from {old_time.isoformat()} to {new_scheduled_time.isoformat()}]"
            )

        await self.db.flush()

        # Re-schedule reminders for the new time
        from app.services.reminder_service import ReminderService
        reminder_service = ReminderService(self.db)
        await reminder_service.schedule_reminders_for_appointment(appointment.id)

        # Sync change to Google Calendar
        dispatch_calendar_sync(appointment.id)

        logger.info(
            f"Appointment {appointment_id} rescheduled from {old_time} to {new_scheduled_time}"
        )
        return appointment

    async def cancel_appointment(
        self,
        appointment_id: UUID,
        reason: Optional[str] = None,
    ) -> Appointment:
        """
        Cancel an appointment and remove its Google Calendar event.
        """
        result = await self.db.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
        appointment = result.scalar_one_or_none()

        if not appointment:
            raise NotFoundException(f"Appointment {appointment_id} not found")

        if appointment.status == AppointmentStatus.CANCELLED:
            raise BadRequestException("Appointment is already cancelled")

        if appointment.status == AppointmentStatus.COMPLETED:
            raise BadRequestException("Cannot cancel a completed appointment")

        appointment.status = AppointmentStatus.CANCELLED
        if reason:
            appointment.notes = (appointment.notes or "") + f"\n[Cancelled] {reason}"

        await self.db.flush()

        # Delete the Google Calendar event (async, best-effort)
        dispatch_calendar_delete(appointment.id)

        logger.info(f"Appointment {appointment_id} cancelled")
        return appointment

    async def get_patient_appointments(self, patient_id: UUID) -> List[Appointment]:
        """Used by 'The Brain' to check patient history."""
        query = select(Appointment).where(
            Appointment.patient_id == patient_id
        ).order_by(Appointment.scheduled_time.desc()).limit(100)
        
        result = await self.db.execute(query)
        return result.scalars().all()