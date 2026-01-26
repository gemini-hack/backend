from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, status
from fastapi.responses import HTMLResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, DbSession, get_db
from app.models.calendar import CalendarIntegration, CalendarProvider, IntegrationStatus
from app.services.google_calendar_service import GoogleCalendarService
from app.utils.exceptions import (
    NotFoundException,
    CalendarServiceError,
    CalendarAuthError,
    CalendarAPIError,
)
from app.schemas.calendar import (
    CalendarStatusResponse,
    InitiateAuthResponse,
    DisconnectResponse,
    CalendarListItem,
    CalendarListResponse,
)
from app.utils.responses import success_response
from app.utils.logger import logger

router = APIRouter(prefix="/integrations", tags=["Integrations"])


@router.get(
    "/google/status",
    status_code=status.HTTP_200_OK,
    response_model=CalendarStatusResponse,
    summary="Get calendar status",
)
async def get_calendar_status(
    user: CurrentUser,
    db: DbSession,
):
    """Get the current user's Google Calendar integration status."""
    service = GoogleCalendarService(db)
    integration = await service.get_integration(user.id)
    
    if not integration:
        return success_response(
            status_code=status.HTTP_200_OK,
            message="Calendar status retrieved",
            data=jsonable_encoder(CalendarStatusResponse(connected=False)),
        )
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Calendar status retrieved",
        data=jsonable_encoder(CalendarStatusResponse(
            connected=True,
            status=IntegrationStatus(integration.status),
            provider=CalendarProvider.GOOGLE,
            email=integration.email,
            last_synced_at=integration.last_synced_at,
        )),
    )


@router.post(
    "/google/initiate",
    status_code=status.HTTP_200_OK,
    response_model=InitiateAuthResponse,
    summary="Initiate Google OAuth",
)
async def initiate_google_auth(
    user: CurrentUser,
    db: DbSession,
):
    """Initiate Google Calendar connection via email magic link."""
    service = GoogleCalendarService(db)
    
    auth_url = service.get_auth_url(user_id=str(user.id))
    
    # Offload email sending to Celery
    from app.tasks.email import send_calendar_auth_email_task
    send_calendar_auth_email_task.delay(
        user.email,
        user.first_name,
        auth_url
    )
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Authorization link sent to email",
        data=jsonable_encoder(InitiateAuthResponse(
            message="Authorization link sent to email",
            provider=CalendarProvider.GOOGLE,
        )),
    )


@router.get(
    "/google/callback",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def google_auth_callback(
    code: str,
    state: str,
    db: DbSession,
    error: Optional[str] = None,
):
    """Handle Google OAuth callback."""
    if error:
        logger.warning(f"OAuth callback received error: {error}")
        return f"""
        <html>
            <head><title>Authorization Failed</title></head>
            <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                <h1 style="color: #d32f2f;">Authorization Failed</h1>
                <p>Error: {error}</p>
                <p>Please try again or contact support if the issue persists.</p>
            </body>
        </html>
        """
    
    try:
        service = GoogleCalendarService(db)
        
        integration = await service.exchange_code(code, state)
        
        return f"""
        <html>
            <head>
                <title>Connection Successful</title>
                <style>
                    body {{ font-family: sans-serif; text-align: center; padding-top: 50px; }}
                    .success {{ color: #2e7d32; font-size: 20px; }}
                    .email {{ color: #666; margin-top: 10px; }}
                </style>
            </head>
            <body>
                <h1 class="success">✓ Calendar Connected!</h1>
                <p>MIRA is now synced with your Google Calendar.</p>
                <p class="email">Connected account: {integration.email or 'Unknown'}</p>
                <p>You can close this window.</p>
            </body>
        </html>
        """
        
    except CalendarAuthError as e:
        logger.warning(f"OAuth state validation failed: {e}")
        return """
        <html>
            <head><title>Authorization Failed</title></head>
            <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                <h1 style="color: #d32f2f;">Authorization Failed</h1>
                <p>The authorization link has expired or is invalid.</p>
                <p>Please request a new link and try again.</p>
            </body>
        </html>
        """
        
    except CalendarAPIError as e:
        logger.error(f"OAuth token exchange failed: {e}")
        return f"""
        <html>
            <head><title>Connection Failed</title></head>
            <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                <h1 style="color: #d32f2f;">Connection Failed</h1>
                <p>An error occurred while connecting your calendar.</p>
                <p>Please try again later.</p>
            </body>
        </html>
        """
        
    except Exception as e:
        logger.error(f"Unexpected callback error: {e}")
        return """
        <html>
            <head><title>Connection Failed</title></head>
            <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                <h1 style="color: #d32f2f;">Connection Failed</h1>
                <p>An unexpected error occurred.</p>
                <p>Please try again or contact support.</p>
            </body>
        </html>
        """


@router.delete(
    "/google/disconnect",
    status_code=status.HTTP_200_OK,
    response_model=DisconnectResponse,
    summary="Disconnect Google Calendar",
)
async def disconnect_google_calendar(
    user: CurrentUser,
    db: DbSession,
):
    """Disconnect Google Calendar integration."""
    service = GoogleCalendarService(db)
    integration = await service.get_integration(user.id)
    
    if not integration:
        raise NotFoundException("No Google Calendar integration found")
    
    try:
        await service.revoke_access(integration)
        logger.info(f"User {user.id} disconnected Google Calendar")
        
        return success_response(
            status_code=status.HTTP_200_OK,
            message="Google Calendar disconnected successfully",
            data=jsonable_encoder(DisconnectResponse(
                message="Google Calendar disconnected successfully",
                provider=CalendarProvider.GOOGLE,
            )),
        )
        
    except CalendarServiceError as e:
        logger.error(f"Error disconnecting calendar: {e}")
        raise CalendarAPIError("Failed to disconnect calendar")


@router.get(
    "/google/calendars",
    status_code=status.HTTP_200_OK,
    response_model=CalendarListResponse,
    summary="List Google Calendars",
)
async def list_google_calendars(
    user: CurrentUser,
    db: DbSession,
):
    """List all calendars accessible by the user's Google account."""
    service = GoogleCalendarService(db)
    integration = await service.get_integration(user.id)
    
    if not integration:
        raise NotFoundException(
            "No Google Calendar integration found. Please connect your calendar first."
        )
    
    if integration.needs_reauth():
        raise CalendarAuthError("Calendar integration requires re-authentication")
    
    try:
        calendars = await service.list_calendars(integration)
        
        return success_response(
            status_code=status.HTTP_200_OK,
            message="Calendars retrieved successfully",
            data=jsonable_encoder(CalendarListResponse(
                calendars=[
                    CalendarListItem(
                        id=cal["id"],
                        summary=cal["summary"],
                        description=cal.get("description"),
                        primary=cal.get("primary", False),
                    )
                    for cal in calendars
                ]
            )),
        )
        
    except CalendarAuthError:
        raise CalendarAuthError(
            "Calendar authentication failed. Please reconnect your calendar."
        )
    except CalendarAPIError as e:
        logger.error(f"Failed to list calendars: {e}")
        raise CalendarAPIError("Failed to fetch calendars from Google")
