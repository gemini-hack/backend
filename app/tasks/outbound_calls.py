import asyncio
import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.celery_app import celery_app
from app.db.database import get_celery_session
from app.models import Patient, CallSession, CallType, CallStatus, Alert
from app.models.agent import AlertSeverity
from app.models.patient import CommunicationPreference
from app.services.livekit_sip_service import LiveKitSIPService
from app.utils.logger import logger


async def _trigger_call_async(
    patient_id: str,
    call_type: str,
    action_id: str | None = None,
    triggered_by_id: str | None = None,
) -> str | None:
    """
    Inner async function to initiate an outbound call.
    
    Args:
        patient_id: UUID of the patient to call
        call_type: Type of call (from CallType enum values)
        action_id: Optional ID of the agent action that triggered this call
        triggered_by_id: Optional ID of the user who manually triggered
    
    Returns:
        Room name if successful, None if failed
    """
    async with get_celery_session() as db:
        try:
            # Fetch patient
            patient = await Patient.fetch_by_id(db, UUID(patient_id))
            
            if not patient:
                logger.error(f"Patient not found: {patient_id}")
                return None
            
            if not patient.phone:
                logger.error(f"Patient {patient_id} has no phone number")
                return None
            
            # Respect patient's preferred contact method
            if patient.preferred_contact_method != CommunicationPreference.CALL:
                logger.info(f"Patient {patient_id} prefers {patient.preferred_contact_method.value}, skipping call")
                return None
            
            # Check preferred contact time (format: "09:00-17:00" or "morning", "afternoon", "evening")
            if patient.preferred_contact_time:
                # Get current time in patient's local timezone
                try:
                    from zoneinfo import ZoneInfo
                    patient_tz = ZoneInfo(patient.timezone) if patient.timezone else ZoneInfo("UTC")
                    local_now = datetime.now(patient_tz)
                    current_hour = local_now.hour
                except Exception:
                    # Fallback to UTC if timezone is invalid
                    current_hour = datetime.now(timezone.utc).hour
                
                pref_time = patient.preferred_contact_time.lower()
                
                # Handle time range format (e.g., "09:00-17:00")
                if "-" in pref_time and ":" in pref_time:
                    try:
                        start_str, end_str = pref_time.split("-")
                        start_hour = int(start_str.split(":")[0])
                        end_hour = int(end_str.split(":")[0])
                        if not (start_hour <= current_hour < end_hour):
                            logger.info(f"Patient {patient_id} prefers contact between {pref_time}, local hour: {current_hour} ({patient.timezone}), skipping call")
                            return None
                    except ValueError:
                        pass  # Fall through if parsing fails
                
                # Handle named time periods
                elif pref_time == "morning" and not (6 <= current_hour < 12):
                    logger.info(f"Patient {patient_id} prefers morning contact, local hour: {current_hour} ({patient.timezone}), skipping call")
                    return None
                elif pref_time == "afternoon" and not (12 <= current_hour < 17):
                    logger.info(f"Patient {patient_id} prefers afternoon contact, local hour: {current_hour} ({patient.timezone}), skipping call")
                    return None
                elif pref_time == "evening" and not (17 <= current_hour < 21):
                    logger.info(f"Patient {patient_id} prefers evening contact, local hour: {current_hour} ({patient.timezone}), skipping call")
                    return None
            
            # Check if SIP is enabled
            sip_service = LiveKitSIPService()
            if not sip_service.is_sip_enabled():
                logger.warning("SIP calling is not enabled or configured")
                return None
            
            # Generate session ID
            session_id = str(uuid.uuid4())
            room_name = f"call-{session_id}"
            
            # Build metadata for the call
            metadata = {
                "call_type": call_type,
                "patient_id": str(patient.id),
                "patient_name": f"{patient.first_name} {patient.last_name}",
                "organization_id": str(patient.organization_id),
            }
            if action_id:
                metadata["action_id"] = action_id
            
            # Create CallSession record
            call_session = CallSession(
                room_name=room_name,
                patient_id=patient.id,
                organization_id=patient.organization_id,
                triggered_by_id=UUID(triggered_by_id) if triggered_by_id else None,
                call_type=CallType(call_type),
                status=CallStatus.INITIATED,
                from_number=sip_service.from_number,
                to_number=patient.phone,
                started_at=datetime.now(timezone.utc),
                metadata_=metadata,
            )
            await call_session.insert(db)
            
            # Initiate the SIP call
            try:
                await sip_service.initiate_outbound_call(
                    patient_phone=patient.phone,
                    session_id=session_id,
                    metadata=metadata,
                )
                
                # Update status to ringing
                call_session.status = CallStatus.RINGING
                await call_session.save(db)
                
                logger.info(f"Outbound call initiated: {room_name} to {patient.phone}")
                return room_name
                
            except Exception as e:
                # Mark as failed
                call_session.status = CallStatus.FAILED
                call_session.error_message = str(e)
                call_session.ended_at = datetime.now(timezone.utc)
                await call_session.save(db)
                
                logger.error(f"Failed to initiate call: {e}")
                return None
                
        except Exception as e:
            logger.exception(f"Error in _trigger_call_async: {e}")
            raise


