"""
Notification Manager - Unified channel routing for appointment reminders.
"""
import uuid
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
    Unified notification manager.
    
    Features:
    - Broadcasts to ALL configured channels (Email + SMS + Voice).
    - Updates status based on overall success.
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
        Execute reminder logic.
        
        Attempts ALL channels in the list (Broadcast strategy).
        """
        any_success = False
        
        for channel_str in reminder.channels:
            # Handle string vs Enum input
            channel = ReminderChannel(channel_str) if isinstance(channel_str, str) else channel_str
            channel_success = False
            
            try:
                if channel == ReminderChannel.EMAIL:
                    channel_success = await self._send_email(reminder, patient, appointment)
                elif channel == ReminderChannel.SMS:
                    channel_success = await self._send_sms(reminder, patient, appointment)
                elif channel == ReminderChannel.VOICE:
                    channel_success = await self._trigger_voice_call(reminder, patient, appointment)
                
                if channel_success:
                    any_success = True
                    
            except Exception as e:
                logger.error(f"Channel {channel.value} failed for reminder {reminder.id}: {e}")
                reminder.mark_channel_attempt(channel, "failed", error=str(e))
        
        # Update final status
        if any_success:
            reminder.status = ReminderStatus.SENT
            await reminder.save(self.db)
            return True
        else:
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
            reminder.mark_channel_attempt(ReminderChannel.EMAIL, "skipped", error="No email address")
            return False
        
        try:
            appt_time = appointment.scheduled_time.strftime('%B %d, %Y at %I:%M %p')
            
            await self.email_service.send_appointment_reminder(
                to_email=patient.email,
                patient_name=patient.first_name,
                appointment_time=appt_time,
                # --- FIX 1: Use the correct field name ---
                appointment_type=appointment.appointment_type, 
            )
            
            reminder.mark_channel_attempt(ReminderChannel.EMAIL, "success")
            logger.info(f"Email reminder sent to {patient.email}")
            return True
            
        except EmailDeliveryError as e:
            reminder.mark_channel_attempt(ReminderChannel.EMAIL, "failed", error=str(e))
            return False
        except Exception as e:
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
            return True
            
        except SMSRateLimitExceeded:
            reminder.mark_channel_attempt(ReminderChannel.SMS, "failed", error="Rate limit exceeded")
            return False
        except SMSDeliveryError as e:
            reminder.mark_channel_attempt(ReminderChannel.SMS, "failed", error=str(e))
            return False
        except Exception as e:
            reminder.mark_channel_attempt(ReminderChannel.SMS, "failed", error=str(e))
            return False

    async def _trigger_voice_call(
        self,
        reminder: AppointmentReminder,
        patient: Patient,
        appointment: Appointment,
    ) -> bool:
        """Trigger voice call reminder."""
        if not patient.phone:
            reminder.mark_channel_attempt(ReminderChannel.VOICE, "skipped", error="No phone number")
            return False
        
        try:
            # Ensure trigger_patient_call is imported
            trigger_patient_call.delay(
                patient_id=str(patient.id),
                call_type="outbound_reminder",
                action_id=str(reminder.id),
            )
            
            reminder.mark_channel_attempt(ReminderChannel.VOICE, "initiated")
            return True
            
        except Exception as e:
            reminder.mark_channel_attempt(ReminderChannel.VOICE, "failed", error=str(e))
            return False

    async def send_booking_confirmation(
        self,
        patient: Patient,
        appointment: Appointment,
        channels: list[ReminderChannel] = None,
    ) -> bool:
        """
        Send an immediate booking confirmation to the patient.
        """
        channels = channels or [ReminderChannel.EMAIL, ReminderChannel.SMS]
        any_success = False
        appt_time = appointment.scheduled_time.strftime('%B %d, %Y at %I:%M %p')
        
        for channel in channels:
            try:
                if channel == ReminderChannel.EMAIL and patient.email:
                    success = await self.email_service.send_booking_confirmation(
                        to_email=patient.email,
                        patient_name=patient.first_name,
                        appointment_time=appt_time,
                        appointment_type=appointment.appointment_type,
                    )
                    if success: any_success = True
                    
                elif channel == ReminderChannel.SMS and patient.phone:
                    success = await self.sms_service.send_booking_confirmation(
                        to_phone=patient.phone,
                        patient_name=patient.first_name,
                        appointment_time=appt_time,
                        appointment_type=appointment.appointment_type,
                        organization_id=str(appointment.organization_id),
                    )
                    if success: any_success = True
                    
            except Exception as e:
                logger.error(f"Booking confirmation {channel.value} failed: {e}")
                
        return any_success

    async def send_no_show_followup(
        self,
        patient: Patient,
        organization_id: uuid.UUID,
        channels: list[ReminderChannel] = None,
    ) -> bool:
        """
        Send no-show follow-up notification.
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