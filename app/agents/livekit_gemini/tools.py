from datetime import datetime, timedelta, timezone

from livekit.agents import function_tool
from sqlalchemy import or_, func

from app.db.database import async_session_factory
from app.models import Patient, Appointment, Alert, AgentAction
from app.utils.logger import logger

from .security import validate_input, sanitize_query_input, audit_log
from .session_cache import get_session_cache
from .action_logger import log_call_action
from app.services.availability_service import AvailabilityService
from app.services.appointment_service import AppointmentService
from app.services.reminder_service import ReminderService
from app.services.livekit_sip_service import LiveKitSIPService
from app.models.appointment import AppointmentStatus, VisitMode
from app.schemas.appointment import AppointmentCreate


async def get_patient_info(patient_name: str) -> str:
    """
    Look up patient information by name.
    
    Args:
        patient_name: The patient's name (first name, last name, or full name)
    
    Returns:
        Patient details including conditions, status, and recent activity
    """
    valid, error = validate_input(patient_name, max_length=100, field_name="patient name")
    if not valid:
        audit_log("get_patient_info", {"patient_name": patient_name}, error or "Validation failed", success=False)
        return error or "Invalid input."
    
    patient_name = sanitize_query_input(patient_name)
    logger.info(f"[TOOL CALLED] get_patient_info with patient_name='{patient_name}'")
    
    # Check cache first
    cache = get_session_cache()
    if cache:
        patient = cache.get_patient_by_name(patient_name)
        if patient:
            logger.info("[CACHE HIT] Found patient in cache")
            return f"""Patient: {patient['first_name']} {patient['last_name']}
ID: {patient['patient_uid']}
Status: {patient['status']}
Primary Condition: {patient['primary_condition']}
Phone: {patient['phone'] or 'Not on file'}
Last Updated: {patient['updated_at'] or 'Unknown'}"""
    
    patient = None
    try:
        async with async_session_factory() as db:
            search_term = f"%{patient_name}%"
            patient = await (
                Patient.query(db)
                .filter(
                    or_(
                        Patient.first_name.ilike(search_term),
                        Patient.last_name.ilike(search_term),
                        func.concat(Patient.first_name, ' ', Patient.last_name).ilike(search_term),
                    )
                )
                .first()
            )
        
            if not patient:
                return f"No patient found with name '{patient_name}'"
            
            return f"""Patient: {patient.first_name} {patient.last_name}
ID: {patient.patient_uid}
Status: {patient.status}
Primary Condition: {patient.primary_condition}
Phone: {patient.phone or 'Not on file'}
Last Updated: {patient.updated_at.strftime('%Y-%m-%d') if patient.updated_at else 'Unknown'}"""
    except Exception as e:
        logger.exception(f"[TOOL ERROR] get_patient_info failed: {e}")
        return f"Error looking up patient: {str(e)}"
    finally:
        # Log the lookup action
        await log_call_action(
            action_type="lookup_patient",
            action_data={"query": patient_name},
            result="success" if patient else "not_found"
        )


async def get_patient_by_id(patient_id: str) -> str:
    """
    Look up patient information by their unique ID.
    
    Args:
        patient_id: The patient's UID (e.g., 'PT-001')
    
    Returns:
        Patient details
    """
    valid, error = validate_input(patient_id, max_length=50, field_name="patient ID")
    if not valid:
        audit_log("get_patient_by_id", {"patient_id": patient_id}, error or "Validation failed", success=False)
        return error or "Invalid input."
    
    patient_id = sanitize_query_input(patient_id)
    
    # Check cache first
    cache = get_session_cache()
    if cache:
        patient = cache.get_patient_by_id(patient_id)
        if patient:
            logger.info("[CACHE HIT] Found patient by ID in cache")
            return f"""Patient: {patient['first_name']} {patient['last_name']}
ID: {patient['patient_uid']}
Status: {patient['status']}
Primary Condition: {patient['primary_condition']}"""
    
    # Fall back to database using QueryBuilder
    try:
        async with async_session_factory() as db:
            patient = await (
                Patient.query(db)
                .filter(Patient.patient_uid.ilike(f"%{patient_id}%"))
                .first()
            )
            
            if not patient:
                return f"No patient found with ID '{patient_id}'"
            
            return f"""Patient: {patient.first_name} {patient.last_name}
ID: {patient.patient_uid}
Status: {patient.status}
Primary Condition: {patient.primary_condition}"""
    except Exception as e:
        logger.exception(f"[TOOL ERROR] get_patient_by_id failed: {e}")
        audit_log("get_patient_by_id", {"patient_id": patient_id}, str(e), success=False)
        return f"Error looking up patient: {str(e)}"


