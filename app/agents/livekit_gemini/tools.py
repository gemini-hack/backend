from datetime import datetime, timedelta
from uuid import UUID

from livekit.agents import function_tool
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from app.db.database import async_session_factory
from app.models import Patient, User, Appointment, Alert, AgentAction
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
    # Validate input
    valid, error = validate_input(patient_name, max_length=100, field_name="patient name")
    if not valid:
        audit_log("get_patient_info", {"patient_name": patient_name}, error or "Validation failed", success=False)
        return error or "Invalid input."
    
    # Sanitize input
    patient_name = sanitize_query_input(patient_name)
    logger.info(f"[TOOL CALLED] get_patient_info with patient_name='{patient_name}'")
    
    # Check cache first
    cache = get_session_cache()
    if cache:
        patient = cache.get_patient_by_name(patient_name)
        if patient:
            logger.info(f"[CACHE HIT] Found patient in cache")
            return f"""Patient: {patient['first_name']} {patient['last_name']}
ID: {patient['patient_uid']}
Status: {patient['status']}
Primary Condition: {patient['primary_condition']}
Phone: {patient['phone'] or 'Not on file'}
Last Updated: {patient['updated_at'] or 'Unknown'}"""
    
    # Fall back to database
    try:
        async with async_session_factory() as session:
            search_term = f"%{patient_name}%"
            query = select(Patient).where(
                or_(
                    Patient.first_name.ilike(search_term),
                    Patient.last_name.ilike(search_term),
                    func.concat(Patient.first_name, ' ', Patient.last_name).ilike(search_term),
                )
            )
            
            result = await session.execute(query)
            patient = result.scalar_one_or_none()
        
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
        patient_id: The patient's UID (e.g., 'PAT-001')
    
    Returns:
        Patient details
    """
    # Validate input
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
            logger.info(f"[CACHE HIT] Found patient by ID in cache")
            return f"""Patient: {patient['first_name']} {patient['last_name']}
ID: {patient['patient_uid']}
Status: {patient['status']}
Primary Condition: {patient['primary_condition']}"""
    
    # Fall back to database
    try:
        async with async_session_factory() as session:
            query = select(Patient).where(
                Patient.patient_uid.ilike(f"%{patient_id}%")
            )
            
            result = await session.execute(query)
            patient = result.scalar_one_or_none()
            
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
    async with async_session_factory() as session:
        # Get patients with active alerts
        query = select(Patient).join(Alert).where(
            and_(
                Alert.status == "pending",
                Patient.status == "active"
            )
        ).limit(limit)
        
        result = await session.execute(query)
        patients = result.scalars().all()
        
        if not patients:
            return "No high priority patients at this time."
        
        lines = ["High Priority Patients:"]
        for p in patients:
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
        lines = ["Today's Appointments:"]
        for apt in cache.today_appointments:
            time_str = datetime.fromisoformat(apt['scheduled_time']).strftime("%I:%M %p")
            lines.append(f"- {time_str}: {apt['patient_name']} ({apt['type']})")
        return "\n".join(lines)
    
    # Fall back to database
    async with async_session_factory() as session:
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        
        query = select(Appointment).where(
            and_(
                Appointment.scheduled_time >= today,
                Appointment.scheduled_time < tomorrow,
            )
        ).options(selectinload(Appointment.patient))
        
        result = await session.execute(query)
        appointments = result.scalars().all()
        
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
    # Validate input
    valid, error = validate_input(patient_name, max_length=100, field_name="patient name")
    if not valid:
        audit_log("get_patient_appointments", {"patient_name": patient_name}, error or "Validation failed", success=False)
        return error or "Invalid input."
    
    patient_name = sanitize_query_input(patient_name)
    
    async with async_session_factory() as session:
        search_term = f"%{patient_name}%"
        
        # First find the patient
        patient_query = select(Patient).where(
            or_(
                Patient.first_name.ilike(search_term),
                Patient.last_name.ilike(search_term),
            )
        )
        result = await session.execute(patient_query)
        patient = result.scalar_one_or_none()
        
        if not patient:
            return f"No patient found with name '{patient_name}'"
        
        # Get their appointments
        apt_query = select(Appointment).where(
            and_(
                Appointment.patient_id == patient.id,
                Appointment.scheduled_time >= datetime.now(),
            )
        ).order_by(Appointment.scheduled_time)
        
        result = await session.execute(apt_query)
        appointments = result.scalars().all()
        
        if not appointments:
            return f"No upcoming appointments for {patient.first_name} {patient.last_name}"
        
        lines = [f"Appointments for {patient.first_name} {patient.last_name}:"]
        for apt in appointments:
            date_str = apt.scheduled_time.strftime("%B %d at %I:%M %p")
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
    async with async_session_factory() as session:
        query = select(Alert).where(
            Alert.status == "pending"
        ).order_by(Alert.severity.desc()).limit(limit).options(
            selectinload(Alert.patient)
        )
        
        result = await session.execute(query)
        alerts = result.scalars().all()
        
        if not alerts:
            return "No active alerts at this time."
        
        lines = ["Active Alerts:"]
        for alert in alerts:
            patient = alert.patient
            lines.append(f"- [{alert.severity.upper()}] {patient.first_name} {patient.last_name}: {alert.title}")
        
        return "\n".join(lines)


# =============================================================================
# Caseload Tools
# =============================================================================

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
    async with async_session_factory() as session:
        patient_count = await session.execute(
            select(func.count(Patient.id)).where(Patient.status == "active")
        )
        active_patients = patient_count.scalar() or 0
        
        alert_count = await session.execute(
            select(func.count(Alert.id)).where(Alert.status == "pending")
        )
        active_alerts = alert_count.scalar() or 0
        
        action_count = await session.execute(
            select(func.count(AgentAction.id)).where(AgentAction.status == "pending")
        )
        pending_actions = action_count.scalar() or 0
        
        return f"""Caseload Summary:
- Active Patients: {active_patients}
- Active Alerts: {active_alerts}
- Pending Actions: {pending_actions}"""


# =============================================================================
# Collection of all tools
# =============================================================================

MIRA_TOOLS = [
    get_patient_info,
    get_patient_by_id,
    list_high_priority_patients,
    get_today_appointments,
    get_patient_appointments,
    get_active_alerts,
    get_my_caseload_summary,
]
