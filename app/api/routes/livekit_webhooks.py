import hmac
import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, status
from pydantic import BaseModel

from app.db.database import async_session_factory
from app.models import CallSession, CallStatus
from app.utils.logger import logger
from app.core.config import settings

router = APIRouter(tags=["Webhooks"])


class WebhookEvent(BaseModel):
    """LiveKit webhook event structure."""
    event: str
    room: dict | None = None
    participant: dict | None = None
    track: dict | None = None
    egress_info: dict | None = None
    ingress_info: dict | None = None


def verify_webhook_signature(body: bytes, signature: str | None) -> bool:
    """
    Verify the webhook signature from LiveKit.
    
    LiveKit signs webhooks with HMAC-SHA256 using the API secret.
    """
    if not signature:
        return False
    
    expected = hmac.new(
        settings.LIVEKIT_API_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    
    return hmac.compare_digest(expected, signature)


async def update_call_status(room_name: str, new_status: CallStatus) -> None:
    """Update call session status in database."""
    async with async_session_factory() as db:
        call_session = await CallSession.fetch_one(db, room_name=room_name)
        
        if not call_session:
            logger.warning(f"CallSession not found for room: {room_name}")
            return
        
        call_session.status = new_status
        
        if new_status == CallStatus.ANSWERED and not call_session.answered_at:
            call_session.answered_at = datetime.now(timezone.utc)
        elif new_status in (CallStatus.COMPLETED, CallStatus.FAILED, CallStatus.NO_ANSWER):
            call_session.ended_at = datetime.now(timezone.utc)
            if call_session.answered_at:
                call_session.duration_seconds = int(
                    (call_session.ended_at - call_session.answered_at).total_seconds()
                )
        
        await call_session.save(db)
        logger.info(f"Updated call status: {room_name} -> {new_status.value}")


@router.post("/livekit/webhook")
async def livekit_webhook(request: Request):
    """
    Handle LiveKit webhook events for call status tracking.
    
    Events of interest:
    - participant_joined: SIP participant answered
    - participant_left: Participant disconnected
    - room_finished: Call ended
    """
    body = await request.body()
    
    # Verify signature in production
    if not settings.DEBUG:
        signature = request.headers.get("X-LiveKit-Signature")
        if not verify_webhook_signature(body, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )
    
    try:
        import json
        data = json.loads(body)
        event_type = data.get("event", "")
        room_info = data.get("room", {})
        participant_info = data.get("participant", {})
        
        room_name = room_info.get("name", "")
        participant_identity = participant_info.get("identity", "")
        
        # Only process call rooms
        if not room_name.startswith("call-"):
            return {"status": "ok", "processed": False}
        
        logger.info(f"LiveKit webhook: {event_type} for room {room_name}")
        
        # Handle participant events
        if event_type == "participant_joined":
            # Check if this is the SIP participant (patient answering)
            if participant_identity.startswith("patient-") or participant_identity.startswith("sip_"):
                await update_call_status(room_name, CallStatus.ANSWERED)
                
        elif event_type == "participant_left":
            # SIP participant left - call may be ending
            if participant_identity.startswith("patient-") or participant_identity.startswith("sip_"):
                await update_call_status(room_name, CallStatus.COMPLETED)
                
        elif event_type == "room_finished":
            # Room closed - call definitely ended
            await update_call_status(room_name, CallStatus.COMPLETED)
        
        return {"status": "ok", "processed": True}
        
    except Exception as e:
        logger.exception(f"Error processing LiveKit webhook: {e}")
        # Return 200 to prevent retries for parsing errors
        return {"status": "error", "message": str(e)}


@router.get("/livekit/webhook/health")
async def livekit_webhook_health():
    """Health check endpoint for LiveKit webhook configuration."""
    return {
        "status": "ok",
        "sip_enabled": settings.LIVEKIT_SIP_ENABLED,
        "webhook_configured": True,
    }
