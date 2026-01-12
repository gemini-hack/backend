from app.celery_app import celery_app
from app.utils.logger import logger
from app.db.database import async_session_factory
import asyncio

@celery_app.task(
    name="app.tasks.email.send_verification_email_task",
    retry_backoff=True,
    max_retries=3,
    autoretry_for=(Exception,)
)
def send_verification_email_task(to_email: str, token: str):
    """Celery task to send verification emails."""
    from app.services.email_service import EmailService
    logger.info(f"Background task: Sending verification email to {to_email}")
    async def run_task():
        async with async_session_factory() as session:
            service = EmailService(session)
            await service.send_verification_email(to_email, token)
    
    asyncio.run(run_task())

@celery_app.task(
    name="app.tasks.email.send_invitation_email_task",
    retry_backoff=True,
    max_retries=3,
    autoretry_for=(Exception,)
)
def send_invitation_email_task(
    to_email: str, 
    inviter_name: str, 
    organization_name: str, 
    invitation_link: str, 
    expires_at_str: str
):
    """Celery task to send invitation emails."""
    from app.services.email_service import EmailService
    logger.info(f"Background task: Sending invitation email to {to_email}")
    async def run_task():
        async with async_session_factory() as session:
            service = EmailService(session)
            await service.send_invitation_email(
                to_email, 
                inviter_name, 
                organization_name, 
                invitation_link, 
                expires_at_str
            )

    asyncio.run(run_task())

@celery_app.task(
    name="app.tasks.email.send_password_reset_email_task",
    retry_backoff=True,
    max_retries=3,
    autoretry_for=(Exception,)
)
def send_password_reset_email_task(to_email: str, reset_token: str):
    """Celery task to send password reset emails."""
    from app.services.email_service import EmailService
    logger.info(f"Background task: Sending password reset email to {to_email}")
    async def run_task():
        async with async_session_factory() as session:
            service = EmailService(session)
            await service.send_password_reset_email(to_email, reset_token)

    asyncio.run(run_task())
