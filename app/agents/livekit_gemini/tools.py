from datetime import datetime, timedelta
from uuid import UUID

from livekit.agents import function_tool
from sqlalchemy import or_, func

from app.db.database import async_session_factory
from app.models import Patient, Appointment, Alert, AgentAction
from app.utils.logger import logger

from .security import validate_input, sanitize_query_input, audit_log
from .session_cache import get_session_cache


@function_tool
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
    
    # Fall back to database using QueryBuilder
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


@function_tool
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


@function_tool
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


@function_tool
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
            lines.append(f"- {time_str}: {apt['patient_name']} ({apt['type']})")
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
            lines.append(f"- {time_str}: {patient.first_name} {patient.last_name} ({apt.type})")
        
        return "\n".join(lines)


@function_tool
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
        audit_log("get_patient_appointments", {"patient_name": patient_name}, error or "Validation failed", success=False)
        return error or "Invalid input."
    
    patient_name = sanitize_query_input(patient_name)
    
    async with async_session_factory() as db:
        # First find the patient
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
        
        # Get their upcoming appointments
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
            lines.append(f"- {date_str}: {apt.type}")
        
        return "\n".join(lines)


@function_tool
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


@function_tool
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


MIRA_TOOLS = [
    get_patient_info,
    get_patient_by_id,
    list_high_priority_patients,
    get_today_appointments,
    get_patient_appointments,
    get_active_alerts,
    get_my_caseload_summary,
]
