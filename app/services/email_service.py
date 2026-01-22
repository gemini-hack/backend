from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Dict, Any
import aiosmtplib
from jinja2 import Template
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.utils.logger import logger
from app.models.template import EmailTemplate
from app.utils.exceptions import EmailDeliveryError


class EmailService:
    """Service for sending emails using SMTP and DB templates."""

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db
        self.host = settings.SMTP_HOST
        self.port = settings.SMTP_PORT
        self.user = settings.SMTP_USER
        self.password = settings.SMTP_PASSWORD
        self.tls = settings.SMTP_TLS
        self.sender = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"

    async def _get_rendered_template(self, slug: str, context: Dict[str, Any]) -> tuple[str, str]:
        """Fetch template from DB and render it. Returns (subject, html_body)."""
        subject = ""
        html_body = ""

        if self.db:
            template = await EmailTemplate.query(self.db).filter(EmailTemplate.slug == slug).one_or_none()
            if template:
                subject_tmpl = Template(template.subject)
                html_tmpl = Template(template.html_body)
                subject = subject_tmpl.render(**context)
                html_body = html_tmpl.render(**context)
                return subject, html_body
            else:
                logger.warning(f"Email template '{slug}' not found in database. Using fallback.")
        
        # Fallbacks if DB not available or template missing
        if slug == "worker_invitation":
            subject = f"You've been invited to join {context.get('organization_name')} on {settings.APP_NAME}"
            html_body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2>Hello!</h2>
                <p>{context.get('inviter_name')} has invited you to join <strong>{context.get('organization_name')}</strong> on {settings.APP_NAME}.</p>
                <p>Click the button below to accept your invitation and set up your account:</p>
                <p style="text-align: center; margin: 30px 0;">
                    <a href="{context.get('invitation_link')}" style="background-color: #4F46E5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold;">Accept Invitation</a>
                </p>
                <p>This link expires on {context.get('expires_at')}.</p>
            </div>
            """
        elif slug == "password_reset":
             subject = f"Reset your password for {settings.APP_NAME}"
             html_body = f"""
             <div>
                <h2>Reset Password</h2>
                <p>Click <a href="{settings.FRONTEND_URL}/reset-password?token={context.get('reset_token')}">here</a> to reset.</p>
             </div>
             """
        elif slug == "email_verification":
             subject = f"Verify your email for {settings.APP_NAME}"
             html_body = f"""
             <div>
                <h2>Verify Email</h2>
                <p>Click <a href="{settings.FRONTEND_URL}/verify-email?token={context.get('token')}">here</a> to verify.</p>
             </div>
             """
        
        return subject, html_body

    async def _send(self, to_email: str, subject: str, html_content: str) -> bool:
        """Internal method to send email via SMTP. Raises EmailDeliveryError on failure."""
        if not self.host or self.host == "localhost":
             logger.warning(f"SMTP not configured. Mocking email send to {to_email}: {subject}")
             return True

        # Proper TLS handling based on port
        use_tls = self.tls if self.port == 465 else False
        start_tls = self.tls if self.port == 587 else False

        message = MIMEMultipart()
        message["From"] = self.sender
        message["To"] = to_email
        message["Subject"] = subject
        message.attach(MIMEText(html_content, "html"))

        try:
            await aiosmtplib.send(
                message,
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                use_tls=use_tls,
                start_tls=start_tls,
                timeout=30
            )
            logger.info(f"Email sent to {to_email}: {subject}")
            return True
        except Exception as e:
            error_msg = f"Failed to send email to {to_email}: {str(e)}"
            logger.error(error_msg)
            raise EmailDeliveryError(error_msg, to_email, e)

    async def send_invitation_email(
        self, 
        to_email: str, 
        inviter_name: str, 
        organization_name: str, 
        invitation_link: str, 
        expires_at: Any
    ):
        """Send worker invitation email."""
        context = {
            "inviter_name": inviter_name,
            "organization_name": organization_name,
            "invitation_link": invitation_link,
            "expires_at": expires_at.strftime('%Y-%m-%d %H:%M UTC') if hasattr(expires_at, 'strftime') else str(expires_at),
            "app_name": settings.APP_NAME
        }
        subject, html = await self._get_rendered_template("worker_invitation", context)
        await self._send(to_email, subject, html)

    async def send_password_reset_email(self, to_email: str, reset_token: str):
        """Send password reset email."""
        context = {
            "reset_token": reset_token,
            "reset_link": f"{settings.FRONTEND_URL}/reset-password?token={reset_token}",
            "app_name": settings.APP_NAME
        }
        subject, html = await self._get_rendered_template("password_reset", context)
        await self._send(to_email, subject, html)

    async def send_verification_email(self, to_email: str, token: str):
        """Send email verification link."""
        context = {
            "token": token,
            "verify_link": f"{settings.FRONTEND_URL}/verify-email?token={token}",
            "app_name": settings.APP_NAME
        }
        subject, html = await self._get_rendered_template("email_verification", context)
        
        
        logger.info(f"VERIFICATION LINK FOR {to_email}: {context['verify_link']}")
        
        await self._send(to_email, subject, html)

    async def send_appointment_reminder(
        self,
        to_email: str,
        patient_name: str,
        appointment_time: str,
        appointment_type: str,
        provider_name: str | None = None,
    ) -> bool:
        """
        Send appointment reminder email.
        
        Args:
            to_email: Patient email address
            patient_name: Patient's first name
            appointment_time: Formatted appointment time string
            appointment_type: Type of appointment (e.g., "Follow-up", "Lab Review")
            provider_name: Optional provider/doctor name
        
        Returns:
            True if sent successfully
        """
        context = {
            "patient_name": patient_name,
            "appointment_time": appointment_time,
            "appointment_type": appointment_type,
            "provider_name": provider_name or "your healthcare provider",
            "app_name": settings.APP_NAME,
        }
        subject, html = await self._get_rendered_template("appointment_reminder", context)
        
        # Fallback if template not in DB
        if not html:
            subject = f"Appointment Reminder - {settings.APP_NAME}"
            html = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2>Appointment Reminder</h2>
                <p>Hi {patient_name},</p>
                <p>This is a reminder about your upcoming <strong>{appointment_type}</strong> appointment:</p>
                <div style="background-color: #f5f5f5; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 0;"><strong>Date & Time:</strong> {appointment_time}</p>
                    <p style="margin: 5px 0 0 0;"><strong>With:</strong> {provider_name or "your healthcare provider"}</p>
                </div>
                <p>If you need to reschedule, please contact us as soon as possible.</p>
                <p>Thank you,<br>{settings.APP_NAME} Team</p>
            </div>
            """
        
        await self._send(to_email, subject, html)
        return True

    async def send_no_show_followup(
        self,
        to_email: str,
        patient_name: str,
    ) -> bool:
        """Send follow-up email after a no-show."""
        subject = f"We missed you - {settings.APP_NAME}"
        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2>We Missed You</h2>
            <p>Hi {patient_name},</p>
            <p>We noticed you weren't able to make your appointment. Your health is important to us!</p>
            <p>Please reach out to reschedule at your earliest convenience.</p>
            <p>Thank you,<br>{settings.APP_NAME} Team</p>
        </div>
        """
        await self._send(to_email, subject, html)
        return True

