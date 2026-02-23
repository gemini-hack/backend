import asyncio
import sys
import os

# Add parent directory to path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
        "subject": "📅 Appointment Reminder - {{ appointment_type }} on {{ appointment_date }}",
        "html_body": """
<div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; background-color: #f8fafc; padding: 20px;">
    <div style="background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 24px;">📅 Appointment Reminder</h1>
    </div>
    
    <div style="background: white; padding: 30px; border-radius: 0 0 12px 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        <p style="font-size: 16px; color: #374151;">Hello <strong>{{ patient_name }}</strong>,</p>
        
        <p style="font-size: 16px; color: #374151;">This is a friendly reminder about your upcoming appointment:</p>
        
        <div style="background: #f3f4f6; border-left: 4px solid #4F46E5; padding: 20px; margin: 20px 0; border-radius: 0 8px 8px 0;">
            <p style="margin: 0 0 10px 0; font-size: 14px; color: #6b7280;"><strong>📋 Type:</strong></p>
            <p style="margin: 0 0 15px 0; font-size: 18px; color: #1f2937; font-weight: 600;">{{ appointment_type }}</p>
            
            <p style="margin: 0 0 10px 0; font-size: 14px; color: #6b7280;"><strong>📆 Date & Time:</strong></p>
            <p style="margin: 0 0 15px 0; font-size: 18px; color: #1f2937; font-weight: 600;">{{ appointment_date }} at {{ appointment_time }}</p>
            
            <p style="margin: 0 0 10px 0; font-size: 14px; color: #6b7280;"><strong>👨‍⚕️ Provider:</strong></p>
            <p style="margin: 0; font-size: 18px; color: #1f2937; font-weight: 600;">{{ provider_name }}</p>
        </div>
        
        {% if notes %}
        <div style="background: #fef3c7; border: 1px solid #f59e0b; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <p style="margin: 0; font-size: 14px; color: #92400e;"><strong>📝 Notes:</strong> {{ notes }}</p>
        </div>
        {% endif %}
        
        <p style="font-size: 16px; color: #374151;">Please arrive 15 minutes early. If you need to reschedule, contact us as soon as possible.</p>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{ clinic_phone }}" style="background: #4F46E5; color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; display: inline-block;">📞 Contact Clinic</a>
        </div>
        
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 25px 0;">
        
        <p style="color: #9ca3af; font-size: 12px; text-align: center;">
            This reminder was sent by {{ app_name }} on behalf of {{ organization_name }}.<br>
            Your health is our priority. 💜
        </p>
    </div>
</div>
        """,
        "variables": ["patient_name", "appointment_type", "appointment_date", "appointment_time", "provider_name", "notes", "clinic_phone", "app_name", "organization_name"]
    },
    {
        "slug": "engagement_nudge",
        "subject": "💊 We miss you, {{ patient_name }}! Time for a check-in",
        "html_body": """
<div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; background-color: #f8fafc; padding: 20px;">
    <div style="background: linear-gradient(135deg, #10B981 0%, #059669 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 24px;">💚 Your Health Matters</h1>
    </div>
    
    <div style="background: white; padding: 30px; border-radius: 0 0 12px 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        <p style="font-size: 16px; color: #374151;">Hello <strong>{{ patient_name }}</strong>,</p>
        
        <p style="font-size: 16px; color: #374151;">We noticed it's been <strong>{{ days_since_last_reading }} days</strong> since your last health update. Your care team wants to make sure you're doing well!</p>
        
        <div style="background: #ecfdf5; border: 1px solid #10b981; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center;">
            <p style="margin: 0 0 10px 0; font-size: 18px; color: #065f46; font-weight: 600;">📱 Log your health reading today</p>
            <p style="margin: 0; color: #047857;">It only takes 2 minutes and helps your care team support you better.</p>
        </div>
        
        <p style="font-size: 16px; color: #374151;">If you're facing any challenges with your medication or have questions, please don't hesitate to reach out. We're here to help!</p>
        
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 25px 0;">
        
        <p style="color: #9ca3af; font-size: 12px; text-align: center;">
            Sent with care by {{ app_name }} 💜<br>
            {{ organization_name }}
        </p>
    </div>
</div>
        """,
        "variables": ["patient_name", "days_since_last_reading", "app_name", "organization_name"]
    },
    {
        "slug": "refill_reminder",
        "subject": "💊 Medication Refill Reminder - {{ patient_name }}",
        "html_body": """
<div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; background-color: #f8fafc; padding: 20px;">
    <div style="background: linear-gradient(135deg, #F59E0B 0%, #D97706 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 24px;">💊 Refill Reminder</h1>
    </div>
    
    <div style="background: white; padding: 30px; border-radius: 0 0 12px 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        <p style="font-size: 16px; color: #374151;">Hello <strong>{{ patient_name }}</strong>,</p>
        
        <p style="font-size: 16px; color: #374151;">Your medication refill is <strong>{{ urgency_text }}</strong>.</p>
        
        <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 20px; margin: 20px 0; border-radius: 0 8px 8px 0;">
            <p style="margin: 0 0 10px 0; font-size: 14px; color: #92400e;"><strong>Current Medication:</strong></p>
            <p style="margin: 0 0 15px 0; font-size: 18px; color: #78350f; font-weight: 600;">{{ current_regimen }}</p>
            
            <p style="margin: 0 0 10px 0; font-size: 14px; color: #92400e;"><strong>Last Refill:</strong></p>
            <p style="margin: 0; font-size: 16px; color: #78350f;">{{ last_refill_date }}</p>
        </div>
        
        <p style="font-size: 16px; color: #374151;">Please visit the clinic to collect your medication. Maintaining your treatment is crucial for your health.</p>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="tel:{{ clinic_phone }}" style="background: #F59E0B; color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; display: inline-block;">📞 Call to Schedule Pickup</a>
        </div>
        
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 25px 0;">
        
        <p style="color: #9ca3af; font-size: 12px; text-align: center;">
            {{ app_name }} - {{ organization_name }}<br>
            Your health journey, supported. 💜
        </p>
    </div>
</div>
        """,
        "variables": ["patient_name", "urgency_text", "current_regimen", "last_refill_date", "clinic_phone", "app_name", "organization_name"]
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
