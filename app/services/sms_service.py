"""
SMS Service - Twilio SMS wrapper for appointment reminders.

Provides HIPAA-compliant SMS messaging with rate limiting and audit logging.
"""
from datetime import date
from typing import Optional

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

from app.core.config import settings
from app.core.redis import RedisManager
from app.models.appointment import Appointment
from app.utils.logger import logger
from app.utils.exceptions import BaseAPIException
from app.core.observability import trace_method


class SMSRateLimitExceeded(BaseAPIException):
    """Raised when daily SMS limit is exceeded."""
    def __init__(self, organization_id: str):
        super().__init__(
            status_code=429,
            message=f"Daily SMS limit exceeded for organization {organization_id}"
        )


class SMSDeliveryError(BaseAPIException):
    """Raised when SMS delivery fails."""
    def __init__(self, message: str, to_phone: str, original_error: Optional[Exception] = None):
        super().__init__(
            status_code=502,
            detail=f"Failed to send SMS to {to_phone}: {message}"
        )
        self.to_phone = to_phone
        self.original_error = original_error


class SMSService:
    """
    Twilio SMS wrapper with rate limiting.
    
    Features:
    - Rate limiting per organization (configurable daily limit)
    - Idempotency support to prevent duplicate sends
    - HIPAA-compliant messaging (no PHI in SMS content)
    - Audit logging for all sends
    
    Complexity Analysis:
    - Time: O(1) for send operations
    - Space: O(1) - no data stored in memory
    """
    
    # Rate limit settings (from config, with fallbacks)
    MAX_SMS_PER_DAY = getattr(settings, 'MAX_SMS_PER_DAY_PER_ORG', 500)
    RATE_LIMIT_KEY_PREFIX = getattr(settings, 'REMINDER_RATE_LIMIT_KEY_PREFIX', 'reminder_limit')
    
    def __init__(self):
        self.account_sid = settings.TWILIO_ACCOUNT_SID
        self.auth_token = settings.TWILIO_AUTH_TOKEN
        self.from_number = settings.TWILIO_PHONE_NUMBER
        self._client: Optional[Client] = None
    
    @property
    def client(self) -> Client:
        """Lazy initialization of Twilio client."""
        if self._client is None:
            if not self.account_sid or not self.auth_token:
                raise SMSDeliveryError("Twilio credentials not configured", "N/A")
            self._client = Client(self.account_sid, self.auth_token)
        return self._client
    
    def is_configured(self) -> bool:
        """Check if SMS service is properly configured."""
        return bool(
            self.account_sid and 
            self.auth_token and 
            self.from_number
        )
    
    async def _check_rate_limit(self, organization_id: str) -> None:
        """
        Check and increment daily SMS rate limit.
        
        Raises:
            SMSRateLimitExceeded: If daily limit exceeded
        """
        redis = RedisManager.get_client()
        key = f"{self.RATE_LIMIT_KEY_PREFIX}:sms:{organization_id}:{date.today().isoformat()}"
        
        count = await redis.incr(key)
        if count == 1:
            # Set expiry on first increment (24 hours)
            await redis.expire(key, 86400)
        
        if count > self.MAX_SMS_PER_DAY:
            logger.warning(f"SMS rate limit exceeded for org {organization_id}: {count}/{self.MAX_SMS_PER_DAY}")
            raise SMSRateLimitExceeded(organization_id)
    
    async def _check_idempotency(self, idempotency_key: str) -> bool:
        """
        Check if this message was already sent.
        
        Returns:
            True if already sent (should skip), False if new
        """
        redis = RedisManager.get_client()
        key = f"sms_sent:{idempotency_key}"
        
        existing = await redis.get(key)
        if existing:
            logger.info(f"SMS already sent with idempotency key: {idempotency_key}")
            return True
        
        # Mark as sent (expires in 7 days)
        await redis.setex(key, 604800, "sent")
        return False
    
    @trace_method("sms.send_reminder")
    async def send_appointment_reminder(
        self,
        to_phone: str,
        patient_name: str,
        appointment: Appointment,
        organization_id: str,
        idempotency_key: Optional[str] = None,
    ) -> str:
        """
        Send appointment reminder via SMS.
        
        HIPAA Note: Message contains NO PHI - only appointment time and generic text.
        
        Args:
            to_phone: Patient phone number (E.164 format preferred)
            patient_name: Patient's first name only
            appointment: Appointment object
            organization_id: Organization UUID (for rate limiting)
            idempotency_key: Optional key to prevent duplicate sends
        
        Returns:
            Twilio message SID
        
        Raises:
            SMSRateLimitExceeded: If daily limit exceeded
            SMSDeliveryError: If send fails
        """
        if not self.is_configured():
            logger.warning("SMS service not configured, skipping send")
            raise SMSDeliveryError("SMS service not configured", to_phone)
        
        # Check idempotency
        if idempotency_key:
            already_sent = await self._check_idempotency(idempotency_key)
            if already_sent:
                return "DUPLICATE_SKIPPED"
        
        # Check rate limit
        await self._check_rate_limit(organization_id)
        
        # Build HIPAA-compliant message (no PHI)
        appt_time = appointment.scheduled_time.strftime('%B %d at %I:%M %p')
        message_body = (
            f"Hi {patient_name}, this is a reminder about your appointment on {appt_time}. "
            f"Reply CONFIRM to confirm or call us to reschedule."
        )
        
        try:
            message = self.client.messages.create(
                to=to_phone,
                from_=self.from_number,
                body=message_body,
            )
            
            logger.info(f"SMS sent successfully: {message.sid} to {to_phone}")
            return message.sid
            
        except TwilioRestException as e:
            logger.error(f"Twilio SMS failed: {e.code} - {e.msg}")
            raise SMSDeliveryError(str(e.msg), to_phone, e)
        except Exception as e:
            logger.exception(f"Unexpected SMS error: {e}")
            raise SMSDeliveryError(str(e), to_phone, e)
    
    async def send_no_show_followup(
        self,
        to_phone: str,
        patient_name: str,
        organization_id: str,
        idempotency_key: Optional[str] = None,
    ) -> str:
        """
        Send follow-up SMS after a no-show.
        
        Args:
            to_phone: Patient phone number
            patient_name: Patient's first name
            organization_id: Organization UUID
            idempotency_key: Optional idempotency key
        
        Returns:
            Twilio message SID
        """
        if not self.is_configured():
            raise SMSDeliveryError("SMS service not configured", to_phone)
        
        if idempotency_key:
            already_sent = await self._check_idempotency(idempotency_key)
            if already_sent:
                return "DUPLICATE_SKIPPED"
        
        await self._check_rate_limit(organization_id)
        
        message_body = (
            f"Hi {patient_name}, we missed you at your appointment. "
            f"Please call us to reschedule. Your health is important to us."
        )
        
        try:
            message = self.client.messages.create(
                to=to_phone,
                from_=self.from_number,
                body=message_body,
            )
            
            logger.info(f"No-show followup SMS sent: {message.sid}")
            return message.sid
            
        except TwilioRestException as e:
            raise SMSDeliveryError(str(e.msg), to_phone, e)

    async def send_generic_sms(
        self,
        to_phone: str,
        message_body: str,
        organization_id: str,
    ) -> str:
        """
        Send a generic SMS (e.g., for Engagement Nudges).
        """
        if not self.is_configured():
            raise SMSDeliveryError("SMS service not configured", to_phone)
            
        await self._check_rate_limit(organization_id)
        
        try:
            message = self.client.messages.create(
                to=to_phone,
                from_=self.from_number,
                body=message_body,
            )
            logger.info(f"Generic SMS sent: {message.sid} to {to_phone}")
            return message.sid
            
        except TwilioRestException as e:
            logger.error(f"Twilio SMS failed: {e.code} - {e.msg}")
            raise SMSDeliveryError(str(e.msg), to_phone, e)
