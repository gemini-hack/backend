import hashlib
import hmac
import base64
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Form
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from app.core.config import settings
from app.db.database import async_session_factory
from app.models import Patient, CallSession, CallStatus
from app.utils.logger import logger

router = APIRouter(prefix="/webhooks/twilio", tags=["Twilio Webhooks"])


def verify_twilio_signature(request: Request, body: bytes) -> bool:
    """
    Verify that the request came from Twilio using X-Twilio-Signature.
    
    For production, this should validate the signature.
    For development, we skip if auth token is not set.
    """
    if not settings.TWILIO_AUTH_TOKEN:
        logger.warning("Twilio auth token not set, skipping signature verification")
        return True
    
    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        return False
    
    # Build the full URL Twilio signed
    url = str(request.url)
    
    # Sort POST params and append to URL
    # For form data, we need to parse it
    try:
        from urllib.parse import parse_qs
        params = parse_qs(body.decode("utf-8"))
        sorted_params = "".join(
            f"{k}{v[0]}" for k, v in sorted(params.items())
        )
        data_to_sign = url + sorted_params
    except Exception:
        data_to_sign = url
    
    # Compute expected signature
    expected = base64.b64encode(
        hmac.new(
            settings.TWILIO_AUTH_TOKEN.encode("utf-8"),
            data_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("utf-8")
    
    return hmac.compare_digest(signature, expected)


@router.post("/voice", response_class=PlainTextResponse)
async def handle_inbound_voice(
    request: Request,
    From: str = Form(...),
    To: str = Form(...),
    CallSid: str = Form(...),
    CallStatus: str = Form(None),
    Direction: str = Form(None),
):
    """
    Handle inbound voice calls from Twilio.
    
    This endpoint returns TwiML to route the call to LiveKit SIP.
    When a patient calls the Twilio number, this routes them to the MIRA agent.
    """
    logger.info(f"Inbound call: {From} -> {To}, CallSid: {CallSid}, Direction: {Direction}")
    
    # Normalize phone number (remove any formatting)
    caller_phone = From.replace(" ", "").replace("-", "")
    
    # Look up patient by phone number
    patient = None
    patient_name = "Unknown Caller"
    organization_id = None
    
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(Patient).filter(Patient.phone == caller_phone)
            )
            patient = result.scalar_one_or_none()
            
            if patient:
                patient_name = f"{patient.first_name} {patient.last_name}"
                organization_id = str(patient.organization_id)
                logger.info(f"Identified caller as patient: {patient.id} ({patient_name})")
            else:
                logger.warning(f"Unknown caller: {caller_phone}")
    except Exception as e:
        logger.error(f"Error looking up patient: {e}")
    
    # Create CallSession for inbound call
    try:
        async with async_session_factory() as db:
            from app.models import CallType
            import uuid
            
            room_name = f"inbound-{CallSid}"
            
            call_session = CallSession(
                room_name=room_name,
                patient_id=patient.id if patient else None,
                organization_id=UUID(organization_id) if organization_id else None,
                call_type=CallType.INBOUND,
                status=CallStatus.RINGING,
                from_number=caller_phone,
                to_number=To,
                started_at=datetime.now(timezone.utc),
                metadata_={
                    "twilio_call_sid": CallSid,
                    "direction": "inbound",
                    "patient_name": patient_name,
                },
            )
            db.add(call_session)
            await db.commit()
            logger.info(f"Created inbound CallSession: {room_name}")
    except Exception as e:
        logger.error(f"Error creating inbound CallSession: {e}")
    
    # Generate TwiML to route to LiveKit SIP
    # This tells Twilio to connect the call to LiveKit via SIP
    livekit_sip_uri = settings.LIVEKIT_SIP_URI or f"sip:inbound@{settings.LIVEKIT_URL.replace('wss://', '').replace('https://', '')}"
    
    # Include caller info in SIP headers for LiveKit to parse
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Please hold while we connect you to MIRA.</Say>
    <Dial timeout="30" callerId="{To}">
        <Sip username="{caller_phone}">
            {livekit_sip_uri}?X-Patient-Phone={caller_phone}&X-Patient-Name={patient_name.replace(' ', '%20')}&X-Org-Id={organization_id or 'unknown'}
        </Sip>
    </Dial>
    <Say voice="alice">We were unable to connect your call. Please try again later.</Say>
</Response>"""
    
    return PlainTextResponse(content=twiml, media_type="application/xml")


@router.post("/status")
async def handle_call_status(
    request: Request,
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: Optional[str] = Form(None),
    From: str = Form(None),
    To: str = Form(None),
):
    """
    Handle call status updates from Twilio.
    
    Twilio sends status webhooks for: initiated, ringing, answered, completed, failed, busy, no-answer
    """
    logger.info(f"Call status update: {CallSid} -> {CallStatus}, Duration: {CallDuration}")
    
    # Map Twilio status to our CallStatus enum
    status_map = {
        "initiated": CallStatus.INITIATED,
        "ringing": CallStatus.RINGING,
        "in-progress": CallStatus.IN_PROGRESS,
        "answered": CallStatus.IN_PROGRESS,
        "completed": CallStatus.COMPLETED,
        "failed": CallStatus.FAILED,
        "busy": CallStatus.FAILED,
        "no-answer": CallStatus.FAILED,
        "canceled": CallStatus.FAILED,
    }
    
    new_status = status_map.get(CallStatus.lower(), None)
    if not new_status:
        logger.warning(f"Unknown Twilio status: {CallStatus}")
        return {"status": "ignored"}
    
    try:
        async with async_session_factory() as db:
            # Find the call session by Twilio CallSid in metadata
            result = await db.execute(
                select(CallSession).filter(
                    CallSession.metadata_.contains({"twilio_call_sid": CallSid})
                )
            )
            session = result.scalar_one_or_none()
            
            # Also try to find by room name pattern
            if not session:
                result = await db.execute(
                    select(CallSession).filter(
                        CallSession.room_name.like(f"%{CallSid}%")
                    )
                )
                session = result.scalar_one_or_none()
            
            if session:
                session.status = new_status
                
                # Update timestamps based on status
                if CallStatus.lower() in ("answered", "in-progress"):
                    session.answered_at = datetime.now(timezone.utc)
                elif CallStatus.lower() in ("completed", "failed", "busy", "no-answer", "canceled"):
                    session.ended_at = datetime.now(timezone.utc)
                    if CallDuration:
                        session.duration_seconds = int(CallDuration)
                    elif session.answered_at:
                        session.duration_seconds = int(
                            (session.ended_at - session.answered_at).total_seconds()
                        )
                
                await db.commit()
                logger.info(f"Updated CallSession {session.room_name} to status {new_status}")
            else:
                logger.warning(f"No CallSession found for CallSid: {CallSid}")
                
    except Exception as e:
        logger.error(f"Error updating call status: {e}")
    
    return {"status": "received"}


@router.post("/recording")
async def handle_recording_status(
    request: Request,
    CallSid: str = Form(...),
    RecordingSid: str = Form(...),
    RecordingUrl: str = Form(...),
    RecordingStatus: str = Form(...),
    RecordingDuration: Optional[str] = Form(None),
):
    """
    Handle recording status updates from Twilio.
    
    When call recording is enabled, this receives the recording URL.
    """
    logger.info(f"Recording update: {CallSid}, Status: {RecordingStatus}, URL: {RecordingUrl}")
    
    if RecordingStatus != "completed":
        return {"status": "ignored"}
    
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(CallSession).filter(
                    CallSession.metadata_.contains({"twilio_call_sid": CallSid})
                )
            )
            session = result.scalar_one_or_none()
            
            if session:
                # Store recording URL in metadata
                if session.metadata_:
                    session.metadata_["recording_url"] = RecordingUrl
                    session.metadata_["recording_sid"] = RecordingSid
                else:
                    session.metadata_ = {
                        "recording_url": RecordingUrl,
                        "recording_sid": RecordingSid,
                    }
                
                await db.commit()
                logger.info(f"Stored recording URL for CallSession {session.room_name}")
            else:
                logger.warning(f"No CallSession found for recording: {CallSid}")
                
    except Exception as e:
        logger.error(f"Error storing recording: {e}")
    
    return {"status": "received"}
