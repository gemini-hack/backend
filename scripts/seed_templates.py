import asyncio
import sys
import os

# Add parent directory to path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session_factory
from app.models.template import EmailTemplate

TEMPLATES = [
    {
        "slug": "worker_invitation",
        "subject": "You've been invited to join {{ organization_name }} on {{ app_name }}",
        "html_body": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333;">
    <h2 style="color: #4F46E5;">Hello!</h2>
    <p><strong>{{ inviter_name }}</strong> has invited you to join <strong>{{ organization_name }}</strong> on {{ app_name }}.</p>
    <p>Click the button below to accept your invitation and set up your account:</p>
    <p style="text-align: center; margin: 30px 0;">
        <a href="{{ invitation_link }}" style="background-color: #4F46E5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold;">Accept Invitation</a>
    </p>
    <p>This link expires on {{ expires_at }}.</p>
    <p>If you didn't expect this invitation, you can ignore this email.</p>
    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
    <p style="color: #666; font-size: 12px;">The {{ app_name }} Team</p>
</div>
        """,
        "variables": ["inviter_name", "organization_name", "app_name", "invitation_link", "expires_at"]
    },
    {
        "slug": "password_reset",
        "subject": "Reset your password for {{ app_name }}",
        "html_body": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333;">
    <h2 style="color: #4F46E5;">Reset Your Password</h2>
    <p>We received a request to reset your password for your {{ app_name }} account.</p>
    <p>Click the button below to choose a new password:</p>
    <p style="text-align: center; margin: 30px 0;">
        <a href="{{ reset_link }}" style="background-color: #4F46E5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold;">Reset Password</a>
    </p>
    <p>This link expires in 15 minutes.</p>
    <p>If you didn't ask for this, you can safely ignore this email.</p>
    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
    <p style="color: #666; font-size: 12px;">The {{ app_name }} Team</p>
</div>
        """,
        "variables": ["app_name", "reset_link"]
    },
    {
        "slug": "email_verification",
        "subject": "Verify your email for {{ app_name }}",
        "html_body": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333;">
    <h2 style="color: #4F46E5;">Verify Your Email</h2>
    <p>Thanks for signing up for {{ app_name }}! Please verify your email address to get started.</p>
    <p style="text-align: center; margin: 30px 0;">
        <a href="{{ verify_link }}" style="background-color: #4F46E5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold;">Verify Email</a>
    </p>
    <p>If you didn't create an account, you can ignore this email.</p>
    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
    <p style="color: #666; font-size: 12px;">The {{ app_name }} Team</p>
</div>
        """,
        "variables": ["app_name", "verify_link"]
    }
]

async def seed_templates():
    print("Beginning template seed...")
    async with async_session_factory() as session:
        for tmpl_data in TEMPLATES:
            # Check if exists
            existing = await EmailTemplate.query(session).filter(EmailTemplate.slug == tmpl_data["slug"]).one_or_none()
            if existing:
                print(f"Updating template: {tmpl_data['slug']}")
                existing.subject = tmpl_data["subject"]
                existing.html_body = tmpl_data["html_body"]
                existing.variables = tmpl_data["variables"]
            else:
                print(f"Creating template: {tmpl_data['slug']}")
                new_tmpl = EmailTemplate(**tmpl_data)
                session.add(new_tmpl)
        
        await session.commit()
    print("Template seeding complete!")

if __name__ == "__main__":
    asyncio.run(seed_templates())
