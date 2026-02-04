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
    },
    {
        "slug": "appointment_reminder",
        "subject": "📅 Reminder: Appointment with {{ provider_name }} tomorrow",
        "html_body": """
<div style="font-family: 'Inter', system-ui, -apple-system, sans-serif; max-width: 600px; margin: 0 auto; color: #1F2937;">
    
    <div style="background: linear-gradient(135deg, #4F46E5 0%, #818CF8 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 22px;">Upcoming Appointment</h1>
    </div>

    <div style="border: 1px solid #E5E7EB; border-top: none; border-radius: 0 0 12px 12px; padding: 30px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
        <p style="font-size: 16px;">Hi {{ patient_name }},</p>
        
        <p style="font-size: 16px;">This is a friendly reminder for your <strong>{{ appointment_type }}</strong>.</p>

        <div style="display: flex; gap: 20px; margin: 25px 0; flex-wrap: wrap;">
            <div style="flex: 1; min-width: 200px; background: #F9FAFB; padding: 15px; border-radius: 8px; border: 1px solid #E5E7EB;">
                <div style="color: #6B7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 5px;">When</div>
                <div style="font-weight: 600; font-size: 16px; color: #111827;">{{ appointment_time }}</div>
                <div style="font-size: 14px; color: #4B5563; margin-top: 2px;">{{ appointment_date }}</div>
            </div>
            <div style="flex: 1; min-width: 200px; background: #F9FAFB; padding: 15px; border-radius: 8px; border: 1px solid #E5E7EB;">
                <div style="color: #6B7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 5px;">With</div>
                <div style="font-weight: 600; font-size: 16px; color: #111827;">{{ provider_name }}</div>
                <div style="font-size: 14px; color: #4B5563; margin-top: 2px;">{{ organization_name }}</div>
            </div>
        </div>

        {% if notes %}
        <div style="background-color: #FFFBEB; border: 1px solid #FCD34D; padding: 15px; border-radius: 6px; margin-bottom: 20px;">
            <strong style="color: #92400E;">Note from Clinic:</strong>
            <span style="color: #B45309;">{{ notes }}</span>
        </div>
        {% endif %}

        <p style="margin-top: 20px; font-size: 14px; color: #6B7280;">
            Please arrive 15 minutes early. Need to reschedule? <a href="tel:{{ clinic_phone }}" style="color: #4F46E5; font-weight: 600; text-decoration: none;">Call us</a>.
        </p>
        
        <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 25px 0;">
        
        <p style="text-align: center; color: #9CA3AF; font-size: 12px;">
            Sent by {{ app_name }} on behalf of {{ organization_name }}
        </p>
    </div>
</div>
        """,
        "variables": ["patient_name", "appointment_type", "appointment_date", "appointment_time", "provider_name", "notes", "clinic_phone", "app_name", "organization_name"]
    },
    {
        "slug": "engagement_nudge",
        "subject": "{% if urgency == 'critical' or urgency == 'high' %}⚠️ Health Alert: We're missing your recent logs{% else %}Checking in: How are you feeling, {{ patient_name }}? 👋{% endif %}",
        "html_body": """
<div style="font-family: 'Inter', system-ui, -apple-system, sans-serif; max-width: 600px; margin: 0 auto; color: #1F2937;">
    
    <!-- Header -->
    <div style="text-align: center; padding: 20px 0;">
        <h2 style="color: #4F46E5; margin: 0; font-size: 24px;">{{ app_name }}</h2>
    </div>

    <!-- Alert Box for High Priority -->
    {% if urgency == 'critical' or urgency == 'high' %}
    <div style="background-color: #FEF2F2; border-left: 4px solid #EF4444; padding: 15px; margin-bottom: 20px; border-radius: 4px;">
        <p style="margin: 0; color: #991B1B; font-weight: 500;">
            ⚠️ <strong>Action Required:</strong> We haven't received your health data in over {{ days_since_last_reading }} days.
        </p>
    </div>
    {% endif %}

    <div style="background: white; padding: 30px; border-radius: 12px; border: 1px solid #E5E7EB; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
        <p style="font-size: 16px;">Hi <strong>{{ patient_name }}</strong>,</p>

        {% if urgency == 'critical' or urgency == 'high' %}
            <p style="font-size: 16px; line-height: 1.5;">Your care team is concerned because consistent tracking is vital for managing your condition effectively. Gaps in data can delay important adjustments to your treatment.</p>
        {% else %}
            <p style="font-size: 16px; line-height: 1.5;">We noticed it's been a few days since your last check-in. We know life gets busy, but consistent tracking helps us keep you healthy!</p>
        {% endif %}

        <div style="background-color: #F3F4F6; padding: 25px; border-radius: 12px; margin: 25px 0; text-align: center;">
            <p style="margin: 0 0 15px 0; font-size: 16px; color: #374151;">
                It only takes <strong>2 minutes</strong> to update your status.
            </p>
            <a href="{{ log_link }}" style="display: inline-block; background-color: #4F46E5; color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; box-shadow: 0 4px 6px rgba(79, 70, 229, 0.2);">
                Update My Health Log
            </a>
        </div>

        <p style="color: #6B7280; font-size: 14px; margin-top: 20px;">
            If you are having technical issues or trouble with your medication, please reply to this email.
        </p>

        <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 30px 0;">
        
        <p style="text-align: center; color: #9CA3AF; font-size: 12px;">
            Sent with care by your team at {{ organization_name }}
        </p>
    </div>
</div>
        """,
        "variables": ["patient_name", "days_since_last_reading", "app_name", "organization_name", "log_link", "urgency"]
    },
    {
        "slug": "refill_reminder",
        "subject": "{% if urgency == 'critical' %}⚠️ Urgent: Medication refill overdue{% else %}Pharmacy Reminder: Refill due soon{% endif %}",
        "html_body": """
<div style="font-family: 'Inter', system-ui, -apple-system, sans-serif; max-width: 600px; margin: 0 auto; color: #1F2937;">
    
    <div style="text-align: center; padding-bottom: 20px; border-bottom: 2px solid #F3F4F6; margin-bottom: 20px;">
        <span style="background-color: #ECFDF5; color: #059669; padding: 6px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">Medication Adherence</span>
    </div>

    <div style="background: white; padding: 20px;">
        <h2 style="color: #111827; margin-top: 0; font-size: 20px;">Hi {{ patient_name }},</h2>

        {% if urgency == 'critical' %}
        <p style="font-size: 16px;">Our records show your supply of <strong>{{ current_regimen }}</strong> may have run out. <span style="background-color: #FEF2F2; color: #B91C1C; padding: 2px 4px; border-radius: 2px; font-weight: 600;">Do not skip doses.</span></p>
        {% else %}
        <p style="font-size: 16px;">This is a reminder to pick up your refill for <strong>{{ current_regimen }}</strong> by {{ due_date }}.</p>
        {% endif %}

        <div style="background-color: #F9FAFB; border-radius: 8px; padding: 20px; margin: 25px 0; border: 1px solid #E5E7EB;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                    <td style="padding-bottom: 10px; color: #6B7280; font-size: 14px;">Medication</td>
                    <td style="padding-bottom: 10px; text-align: right; font-weight: 600; color: #111827;">{{ current_regimen }}</td>
                </tr>
                <tr>
                    <td style="color: #6B7280; font-size: 14px;">Status</td>
                    <td style="text-align: right; color: #D97706; font-weight: 600;">{{ urgency_text }}</td>
                </tr>
            </table>
        </div>

        <p style="font-size: 16px;">Staying on track with your medication is the most important thing you can do for your health.</p>

        <div style="text-align: center; margin-top: 30px;">
            <a href="tel:{{ clinic_phone }}" style="background-color: #059669; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block;">📞 Contact Pharmacy</a>
        </div>
        
        <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 30px 0;">
             
        <p style="text-align: center; color: #9CA3AF; font-size: 12px;">
            {{ app_name }} - {{ organization_name }}
        </p>
    </div>
</div>
        """,
        "variables": ["patient_name", "urgency_text", "current_regimen", "last_refill_date", "clinic_phone", "app_name", "organization_name", "urgency", "due_date"]
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