async def list_high_priority_patients(limit: int = 5) -> str:
    """
    Get a list of high priority patients that need attention.
    
    Args:
        limit: Maximum number of patients to return (default: 5)
    
    Returns:
        List of patients requiring urgent attention
    """
    # Check cache - derive from active alerts
    cache = get_session_cache()
    if cache and cache.active_alerts:
        logger.info("[CACHE HIT] Deriving high priority patients from cached alerts")
        seen_uids = set()
        lines = ["High Priority Patients:"]
        for alert in cache.active_alerts[:limit]:
            uid = alert.get('patient_uid')
            if uid and uid not in seen_uids:
                seen_uids.add(uid)
                lines.append(f"- {alert['patient_name']} ({uid})")
        if len(lines) == 1:
            return "No high priority patients at this time."
        return "\n".join(lines)
    
    # Fall back to database using QueryBuilder
    async with async_session_factory() as db:
        # Get patients with pending alerts
        patients = await (
            Patient.query(db)
            .filter(Patient.status == "active")
            .with_relations("alerts")
            .limit(limit)
            .all()
        )
        
        # Filter to those with pending alerts
        high_priority = [p for p in patients if any(a.status == "pending" for a in p.alerts)]
        
        if not high_priority:
            return "No high priority patients at this time."
        
        lines = ["High Priority Patients:"]
        for p in high_priority[:limit]:
            lines.append(f"- {p.first_name} {p.last_name} ({p.patient_uid})")
        
        return "\n".join(lines)


async def get_today_appointments() -> str:
    """
    Get all appointments scheduled for today.
    
    Returns:
        List of today's appointments with patient names and times
    """
    # Check cache first
    cache = get_session_cache()
    if cache and cache.today_appointments:
        logger.info(f"[CACHE HIT] Returning {len(cache.today_appointments)} appointments from cache")
        if not cache.today_appointments:
            return "No appointments scheduled for today."
        lines = ["Today's Appointments:"]
        for apt in cache.today_appointments:
            time_str = datetime.fromisoformat(apt['scheduled_time']).strftime("%I:%M %p")
            lines.append(f"- {time_str}: {apt['patient_name']} ({apt['appointment_type']})")
        return "\n".join(lines)
    
    # Fall back to database using QueryBuilder
    async with async_session_factory() as db:
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        
        appointments = await (
            Appointment.query(db)
            .filter(
                Appointment.scheduled_time >= today,
                Appointment.scheduled_time < tomorrow,
            )
            .with_relations("patient")
            .all()
        )
        
        if not appointments:
            return "No appointments scheduled for today."
        
        lines = ["Today's Appointments:"]
        for apt in appointments:
            time_str = apt.scheduled_time.strftime("%I:%M %p")
            patient = apt.patient
            lines.append(f"- {time_str}: {patient.first_name} {patient.last_name} ({apt.appointment_type})")
        
        return "\n".join(lines)


async def get_patient_appointments(patient_name: str) -> str:
    """
    Get upcoming appointments for a specific patient.
    
    Args:
        patient_name: The patient's name
    
    Returns:
        List of upcoming appointments for the patient
    """
    valid, error = validate_input(patient_name, max_length=100, field_name="patient name")
    if not valid:
        return error
    
    patient_name = sanitize_query_input(patient_name)
    
    async with async_session_factory() as db:
        # First find the patient using QueryBuilder
        search_term = f"%{patient_name}%"
        patient = await (
            Patient.query(db)
            .filter(
                or_(
                    Patient.first_name.ilike(search_term),
                    Patient.last_name.ilike(search_term),
                    func.concat(Patient.first_name, ' ', Patient.last_name).ilike(search_term),
                )
            )
            .first()
        )
        
        if not patient:
            return f"No patient found with name '{patient_name}'"
        
        # Get their upcoming appointments using QueryBuilder
        now = datetime.now()
        appointments = await (
            Appointment.query(db)
            .filter(
                Appointment.patient_id == patient.id,
                Appointment.scheduled_time >= now,
            )
            .order_by(Appointment.scheduled_time)
            .limit(10)
            .all()
        )
        
        if not appointments:
            return f"No upcoming appointments for {patient.first_name} {patient.last_name}"
        
        lines = [f"Upcoming Appointments for {patient.first_name} {patient.last_name}:"]
        for apt in appointments:
            date_str = apt.scheduled_time.strftime("%b %d at %I:%M %p")
            lines.append(f"- {date_str}: {apt.appointment_type}")
        
        return "\n".join(lines)