@celery_app.task(
    name="app.tasks.outbound_calls.trigger_patient_call",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def trigger_patient_call(
    self,
    patient_id: str,
    call_type: str = "outbound_reminder",
    action_id: str | None = None,
    triggered_by_id: str | None = None,
):
    """
    Celery task to trigger an outbound call to a patient.
    
    This task is triggered by:
    - Morning rounds workflow (after alerts are generated)
    - Manual trigger via API endpoint
    
    Args:
        patient_id: UUID of the patient to call
        call_type: Type of call (outbound_reminder, outbound_followup, outbound_alert)
        action_id: Optional UUID of the agent action that triggered this
        triggered_by_id: Optional UUID of user who manually triggered
    """
    logger.info(f"Celery task: trigger_patient_call started for patient {patient_id}")
    
    try:
        result = asyncio.run(_trigger_call_async(
            patient_id=patient_id,
            call_type=call_type,
            action_id=action_id,
            triggered_by_id=triggered_by_id,
        ))
        
        if result:
            logger.info(f"Celery task: trigger_patient_call completed: {result}")
        else:
            logger.warning(f"Celery task: trigger_patient_call - call not initiated")
            
        return result
        
    except Exception as e:
        logger.error(f"Celery task: trigger_patient_call failed: {e}")
        # Retry on failure
        raise self.retry(exc=e)


@celery_app.task(name="app.tasks.outbound_calls.trigger_calls_for_alerts")
def trigger_calls_for_alerts(organization_id: str | None = None):
    """
    Trigger calls for patients with high-priority alerts.
    
    This is called after morning rounds to call patients
    who need immediate attention.
    
    Args:
        organization_id: Optional filter by organization
    """
    logger.info("Celery task: trigger_calls_for_alerts started")
    
    async def _trigger_alert_calls():
        
        async with get_celery_session() as db:
            # Get unacknowledged alerts (CRITICAL, URGENT, and engagement WARNINGs)
            query = select(Alert).filter(
                Alert.severity.in_([AlertSeverity.CRITICAL, AlertSeverity.URGENT, AlertSeverity.WARNING]),
                Alert.acknowledged_at.is_(None),
            )
            
            if organization_id:
                query = query.filter(Alert.organization_id == UUID(organization_id))
            
            result = await db.execute(query)
            alerts = result.scalars().all()
            
            # Get unique patients from alerts
            patient_ids = set(str(alert.patient_id) for alert in alerts)
            
            logger.info(f"Found {len(patient_ids)} patients with high-priority alerts")
            
            # Trigger calls for each patient
            for patient_id in patient_ids:
                trigger_patient_call.delay(
                    patient_id=patient_id,
                    call_type="outbound_alert",
                )
    
    try:
        asyncio.run(_trigger_alert_calls())
        logger.info("Celery task: trigger_calls_for_alerts completed")
    except Exception as e:
        logger.error(f"Celery task: trigger_calls_for_alerts failed: {e}")
        raise
