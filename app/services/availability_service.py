from datetime import datetime, timedelta, time, timezone
from uuid import UUID
from typing import List, Optional

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession
from app.models.appointment import Appointment, AppointmentStatus
from app.models.calendar import CalendarIntegration, CalendarProvider
from app.services.google_calendar_service import GoogleCalendarService
from app.utils.exceptions import (
    CalendarServiceError,
    CalendarAuthError,
    CalendarTokenExpiredError,
)
from app.utils.logger import logger


class AvailabilityService:
    """
    Service to calculate available appointment slots.
    
    Default Business Rules:
    - Working hours: 09:00 - 17:00
    - Work days: Monday (0) - Friday (4)
    - Slot duration: 30 minutes
    """
    
    WORK_START = time(9, 0)
    WORK_END = time(17, 0)
    SLOT_DURATION_MINUTES = 30
    
    @classmethod
    async def _fetch_calendar_busy_periods(
        cls,
        db,
        provider_id: UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> List[tuple[datetime, datetime]]:
        """
        Fetch busy periods from external calendar integrations.
        
        Args:
            db: Database session
            provider_id: The provider's user ID
            start_date: Start of the time range
            end_date: End of the time range
            
        Returns:
            List of (start, end) tuples for busy periods.
            Returns empty list if no calendar connected or on error.
        """
        # Check if provider has calendar connected
        cal_query = select(CalendarIntegration).where(
            CalendarIntegration.user_id == provider_id,
            CalendarIntegration.provider == CalendarProvider.GOOGLE,
        )
        cal_result = await db.execute(cal_query)
        integration = cal_result.scalar_one_or_none()
        
        if not integration:
            return []
        
        # Skip if integration needs re-authentication
        if integration.needs_reauth():
            logger.warning(
                f"Calendar integration for provider {provider_id} needs re-authentication"
            )
            return []
        
        try:
            service = GoogleCalendarService(db)
            return await service.get_busy_periods(integration, start_date, end_date)
            
        except CalendarTokenExpiredError as e:
            # Token expired and couldn't be refreshed
            logger.warning(f"Calendar token expired for provider {provider_id}: {e}")
            return []
            
        except CalendarAuthError as e:
            # Authentication issue
            logger.warning(f"Calendar auth error for provider {provider_id}: {e}")
            return []
            
        except CalendarServiceError as e:
            # Other calendar service errors - fail open to avoid blocking scheduling
            logger.error(f"Failed to fetch Google Calendar busy slots: {e}")
            return []
            
        except Exception as e:
            # Unexpected error - fail open
            logger.error(f"Unexpected error fetching calendar busy slots: {e}")
            return []
    
    @classmethod
    async def get_available_slots(
        cls, 
        db: AsyncSession,
        org_id: UUID, 
        start_date: datetime, 
        end_date: datetime, 
        provider_id: Optional[UUID] = None
    ) -> List[datetime]:
        """
        Get all available appointment slots between start_date and end_date.
        
        Logic:
        1. Query existing scheduled appointments.
        2. Check external calendars for busy periods.
        3. Generate theoretical slots and subtract booked slots.
        """
        if start_date >= end_date:
            return []
        
        # Ensure timezone-aware datetimes to avoid naive vs aware comparison errors
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
            
        available_slots = []
        
        # 1. Fetch relevant appointments to block off time
        query = select(Appointment).where(
            Appointment.organization_id == org_id,
            Appointment.status.in_([AppointmentStatus.SCHEDULED, AppointmentStatus.COMPLETED]),
            Appointment.scheduled_time >= start_date,
            Appointment.scheduled_time < end_date
        )
        
        calendar_busy_ranges = []
        
        if provider_id:
            query = query.where(Appointment.provider_id == provider_id)
            calendar_busy_ranges = await cls._fetch_calendar_busy_periods(
                db, provider_id, start_date, end_date
            )
            
        result = await db.execute(query)
        existing_appointments = result.scalars().all()
        
        # Normalize appointment times to match start_date timezone awareness
        for appt in existing_appointments:
            if appt.scheduled_time.tzinfo is None:
                appt.scheduled_time = appt.scheduled_time.replace(tzinfo=timezone.utc)
        
        booked_times = {appt.scheduled_time.replace(second=0, microsecond=0) for appt in existing_appointments}
            
        # 2. Iterate through days and generate slots
        current_day = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_day_boundary = end_date.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        
        while current_day < end_day_boundary:
            # Skip weekends (5=Saturday, 6=Sunday)
            if current_day.weekday() >= 5:
                current_day += timedelta(days=1)
                continue
            
            # Generate slots for this day
            # Construct start/end DateTimes for the work day
            day_start = datetime.combine(current_day.date(), cls.WORK_START).replace(tzinfo=start_date.tzinfo)
            day_end = datetime.combine(current_day.date(), cls.WORK_END).replace(tzinfo=start_date.tzinfo)
            
            current_slot = day_start
            while current_slot < day_end:
                # Check constraints:
                # 1. Must be strictly after requested start_date (if start_date is mid-day)
                # 2. Must be before end_date
                if current_slot >= start_date and current_slot < end_date:
                    
                    # INTERNAL CHECK (Overlap detection fallback)
                    is_internally_busy = False
                    slot_end = current_slot + timedelta(minutes=cls.SLOT_DURATION_MINUTES)
                    
                    for appt in existing_appointments:
                        appt_end = appt.scheduled_time + timedelta(minutes=appt.duration_minutes)
                        if current_slot < appt_end and slot_end > appt.scheduled_time:
                            is_internally_busy = True
                            break
                            
                    if is_internally_busy:
                        current_slot += timedelta(minutes=cls.SLOT_DURATION_MINUTES)
                        continue
                        
                    # EXTERNAL CALENDAR CHECK
                    is_externally_busy = False
                    slot_end = current_slot + timedelta(minutes=cls.SLOT_DURATION_MINUTES)
                    
                    for busy_start, busy_end in calendar_busy_ranges:
                        # Check overlap
                        # Overlap exists if (SlotStart < BusyEnd) AND (SlotEnd > BusyStart)
                        if current_slot < busy_end and slot_end > busy_start:
                            is_externally_busy = True
                            break
                    
                    if not is_externally_busy:
                        available_slots.append(current_slot)
                
                current_slot += timedelta(minutes=cls.SLOT_DURATION_MINUTES)
            
            current_day += timedelta(days=1)
            
        return available_slots