async def get_active_alerts(limit: int = 5) -> str:
    """
    Get active alerts that need attention.
    
    Args:
        limit: Maximum number of alerts to return (default: 5)
    
    Returns:
        List of active alerts with patient info and severity
    """
    # Check cache first
    cache = get_session_cache()
    if cache and cache.active_alerts:
        logger.info(f"[CACHE HIT] Returning {len(cache.active_alerts)} alerts from cache")
        alerts = cache.active_alerts[:limit]
        if not alerts:
            return "No active alerts at this time."
        lines = ["Active Alerts:"]
        for alert in alerts:
            lines.append(f"- [{alert['severity'].upper()}] {alert['patient_name']}: {alert['title']}")
        return "\n".join(lines)
    
    # Fall back to database
    async with async_session_factory() as db:
        alerts = await (
            Alert.query(db)
            .filter(Alert.status == "pending")
            .with_relations("patient")
            .order_by(Alert.severity, desc=True)
            .limit(limit)
            .all()
        )
        
        if not alerts:
            return "No active alerts at this time."
        
        lines = ["Active Alerts:"]
        for alert in alerts:
            patient = alert.patient
            lines.append(f"- [{alert.severity.upper()}] {patient.first_name} {patient.last_name}: {alert.title}")
        
        return "\n".join(lines)


async def get_my_caseload_summary() -> str:
    """
    Get a summary of the current user's caseload.
    
    Returns:
        Summary of active patients and pending tasks
    """
    # Check cache first
    cache = get_session_cache()
    if cache and cache.caseload_summary:
        logger.info("[CACHE HIT] Returning caseload summary from cache")
        s = cache.caseload_summary
        return f"""Caseload Summary:
- Active Patients: {s['active_patients']}
- Active Alerts: {s['active_alerts']}
- Pending Actions: {s['pending_actions']}"""
    
    # Fall back to database
    async with async_session_factory() as db:
        active_patients = await Patient.query(db).filter(Patient.status == "active").count()
        active_alerts = await Alert.query(db).filter(Alert.status == "pending").count()
        pending_actions = await AgentAction.query(db).filter(AgentAction.status == "pending").count()
        
        return f"""Caseload Summary:
- Active Patients: {active_patients}
- Active Alerts: {active_alerts}
- Pending Actions: {pending_actions}"""



