from datetime import datetime, timezone
from uuid import UUID
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.appointment import Appointment, AppointmentStatus, VisitMode
from app.schemas.appointment import AppointmentCreate
from app.utils.exceptions import NotFoundException, BadRequestException

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
            appointment_type=data.appointment_type,
            visit_mode=data.visit_mode,
            notes=data.notes,
            # If Agent created it, maybe mark priority or add a note?
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
        
        return appointment

    async def get_patient_appointments(self, patient_id: UUID) -> List[Appointment]:
        """Used by 'The Brain' to check patient history."""
        query = select(Appointment).where(
            Appointment.patient_id == patient_id
        ).order_by(Appointment.scheduled_time.desc())
        
        result = await self.db.execute(query)
        return result.scalars().all()