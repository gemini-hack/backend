import asyncio
import concurrent.futures
from app.celery_app import celery_app
from app.utils.logger import logger
from app.db.database import get_celery_session
from app.services.email_service import EmailService


def run_async(coro):
    """Run async code safely in Celery worker."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(coro)

@celery_app.task(
    bind=True,
    max_retries=5,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    acks_late=True,
)
def send_verification_email_task(self, to_email: str, token: str):
    """Send verification email. Failed messages go to DLQ."""
    logger.info(f"[Attempt {self.request.retries + 1}/{self.max_retries + 1}] Sending verification email to {to_email}")
    
    async def run_task():
        async with get_celery_session() as session:
            service = EmailService(session)
            await service.send_verification_email(to_email, token)
    
    run_async(run_task())
    logger.info(f"Verification email sent successfully to {to_email}")
    return {"status": "success", "email": to_email}


@celery_app.task(
    bind=True,
    max_retries=5,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    acks_late=True,
)
def send_invitation_email_task(
    self,
    to_email: str,
    inviter_name: str,
    organization_name: str,
    invitation_link: str,
    expires_at_str: str
):
    """Send invitation email. Failed messages go to DLQ."""
    logger.info(f"[Attempt {self.request.retries + 1}/{self.max_retries + 1}] Sending invitation email to {to_email}")
    
    async def run_task():
        async with get_celery_session() as session:
            service = EmailService(session)
            await service.send_invitation_email(
                to_email, inviter_name, organization_name, invitation_link, expires_at_str
            )
    
    run_async(run_task())
    logger.info(f"Invitation email sent successfully to {to_email}")
    return {"status": "success", "email": to_email}


@celery_app.task(
    bind=True,
    max_retries=5,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    acks_late=True,
)
def send_password_reset_email_task(self, to_email: str, reset_token: str):
    """Send password reset email. Failed messages go to DLQ."""
    logger.info(f"[Attempt {self.request.retries + 1}/{self.max_retries + 1}] Sending password reset email to {to_email}")
    
    async def run_task():
        async with get_celery_session() as session:
            service = EmailService(session)
            await service.send_password_reset_email(to_email, reset_token)
    
    run_async(run_task())
    logger.info(f"Password reset email sent successfully to {to_email}")
    return {"status": "success", "email": to_email}