async def check_availability_for_rescheduling(patient_id: str) -> str:
    """
    Check if a patient has a missed appointment and find available slots for rescheduling.
    
    Args:
        patient_id: The patient's UID (e.g., 'PT-001')
        
    Returns:
        String description of missed appointment and list of available slots.
    """
    valid, error = validate_input(patient_id, max_length=50, field_name="patient ID")
    if not valid:
        return error or "Invalid input."

    patient_id = sanitize_query_input(patient_id)
    
    async with async_session_factory() as db:
        # 1. Find patient
        patient = await (
            Patient.query(db)
            .filter(Patient.patient_uid == patient_id)
            .first()
        )
        if not patient:
            return f"Patient not found: {patient_id}"
            
        # 2. Find most recent NO_SHOW or CANCELLED appointment
        # We need to sort by scheduled_time DESC
        last_appointment = await (
            Appointment.query(db)
            .filter(
                Appointment.patient_id == patient.id,
                or_(
                    Appointment.status == AppointmentStatus.NO_SHOW,
                    Appointment.status == AppointmentStatus.CANCELLED
                )
            )
            .order_by(Appointment.scheduled_time, desc=True)
            .first()
        )
        
        if not last_appointment:
            return "No recently missed or cancelled appointments found eligible for rescheduling."
            
        # 3. Get availability
        # Use provider from the missed appointment if possible, or fallback
        # Range: Next 7 days
        start_date = datetime.now(timezone.utc) + timedelta(minutes=30) # buffer
        end_date = start_date + timedelta(days=7)
        
        slots = await AvailabilityService.get_available_slots(
            db=db,
            org_id=patient.organization_id,
            start_date=start_date,
            end_date=end_date,
            provider_id=last_appointment.provider_id
        )
        
        if not slots:
            return "No available slots found for the next 7 days. Please contact the clinic."
            
        # Format slots (take top 5)
        slot_strings = [s.strftime("%A, %b %d at %I:%M %p") for s in slots[:5]]
        slots_text = "\n".join([f"- {s}" for s in slot_strings])
        
        missed_time = last_appointment.scheduled_time.strftime("%b %d")
        
        return f"""Found missed appointment from {missed_time}.
Here are some available times to reschedule:
{slots_text}

To reschedule, please reply with the preferred time.
(System: Call confirm_reschedule with the exact ISO timestamp of the chosen slot)
"""


async def confirm_reschedule(patient_id: str, chosen_slot_iso: str) -> str:
    """
    Confirm and execute the rescheduling of an appointment.
    
    Args:
        patient_id: The patient's UID
        chosen_slot_iso: The ISO formatted string of the chosen time slot
        
    Returns:
        Confirmation message
    """
    valid, error = validate_input(patient_id, max_length=50, field_name="patient ID")
    if not valid:
        return error or "Invalid input."
        
    try:
        new_time = datetime.fromisoformat(chosen_slot_iso.replace("Z", "+00:00"))
    except ValueError:
        return "Invalid date format. Please provide ISO 8601 format."
        
    async with async_session_factory() as db:
        # 1. Find patient and their missed appointment again (for safety)
        patient = await (
            Patient.query(db)
            .filter(Patient.patient_uid == patient_id)
            .first()
        )
        if not patient:
            return "Patient not found."
            
        last_appointment = await (
            Appointment.query(db)
            .filter(
                Appointment.patient_id == patient.id,
                or_(
                    Appointment.status == AppointmentStatus.NO_SHOW,
                    Appointment.status == AppointmentStatus.CANCELLED
                )
            )
            .order_by(Appointment.scheduled_time, desc=True)
            .first()
        )
        
        if not last_appointment:
            return "Could not find the appointment to reschedule."
            
        try:
            service = AppointmentService(db)
            updated_appt = await service.reschedule_appointment(
                appointment_id=last_appointment.id,
                new_scheduled_time=new_time,
            )
            
            # Log the reschedule action
            await log_call_action(
                action_type="reschedule_appointment",
                action_data={
                    "patient_id": patient_id,
                    "patient_name": f"{patient.first_name} {patient.last_name}",
                    "old_time": last_appointment.scheduled_time.isoformat(),
                    "new_time": new_time.isoformat(),
                    "appointment_id": str(last_appointment.id)
                },
                result="success"
            )
            
            return f"Successfully rescheduled appointment to {new_time.strftime('%A, %b %d at %I:%M %p')}."
            
        except Exception as e:
            logger.error(f"Reschedule failed: {e}")
            
            # Log the failed action
            await log_call_action(
                action_type="reschedule_appointment",
                action_data={
                    "patient_id": patient_id,
                    "new_time": new_time.isoformat(),
                    "error": str(e)
                },
                result="failed"
            )
            
            return f"Failed to reschedule: {str(e)}"


