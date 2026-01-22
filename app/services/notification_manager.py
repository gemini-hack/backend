"""
Notification Manager - Unified channel routing for appointment reminders.

Provides cascade logic: email → SMS → voice with fallback on failure.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.reminder import AppointmentReminder, ReminderChannel, ReminderStatus
from app.services.email_service import EmailService
from app.services.sms_service import SMSService, SMSDeliveryError, SMSRateLimitExceeded
from app.tasks.outbound_calls import trigger_patient_call
from app.utils.logger import logger
from app.utils.exceptions import EmailDeliveryError


class NotificationManager:
    """
    Unified notification manager with cascade fallback logic.
    
    Features:
    - Routes to appropriate channel (email, SMS, voice)
    - Cascade fallback: if one channel fails, tries next in preference order
    - Logs all attempts to reminder.attempts JSONB
    - Respects patient preferences and rate limits
    
    Complexity Analysis:
    - Time: O(n) where n = number of channels to try
    - Space: O(1) - no significant data stored
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.email_service = EmailService(db)
        self.sms_service = SMSService()
    
    async def send_appointment_reminder(
        self,
        reminder: AppointmentReminder,
        patient: Patient,
        appointment: Appointment,
    ) -> bool:
        """
        Execute reminder with cascade logic.
        
        Tries each channel in the reminder.channels list until one succeeds.
        Updates reminder.attempts and reminder.status accordingly.
        
        Args:
            reminder: AppointmentReminder record
            patient: Patient to notify
            appointment: Appointment details
        
        Returns:
            True if any channel succeeded, False if all failed
        """
        success = False
        
        for channel_str in reminder.channels:
            channel = ReminderChannel(channel_str) if isinstance(channel_str, str) else channel_str
            
            try:
                if channel == ReminderChannel.EMAIL:
                    success = await self._send_email(reminder, patient, appointment)
                elif channel == ReminderChannel.SMS:
                    success = await self._send_sms(reminder, patient, appointment)
                elif channel == ReminderChannel.VOICE:
                    success = await self._trigger_voice_call(reminder, patient, appointment)
                
                if success:
                    reminder.status = ReminderStatus.SENT
                    await reminder.save(self.db)
                    return True
                    
            except Exception as e:
                logger.error(f"Channel {channel.value} failed for reminder {reminder.id}: {e}")
                reminder.mark_channel_attempt(channel, "failed", error=str(e))
                # Continue to next channel
        
        # All channels failed
        reminder.status = ReminderStatus.FAILED
        await reminder.save(self.db)
        return False
    
    async def _send_email(
        self,
        reminder: AppointmentReminder,
        patient: Patient,
        appointment: Appointment,
    ) -> bool:
        """Send reminder via email."""
        if not patient.email:
            logger.info(f"Patient {patient.id} has no email, skipping email reminder")
            reminder.mark_channel_attempt(ReminderChannel.EMAIL, "skipped", error="No email address")
            return False
        
        try:
            appt_time = appointment.scheduled_time.strftime('%B %d, %Y at %I:%M %p')
            
            await self.email_service.send_appointment_reminder(
                to_email=patient.email,
                patient_name=patient.first_name,
                appointment_time=appt_time,
                appointment_type=appointment.type,
            )
            
            reminder.mark_channel_attempt(ReminderChannel.EMAIL, "success")
            logger.info(f"Email reminder sent to {patient.email} for appointment {appointment.id}")
            return True
            
        except EmailDeliveryError as e:
            reminder.mark_channel_attempt(ReminderChannel.EMAIL, "failed", error=str(e))
            return False
    
    async def _send_sms(
        self,
        reminder: AppointmentReminder,
        patient: Patient,
        appointment: Appointment,
    ) -> bool:
        """Send reminder via SMS."""
        if not patient.phone:
            logger.info(f"Patient {patient.id} has no phone, skipping SMS reminder")
            reminder.mark_channel_attempt(ReminderChannel.SMS, "skipped", error="No phone number")
            return False
        
        try:
            message_sid = await self.sms_service.send_appointment_reminder(
                to_phone=patient.phone,
                patient_name=patient.first_name,
                appointment=appointment,
                organization_id=str(reminder.organization_id),
                idempotency_key=reminder.idempotency_key,
            )
            
            reminder.mark_channel_attempt(ReminderChannel.SMS, "success", message_id=message_sid)
            logger.info(f"SMS reminder sent to {patient.phone} for appointment {appointment.id}")
            return True
            
        except SMSRateLimitExceeded:
            reminder.mark_channel_attempt(ReminderChannel.SMS, "failed", error="Rate limit exceeded")
            return False
        except SMSDeliveryError as e:
            reminder.mark_channel_attempt(ReminderChannel.SMS, "failed", error=str(e))
            return False
    
    async def _trigger_voice_call(
        self,
        reminder: AppointmentReminder,
        patient: Patient,
        appointment: Appointment,
    ) -> bool:
        """Trigger voice call reminder via existing outbound call infrastructure."""
        if not patient.phone:
            logger.info(f"Patient {patient.id} has no phone, skipping voice reminder")
            reminder.mark_channel_attempt(ReminderChannel.VOICE, "skipped", error="No phone number")
            return False
        
        try:
            # Trigger async Celery task
            trigger_patient_call.delay(
                patient_id=str(patient.id),
                call_type="outbound_reminder",
                action_id=str(reminder.id),
            )
            
            reminder.mark_channel_attempt(ReminderChannel.VOICE, "initiated")
            logger.info(f"Voice call triggered for patient {patient.id}")
            return True
            
        except Exception as e:
            reminder.mark_channel_attempt(ReminderChannel.VOICE, "failed", error=str(e))
            return False
    
    async def send_no_show_followup(
        self,
        patient: Patient,
        organization_id: uuid.UUID,
        channels: list[ReminderChannel] = None,
    ) -> bool:
        """
        Send no-show follow-up notification.
        
        Uses cascade logic: email → SMS
        """
        channels = channels or [ReminderChannel.EMAIL, ReminderChannel.SMS]
        
        for channel in channels:
            try:
                if channel == ReminderChannel.EMAIL and patient.email:
                    await self.email_service.send_no_show_followup(
                        to_email=patient.email,
                        patient_name=patient.first_name,
                    )
                    logger.info(f"No-show email sent to {patient.email}")
                    return True
                    
                elif channel == ReminderChannel.SMS and patient.phone:
                    await self.sms_service.send_no_show_followup(
                        to_phone=patient.phone,
                        patient_name=patient.first_name,
                        organization_id=str(organization_id),
                    )
                    logger.info(f"No-show SMS sent to {patient.phone}")
                    return True
                    
            except Exception as e:
                logger.error(f"No-show {channel.value} failed for patient {patient.id}: {e}")
                # Continue to next channel
        
        return False
