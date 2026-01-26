from datetime import datetime, timedelta, time
from uuid import UUID
from typing import List, Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from app.db.database import async_session_factory
from app.models.appointment import Appointment, AppointmentStatus
from app.models.calendar import CalendarIntegration, CalendarProvider
from app.models.user import User
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
        org_id: UUID, 
        start_date: datetime, 
        end_date: datetime, 
        provider_id: Optional[UUID] = None
    ) -> List[datetime]:
        """
        Get all available appointment slots between start_date and end_date.
        
        Logic:
        1. Generate all theoretical slots within working hours.
        2. Query existing scheduled appointments.
        3. Check external calendars for busy periods.
        4. Subtract booked slots from theoretical slots.
        """
        if start_date >= end_date:
            return []
            
        # Ensure dates are timezone-aware (assuming UTC inputs for now)
        # In a real app, care must be taken with organization timezones.
        
        available_slots = []
        
        async with async_session_factory() as db:
            # 1. Fetch relevant appointments to block off time
            query = select(Appointment).where(
                Appointment.organization_id == org_id,
                Appointment.status.in_([AppointmentStatus.SCHEDULED, AppointmentStatus.COMPLETED]),
                Appointment.scheduled_time >= start_date,
                Appointment.scheduled_time < end_date
            )
            
            calendar_busy_ranges = []
            
            if provider_id:
                # If checking for specific provider
                query = query.where(Appointment.provider_id == provider_id)
                
                # Fetch external calendar busy periods
                calendar_busy_ranges = await cls._fetch_calendar_busy_periods(
                    db, provider_id, start_date, end_date
                )
                
            else:
                # Logic: If checking generally, we need to know WHICH providers are available.
                # For this MVP, we might assume we are looking for ANY availability for the specific provider 
                # OR if no provider specified, we might pick the first available one? 
                # The prompt implies: "Priority to assigned provider, fallback to team."
                # But for the service method signature, let's keep it simple: 
                # If provider_id is None, we need to know capacity. 
                # Simplification: The tool calling this will likely pass a provider_id from the patient's history.
                # If not, we might be checking "any doctor".
                pass

            result = await db.execute(query)
            existing_appointments = result.scalars().all()
            
            # Create a set of booked times for O(1) lookup
            # Rounding existing appts to slot boundaries might be needed if they are off-grid
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
                        
                        # INTERNAL CHECK
                        if current_slot in booked_times:
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
