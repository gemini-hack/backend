import httpx
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from typing import Optional, List, Any
from uuid import UUID

from sqlalchemy import select
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.core.config import settings
from app.models.calendar import CalendarIntegration, CalendarProvider, IntegrationStatus
from app.services.base import BaseService
from app.utils.exceptions import (
    CalendarServiceError,
    CalendarAuthError,
    CalendarAPIError,
    CalendarTokenExpiredError,
    CalendarRateLimitError,
)
from app.utils.logger import logger
from app.utils.security import create_access_token, decode_token


# HTTP client configuration
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
DEFAULT_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20)

# Shared HTTP client for connection pooling
_http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    """Get or create a shared HTTP client with connection pooling."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=DEFAULT_LIMITS,
        )
    return _http_client


class GoogleCalendarService(BaseService):
    """Service for Google Calendar OAuth2 and API operations."""
    
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
    AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
    CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
    USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"
    
    # OAuth scopes
    SCOPES = [
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/userinfo.email",
    ]
    
    def generate_oauth_state(self, user_id: str) -> str:
        """Generate a secure, signed OAuth state parameter."""
        return create_access_token(
            user_id=user_id,
            organization_id="oauth",
            role="oauth_state",
            session_id=secrets.token_urlsafe(16),
            expires_delta=timedelta(minutes=10),
        )
    
    def verify_oauth_state(self, state: str) -> Optional[str]:
        """Verify OAuth state and extract user ID. Returns None if invalid."""
        try:
            payload = decode_token(state)
            if payload.get("role") != "oauth_state":
                logger.warning("Invalid OAuth state: wrong token type")
                return None
            return payload.get("sub")
        except Exception as e:
            logger.warning(f"OAuth state verification failed: {e}")
            return None
    
    def get_auth_url(self, user_id: str) -> str:
        """Generate the Google OAuth2 consent URL with secure state."""
        state = self.generate_oauth_state(user_id)
        
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{self.AUTH_ENDPOINT}?{urlencode(params)}"
    
    async def _fetch_user_email(self, access_token: str) -> Optional[str]:
        """Fetch the email address of the authenticated Google account."""
        try:
            client = get_http_client()
            resp = await client.get(
                self.USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            
            if resp.status_code == 200:
                return resp.json().get("email")
            else:
                logger.warning(f"Failed to fetch user email: {resp.status_code}")
                return None
        except Exception as e:
            logger.warning(f"Error fetching user email: {e}")
            return None
    
    async def exchange_code(self, code: str, state: str) -> CalendarIntegration:
        """Exchange authorization code for tokens with state validation."""
        # Verify state and extract user_id
        user_id = self.verify_oauth_state(state)
        if not user_id:
            raise CalendarAuthError(
                "Invalid or expired OAuth state",
                details={"error": "state_invalid"}
            )
        
        client = get_http_client()
        
        try:
            resp = await client.post(
                self.TOKEN_ENDPOINT,
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                },
            )
        except httpx.TimeoutException:
            raise CalendarAPIError("Token exchange timed out", status_code=504)
        except httpx.RequestError as e:
            raise CalendarAPIError(f"Network error during token exchange: {e}")
        
        if resp.status_code != 200:
            error_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            logger.error(f"Google Token Exchange Failed: {resp.text}")
            raise CalendarAPIError(
                "Failed to exchange code for tokens",
                status_code=resp.status_code,
                details=error_data,
            )
        
        data = resp.json()
        
        # Extract tokens
        access_token = data["access_token"]
        refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in", 3600)
        expiry_date = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        # Fetch the connected account's email
        email = await self._fetch_user_email(access_token)
                
        # Check for existing integration to update
        stmt = select(CalendarIntegration).where(
            CalendarIntegration.user_id == user_id,
            CalendarIntegration.provider == CalendarProvider.GOOGLE,
        )
        result = await self.db.execute(stmt)
        integration = result.scalar_one_or_none()
        
        if integration:
            integration.access_token = access_token
            integration.token_expiry = expiry_date
            integration.status = IntegrationStatus.ACTIVE
            integration.email = email
            integration.last_synced_at = datetime.now(timezone.utc)
            if refresh_token:
                integration.refresh_token = refresh_token
        else:
            if not refresh_token:
                logger.warning("No refresh token received during initial link")
            
            integration = CalendarIntegration(
                user_id=user_id,
                provider=CalendarProvider.GOOGLE,
                status=IntegrationStatus.ACTIVE,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expiry=expiry_date,
                email=email,
                last_synced_at=datetime.now(timezone.utc),
            )
            self.db.add(integration)
        
        await self.db.commit()
        await self.db.refresh(integration)
        
        logger.info(f"Google Calendar connected for user {user_id}, email: {email}")
        return integration
    
    async def get_valid_token(self, integration: CalendarIntegration) -> str:
        """Get a valid access token, refreshing if necessary."""
        if integration.needs_reauth():
            raise CalendarTokenExpiredError(
                "Integration requires re-authentication",
                details={"status": "needs_reauth"}
            )
        
        access_token = integration.access_token
        
        if integration.token_expiry and integration.token_expiry > datetime.now(timezone.utc) + timedelta(minutes=5):
            return access_token
        
        if not integration.refresh_token:
            integration.mark_needs_reauth()
            await self.db.commit()
            raise CalendarTokenExpiredError(
                "No refresh token available and access token expired",
                details={"status": "needs_reauth"}
            )
        
        refresh_token = integration.refresh_token 
        
        client = get_http_client()
        
        try:
            resp = await client.post(
                self.TOKEN_ENDPOINT,
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.TimeoutException:
            raise CalendarAPIError("Token refresh timed out", status_code=504)
        except httpx.RequestError as e:
            raise CalendarAPIError(f"Network error during token refresh: {e}")
        
        if resp.status_code == 400:
            # Usually means refresh token is invalid/revoked
            error_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if error_data.get("error") == "invalid_grant":
                logger.warning(f"Refresh token revoked for integration {integration.id}")
                integration.mark_needs_reauth()
                await self.db.commit()
                raise CalendarTokenExpiredError(
                    "Refresh token has been revoked",
                    details={"error": "invalid_grant", "status": "needs_reauth"}
                )
        
        if resp.status_code != 200:
            logger.error(f"Token Refresh Failed: {resp.text}")
            raise CalendarAPIError(
                "Failed to refresh token",
                status_code=resp.status_code,
            )
        
        data = resp.json()
        new_access_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        
        integration.access_token = new_access_token # Transparently encrypted
        integration.token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        integration.status = IntegrationStatus.ACTIVE
        
        await self.db.commit()
        
        return new_access_token
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(CalendarAPIError),
        reraise=True,
    )
    async def get_busy_periods(
        self,
        integration: CalendarIntegration,
        start_time: datetime,
        end_time: datetime,
        calendar_ids: Optional[List[str]] = None,
    ) -> List[tuple[datetime, datetime]]:
        """Query Google Calendar Free/Busy API for busy periods."""
        token = await self.get_valid_token(integration)
        
        if not calendar_ids:
            calendar_ids = ["primary"]
        
        body = {
            "timeMin": start_time.isoformat(),
            "timeMax": end_time.isoformat(),
            "items": [{"id": cal_id} for cal_id in calendar_ids],
        }
        
        client = get_http_client()
        
        try:
            resp = await client.post(
                f"{self.CALENDAR_API_BASE}/freeBusy",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        except httpx.TimeoutException:
            raise CalendarAPIError("Free/Busy check timed out", status_code=504)
        except httpx.RequestError as e:
            raise CalendarAPIError(f"Network error during Free/Busy check: {e}")
        
        if resp.status_code == 401:
            integration.mark_needs_reauth()
            await self.db.commit()
            raise CalendarAuthError("Access token invalid", details={"status": "needs_reauth"})
        
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            raise CalendarRateLimitError(retry_after=retry_after)
        
        if resp.status_code != 200:
            logger.error(f"Free/Busy Check Failed: {resp.text}")
            raise CalendarAPIError(
                "Free/Busy check failed",
                status_code=resp.status_code,
            )
        
        data = resp.json()
        calendars = data.get("calendars", {})
        
        result = []
        for cal_id in calendar_ids:
            cal_data = calendars.get(cal_id, {})
            busy_periods = cal_data.get("busy", [])
            
            for slot in busy_periods:
                # Parse ISO strings (Google returns Z-terminated strings)
                start = datetime.fromisoformat(slot["start"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(slot["end"].replace("Z", "+00:00"))
                result.append((start, end))
        
        integration.last_synced_at = datetime.now(timezone.utc)
        await self.db.commit()
        
        return result
    
    async def list_calendars(self, integration: CalendarIntegration) -> List[dict]:
        """List all calendars accessible by the user."""
        token = await self.get_valid_token(integration)
        
        client = get_http_client()
        
        try:
            resp = await client.get(
                f"{self.CALENDAR_API_BASE}/users/me/calendarList",
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.TimeoutException:
            raise CalendarAPIError("Calendar list request timed out", status_code=504)
        except httpx.RequestError as e:
            raise CalendarAPIError(f"Network error fetching calendar list: {e}")
        
        if resp.status_code != 200:
            logger.error(f"Calendar List Failed: {resp.text}")
            raise CalendarAPIError(
                "Failed to list calendars",
                status_code=resp.status_code,
            )
        
        items = resp.json().get("items", [])
        return [
            {
                "id": cal["id"],
                "summary": cal.get("summary", cal["id"]),
                "description": cal.get("description"),
                "primary": cal.get("primary", False),
            }
            for cal in items
        ]
    
    async def revoke_access(self, integration: CalendarIntegration) -> bool:
        """Revoke the OAuth token at Google and delete the integration."""
        try:
            # Get a valid token to revoke (or use refresh token)
            token_to_revoke = integration.refresh_token or integration.access_token # Transparently decrypted
            
            if token_to_revoke:
                client = get_http_client()
                await client.post(
                    self.REVOKE_ENDPOINT,
                    params={"token": token_to_revoke},
                )
        except Exception as e:
            logger.warning(f"Token revocation failed (continuing with deletion): {e}")
        
        await self.db.delete(integration)
        await self.db.commit()
        
        logger.info(f"Google Calendar disconnected for user {integration.user_id}")
        return True
    
    async def get_integration(self, user_id: UUID) -> Optional[CalendarIntegration]:
        """Get the Google Calendar integration for a user."""
        stmt = select(CalendarIntegration).where(
            CalendarIntegration.user_id == user_id,
            CalendarIntegration.provider == CalendarProvider.GOOGLE,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
