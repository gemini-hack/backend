"""
Celery tasks for two-way Google Calendar synchronization.

These tasks run asynchronously after appointment create/update/cancel
to push changes to the provider's Google Calendar.
"""
import asyncio
from app.celery_app import celery_app
from app.db.database import get_celery_session
from app.utils.logger import logger


def run_async(coro):
    """Run async code safely in Celery worker."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def dispatch_calendar_sync(appointment_id) -> None:
    """Dispatch a Celery task to sync this appointment to Google Calendar."""
    try:
        sync_appointment_to_google.delay(str(appointment_id))
        logger.info(f"Dispatched calendar sync for appointment {appointment_id}")
    except Exception as e:
        # Calendar sync is best-effort — never block appointment operations
        logger.warning(f"Failed to dispatch calendar sync for {appointment_id}: {e}")


def dispatch_calendar_delete(appointment_id) -> None:
    """Dispatch a Celery task to delete the Google Calendar event."""
    try:
        delete_google_event.delay(str(appointment_id))
        logger.info(f"Dispatched calendar delete for appointment {appointment_id}")
    except Exception as e:
        logger.warning(f"Failed to dispatch calendar delete for {appointment_id}: {e}")


@celery_app.task(
    bind=True,
    name="app.tasks.calendar_tasks.sync_appointment_to_google",
    max_retries=5,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    acks_late=True,
)
def sync_appointment_to_google(self, appointment_id: str):
    """
    Sync an appointment to Google Calendar (create or update).
    
    Idempotent: 
    - If no google_event_id exists → creates a new event, stores the ID.
    - If google_event_id exists → updates the existing event.
    - If update returns 404 (event deleted externally) → creates a new one.
    
    On auth failure → marks integration as NEEDS_REAUTH, does NOT retry.
    """
    logger.info(
        f"[Attempt {self.request.retries + 1}/{self.max_retries + 1}] "
        f"Syncing appointment {appointment_id} to Google Calendar"
    )

    async def _sync():
        from uuid import UUID
        from sqlalchemy import select
        from app.models.appointment import Appointment, AppointmentStatus
        from app.models.calendar import CalendarIntegration, CalendarProvider
        from app.services.google_calendar_service import GoogleCalendarService
        from app.utils.exceptions import (
            CalendarAuthError,
            CalendarTokenExpiredError,
            CalendarAPIError,
        )

        async with get_celery_session() as db:
            # Load appointment
            result = await db.execute(
                select(Appointment).where(Appointment.id == UUID(appointment_id))
            )
            appointment = result.scalar_one_or_none()

            if not appointment:
                logger.warning(f"Appointment {appointment_id} not found, skipping sync")
                return {"status": "skipped", "reason": "appointment_not_found"}

            if not appointment.provider_id:
                logger.info(f"Appointment {appointment_id} has no provider, skipping sync")
                return {"status": "skipped", "reason": "no_provider"}

            # Skip cancelled appointments (they should use delete task)
            if appointment.status == AppointmentStatus.CANCELLED:
                logger.info(f"Appointment {appointment_id} is cancelled, skipping sync")
                return {"status": "skipped", "reason": "cancelled"}

            # Load provider's calendar integration
            cal_result = await db.execute(
                select(CalendarIntegration).where(
                    CalendarIntegration.user_id == appointment.provider_id,
                    CalendarIntegration.provider == CalendarProvider.GOOGLE,
                )
            )
            integration = cal_result.scalar_one_or_none()

            if not integration:
                logger.info(
                    f"No Google Calendar integration for provider {appointment.provider_id}, skipping"
                )
                return {"status": "skipped", "reason": "no_integration"}

            if integration.needs_reauth():
                logger.warning(
                    f"Calendar integration for provider {appointment.provider_id} needs re-auth"
                )
                return {"status": "skipped", "reason": "needs_reauth"}

            service = GoogleCalendarService(db)

            try:
                if appointment.google_event_id:
                    # Update existing event
                    try:
                        await service.update_event(
                            integration, appointment.google_event_id, appointment
                        )
                        await db.commit()
                        logger.info(
                            f"Updated Google Calendar event {appointment.google_event_id} "
                            f"for appointment {appointment_id}"
                        )
                        return {"status": "updated", "event_id": appointment.google_event_id}
                    except CalendarAPIError as e:
                        if e.status_code == 404:
                            # Event was deleted externally — fall through to create
                            logger.info(
                                f"Event {appointment.google_event_id} deleted externally, "
                                f"creating new one"
                            )
                            appointment.google_event_id = None
                        else:
                            raise

                # Create new event
                event_id = await service.create_event(integration, appointment)
                appointment.google_event_id = event_id
                await db.commit()
                logger.info(
                    f"Created Google Calendar event {event_id} "
                    f"for appointment {appointment_id}"
                )
                return {"status": "created", "event_id": event_id}

            except (CalendarAuthError, CalendarTokenExpiredError) as e:
                # Auth failure — mark integration and don't retry
                integration.mark_needs_reauth()
                await db.commit()
                logger.warning(
                    f"Calendar auth failed for provider {appointment.provider_id}: {e}. "
                    f"Marked as NEEDS_REAUTH."
                )
                return {"status": "auth_failed", "reason": str(e)}

    result = run_async(_sync())
    return result


@celery_app.task(
    bind=True,
    name="app.tasks.calendar_tasks.delete_google_event",
    max_retries=5,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    acks_late=True,
)
def delete_google_event(self, appointment_id: str):
    """
    Delete a Google Calendar event for a cancelled appointment.
    
    Idempotent:
    - If no google_event_id → nothing to delete.
    - If google_event_id exists → deletes the event, clears the field.
    - 404 from Google → event already gone, just clear the field.
    
    On auth failure → marks integration as NEEDS_REAUTH, does NOT retry.
    """
    logger.info(
        f"[Attempt {self.request.retries + 1}/{self.max_retries + 1}] "
        f"Deleting Google Calendar event for appointment {appointment_id}"
    )

    async def _delete():
        from uuid import UUID
        from sqlalchemy import select
        from app.models.appointment import Appointment
        from app.models.calendar import CalendarIntegration, CalendarProvider
        from app.services.google_calendar_service import GoogleCalendarService
        from app.utils.exceptions import (
            CalendarAuthError,
            CalendarTokenExpiredError,
        )

        async with get_celery_session() as db:
            # Load appointment
            result = await db.execute(
                select(Appointment).where(Appointment.id == UUID(appointment_id))
            )
            appointment = result.scalar_one_or_none()

            if not appointment:
                logger.warning(f"Appointment {appointment_id} not found, skipping delete")
                return {"status": "skipped", "reason": "appointment_not_found"}

            if not appointment.google_event_id:
                logger.info(f"Appointment {appointment_id} has no google_event_id, nothing to delete")
                return {"status": "skipped", "reason": "no_event_id"}

            if not appointment.provider_id:
                logger.info(f"Appointment {appointment_id} has no provider, clearing event id")
                appointment.google_event_id = None
                await db.commit()
                return {"status": "cleared", "reason": "no_provider"}

            # Load provider's calendar integration
            cal_result = await db.execute(
                select(CalendarIntegration).where(
                    CalendarIntegration.user_id == appointment.provider_id,
                    CalendarIntegration.provider == CalendarProvider.GOOGLE,
                )
            )
            integration = cal_result.scalar_one_or_none()

            if not integration:
                # No integration — just clear the stale event ID
                logger.info(
                    f"No integration for provider {appointment.provider_id}, "
                    f"clearing stale google_event_id"
                )
                appointment.google_event_id = None
                await db.commit()
                return {"status": "cleared", "reason": "no_integration"}

            if integration.needs_reauth():
                logger.warning(
                    "Calendar integration needs re-auth, clearing google_event_id"
                )
                appointment.google_event_id = None
                await db.commit()
                return {"status": "cleared", "reason": "needs_reauth"}

            service = GoogleCalendarService(db)
            event_id = appointment.google_event_id

            try:
                await service.delete_event(integration, event_id)
                appointment.google_event_id = None
                await db.commit()
                logger.info(f"Deleted Google Calendar event {event_id}")
                return {"status": "deleted", "event_id": event_id}

            except (CalendarAuthError, CalendarTokenExpiredError) as e:
                integration.mark_needs_reauth()
                appointment.google_event_id = None
                await db.commit()
                logger.warning(
                    f"Calendar auth failed during delete: {e}. "
                    f"Marked as NEEDS_REAUTH, cleared event ID."
                )
                return {"status": "auth_failed", "reason": str(e)}

    result = run_async(_delete())
    return result


@celery_app.task(name="app.tasks.calendar_tasks.backfill_historical_sync")
def backfill_historical_sync(organization_id: str):
    """
    Find appointments without google_event_id and sync them.
    Only syncs future appointments for providers who have an active integration.
    """
    logger.info(f"Starting historical backfill for organization {organization_id}")
    
    async def _backfill():
        from uuid import UUID
        from datetime import datetime, timezone
        from sqlalchemy import select, and_
        from app.models.appointment import Appointment, AppointmentStatus
        
        async with get_celery_session() as db:
            # Find future scheduled appointments without google_event_id
            query = (
                select(Appointment)
                .where(
                    and_(
                        Appointment.organization_id == UUID(organization_id),
                        Appointment.google_event_id == None,
                        Appointment.status == AppointmentStatus.SCHEDULED,
                        Appointment.scheduled_time >= datetime.now(timezone.utc)
                    )
                )
            )
            
            result = await db.execute(query)
            appointments = result.scalars().all()
            
            logger.info(f"Found {len(appointments)} appointments to backfill for org {organization_id}")
            for appt in appointments:
                # Dispatch individual sync tasks
                dispatch_calendar_sync(appt.id)
                
    run_async(_backfill())
