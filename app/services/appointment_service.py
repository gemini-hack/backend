from datetime import datetime
from uuid import UUID
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import async_session_factory
from app.models.appointment import Appointment, AppointmentStatus
from app.utils.exceptions import NotFoundException, BadRequestException

class AppointmentService:
    """Service for managing appointments."""
    
    @staticmethod
    async def reschedule_appointment(
        appointment_id: UUID, 
        new_start_time: datetime,
        organization_id: UUID
    ) -> Appointment:
        """
        Reschedule an appointment.
        
        Business Rules:
        - Can only reschedule if status is NO_SHOW or CANCELLED (recovery flow)
        - New time must be in the future
        - Resets status to SCHEDULED
        """
        if new_start_time <= datetime.now(new_start_time.tzinfo):
             raise BadRequestException("New appointment time must be in the future")

        async with async_session_factory() as db:
            appointment = await Appointment.fetch_unique(
                db,
                id=appointment_id,
                organization_id=organization_id
            )
            
            if not appointment:
                raise NotFoundException("Appointment not found")
            
            # Allow recovery from NO_SHOW or CANCELLED
            if appointment.status not in [AppointmentStatus.NO_SHOW, AppointmentStatus.CANCELLED]:
                raise BadRequestException(
                    f"Only missed (NO_SHOW) or cancelled appointments can be rescheduled via this flow. "
                    f"Current status: {appointment.status.value}"
                )
            
            # Update
            appointment.scheduled_time = new_start_time
            appointment.status = AppointmentStatus.SCHEDULED
            
            await appointment.save(db)
            
            # Re-prime reminders (cancel old, schedule new)
            from app.services.reminder_service import ReminderService
            reminder_service = ReminderService(db)
            await reminder_service.reprime_reminders(appointment.id)
            
            return appointment