async def create_appointment(patient_id: str, provider_id: str, scheduled_time: str, appointment_type: str, duration_minutes: int, notes: str = None) -> str:
    """
    Schedule a new appointment for a patient.
    
    Args:
        patient_id: The patient's UID
        provider_id: The provider's user ID
        scheduled_time: ISO-formatted start time for the appointment
        appointment_type: Type of the appointment (e.g. Follow-up, Consultation)
        duration_minutes: Duration of the appointment in minutes
        notes: (Optional) Any specific notes for the appointment
        
    Returns:
        Confirmation message
    """
    valid, error = validate_input(patient_id, max_length=50, field_name="patient ID")
    if not valid:
        return error or "Invalid input."
        
    try:
        new_time = datetime.fromisoformat(scheduled_time.replace("Z", "+00:00"))
    except ValueError:
        return "Invalid date format. Please provide ISO 8601 format."
        
    async with async_session_factory() as db:
        patient = await Patient.query(db).filter(Patient.patient_uid == patient_id).first()
        if not patient:
            return "Patient not found."
            
        try:
            from uuid import UUID
            provider_uuid = UUID(provider_id) if provider_id else None
            
            data = AppointmentCreate(
                patient_id=patient.id,
                provider_id=provider_uuid,
                scheduled_time=new_time,
                appointment_type=appointment_type,
                duration_minutes=duration_minutes,
                visit_mode=VisitMode.IN_PERSON,
                notes=notes
            )
            
            service = AppointmentService(db)
            appointment = await service.create_appointment(
                data=data,
                organization_id=patient.organization_id,
                created_by_agent=True
            )
            
            await log_call_action(
                action_type="create_appointment",
                action_data={
                    "patient_id": patient_id,
                    "scheduled_time": new_time.isoformat(),
                    "appointment_type": appointment_type,
                    "provider_id": provider_id
                },
                result="success"
            )
            
            return f"Successfully booked appointment for {new_time.strftime('%b %d at %I:%M %p')}. Confirmation sent."
            
        except Exception as e:
            logger.error(f"Failed to create appointment: {e}")
            return f"Failed to book appointment: {str(e)}"

async def send_reminder(appointment_id: str) -> str:
    """
    Send an immediate appointment reminder to a patient.
    
    Args:
        appointment_id: The internal UUID of the appointment to send the reminder for
        
    Returns:
        Confirmation message
    """
    try:
        from uuid import UUID
        appt_uuid = UUID(appointment_id)
        
        async with async_session_factory() as db:
            service = ReminderService(db)
            await service.schedule_reminders_for_appointment(appt_uuid)
            
            await log_call_action(
                action_type="send_reminder",
                action_data={"appointment_id": appointment_id},
                result="success"
            )
            return "Appointment reminder has been dispatched successfully."
    except Exception as e:
        logger.error(f"Failed to send reminder for {appointment_id}: {e}")
        return f"Failed to send appointment reminder: {str(e)}"

async def initiate_outbound_call(patient_phone: str, session_id: str) -> str:
    """
    Dial out to a patient via Twilio SIP trunk to initiate a phone call.
    Requires SIP calling capabilities to be active in LiveKit and Twilio.
    
    Args:
        patient_phone: The patient's phone number in E.164 format (e.g. +1234567890)
        session_id: The session ID
        
    Returns:
        Confirmation message about the dialing state
    """
    valid, error = validate_input(patient_phone, max_length=20, field_name="patient phone")
    if not valid:
        return error or "Invalid input."
        
    try:
        service = LiveKitSIPService()
        if not service.is_sip_enabled():
            return "Twilio SIP calling is not configured on this server."
        
        # Dial out 
        metadata = {"agent_initiated": True, "type": "outbound_dial"}
        room_name = await service.initiate_outbound_call(
            patient_phone=patient_phone,
            session_id=session_id,
            metadata=metadata
        )
        
        await log_call_action(
            action_type="initiate_outbound_call",
            action_data={"phone": patient_phone, "room_name": room_name},
            result="success"
        )
        return f"Calling {patient_phone} now. Room established: {room_name}"
        
    except Exception as e:
        logger.error(f"Failed to initiate call to {patient_phone}: {e}")
        return f"Failed to dial patient: {str(e)}"


MIRA_TOOLS = [
    function_tool(get_patient_info),
    function_tool(get_patient_by_id),
    function_tool(list_high_priority_patients),
    function_tool(get_today_appointments),
    function_tool(get_patient_appointments),
    function_tool(get_active_alerts),
    function_tool(get_my_caseload_summary),
    function_tool(check_availability_for_rescheduling),
    function_tool(confirm_reschedule),
    function_tool(create_appointment),
    function_tool(send_reminder),
    function_tool(initiate_outbound_call),
]
