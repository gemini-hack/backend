from uuid import UUID

from fastmcp import FastMCP
from fastmcp.dependencies import Depends
from fastmcp.server.auth import JWTVerifier
from fastmcp.server.dependencies import get_access_token

from app.core.config import settings
from app.models.user import UserRole
from app.utils.logger import logger

from .session_cache import SessionCache, preload_session_data, set_session_cache
from .voice_context import VoiceAgentUserContext, set_current_voice_context

# Import the core tool implementations
from .tools import (
    get_patient_info,
    get_patient_by_id,
    list_high_priority_patients,
    get_today_appointments,
    get_patient_appointments,
    get_active_alerts,
    get_my_caseload_summary,
    check_availability_for_rescheduling,
    confirm_reschedule,
    create_appointment,
    send_reminder,
    initiate_outbound_call,
)

mcp = FastMCP(
    "MIRA Voice Tools",
    auth=JWTVerifier(
        public_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        issuer="mira-voice-agent",
        audience="mira-mcp-server",
    ),
)

# Session-level cache (keyed by org:user, reused across tool calls)
_session_caches: dict[str, SessionCache] = {}


# Auth dependency
async def _resolve_voice_context() -> VoiceAgentUserContext:
    """Decode the verified JWT claims, hydrate ContextVars, and preload the
    organisation-scoped session cache so downstream tool functions work
    transparently."""
    token = get_access_token()
    if token is None:
        raise RuntimeError("Unauthenticated MCP request")

    claims = token.claims
    ctx = VoiceAgentUserContext(
        user_id=UUID(claims["sub"]),
        organization_id=UUID(claims["org_id"]),
        role=UserRole(claims["role"]),
        full_name=claims.get("full_name", "Voice User"),
    )
    set_current_voice_context(ctx)

    # Preload / reuse session cache
    cache_key = f"{claims['org_id']}:{claims['sub']}"
    cache = _session_caches.get(cache_key)
    if cache is None or cache.is_stale():
        try:
            cache = await preload_session_data(ctx.organization_id, ctx.user_id)
            _session_caches[cache_key] = cache
        except Exception as exc:
            logger.warning("MCP session cache preload failed: %s", exc)

    if cache:
        set_session_cache(cache)

    return ctx


_auth = Depends(_resolve_voice_context)


@mcp.tool
async def mcp_get_patient_info(patient_name: str, _: VoiceAgentUserContext = _auth) -> str:
    """
    Look up patient information by name.

    Args:
        patient_name: The patient's name (first name, last name, or full name)

    Returns:
        Patient details including conditions, status, and recent activity
    """
    return await get_patient_info(patient_name)


@mcp.tool
async def mcp_get_patient_by_id(patient_id: str, _: VoiceAgentUserContext = _auth) -> str:
    """
    Look up patient information by their unique ID.

    Args:
        patient_id: The patient's UID (e.g., 'PT-001')

    Returns:
        Patient details
    """
    return await get_patient_by_id(patient_id)


@mcp.tool
async def mcp_list_high_priority_patients(limit: int = 5, _: VoiceAgentUserContext = _auth) -> str:
    """
    Get a list of high priority patients that need attention.

    Args:
        limit: Maximum number of patients to return (default: 5)

    Returns:
        List of patients requiring urgent attention
    """
    return await list_high_priority_patients(limit)


@mcp.tool
async def mcp_get_today_appointments(_: VoiceAgentUserContext = _auth) -> str:
    """
    Get all appointments scheduled for today.

    Returns:
        List of today's appointments with patient names and times
    """
    return await get_today_appointments()


@mcp.tool
async def mcp_get_patient_appointments(patient_name: str, _: VoiceAgentUserContext = _auth) -> str:
    """
    Get upcoming appointments for a specific patient.

    Args:
        patient_name: The patient's name

    Returns:
        List of upcoming appointments for the patient
    """
    return await get_patient_appointments(patient_name)


@mcp.tool
async def mcp_get_active_alerts(limit: int = 5, _: VoiceAgentUserContext = _auth) -> str:
    """
    Get active alerts that need attention.

    Args:
        limit: Maximum number of alerts to return (default: 5)

    Returns:
        List of active alerts with patient info and severity
    """
    return await get_active_alerts(limit)



@mcp.tool
async def mcp_get_my_caseload_summary(_: VoiceAgentUserContext = _auth) -> str:
    """
    Get a summary of the current user's caseload.

    Returns:
        Summary of active patients and pending tasks
    """
    return await get_my_caseload_summary()



@mcp.tool
async def mcp_check_availability_for_rescheduling(patient_id: str, _: VoiceAgentUserContext = _auth) -> str:
    """
    Check if a patient has a missed appointment and find available slots for rescheduling.

    Args:
        patient_id: The patient's UID (e.g., 'PT-001')

    Returns:
        String description of missed appointment and list of available slots.
    """
    return await check_availability_for_rescheduling(patient_id)


@mcp.tool
async def mcp_confirm_reschedule(patient_id: str, chosen_slot_iso: str, _: VoiceAgentUserContext = _auth) -> str:
    """
    Confirm and execute the rescheduling of an appointment.

    Args:
        patient_id: The patient's UID
        chosen_slot_iso: The ISO formatted string of the chosen time slot

    Returns:
        Confirmation message
    """
    return await confirm_reschedule(patient_id, chosen_slot_iso)


@mcp.tool
async def mcp_create_appointment(patient_id: str, provider_id: str, scheduled_time: str, appointment_type: str, duration_minutes: int, notes: str = None, _: VoiceAgentUserContext = _auth) -> str:
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
    return await create_appointment(patient_id, provider_id, scheduled_time, appointment_type, duration_minutes, notes)


@mcp.tool
async def mcp_send_reminder(appointment_id: str, _: VoiceAgentUserContext = _auth) -> str:
    """
    Send an immediate appointment reminder to a patient.
    
    Args:
        appointment_id: The internal UUID of the appointment to send the reminder for
        
    Returns:
        Confirmation message
    """
    return await send_reminder(appointment_id)


@mcp.tool
async def mcp_initiate_outbound_call(patient_phone: str, session_id: str, _: VoiceAgentUserContext = _auth) -> str:
    """
    Dial out to a patient via Twilio SIP trunk to initiate a phone call.
    Requires SIP calling capabilities to be active in LiveKit and Twilio.
    
    Args:
        patient_phone: The patient's phone number in E.164 format (e.g. +1234567890)
        session_id: The session ID
        
    Returns:
        Confirmation message about the dialing state
    """
    return await initiate_outbound_call(patient_phone, session_id)


def run_mcp_server():
    """Start the MIRA MCP server on the configured port."""
    port = settings.MCP_SERVER_PORT
    host = settings.MCP_SERVER_HOST if hasattr(settings, "MCP_SERVER_HOST") else "0.0.0.0"
    logger.info(f"Starting MIRA MCP Server on http://{host}:{port}/sse")
    mcp.run(transport="sse", host=host, port=port)


if __name__ == "__main__":
    run_mcp_server()
