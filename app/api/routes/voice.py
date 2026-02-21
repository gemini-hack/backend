import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.dependencies import CurrentUser, DbSession, require_permission
from app.services.livekit_service import LiveKitService
from app.core.config import settings
from app.utils.responses import success_response

router = APIRouter(prefix="/voice", tags=["Voice"])


class VoiceSessionResponse(BaseModel):
    room_name: str
    token: str
    livekit_url: str


@router.post(
    "/session",
    status_code=status.HTTP_200_OK,
    summary="Create voice session",
    response_model=None,
)
async def create_voice_session(
    user: CurrentUser,
    db: DbSession,
):
    """
    Create a new voice session with MIRA AI.

    Returns a LiveKit room name, access token, and server URL.
    The client uses these to connect via WebRTC.
    """
    import json
    from livekit import api
    
    service = LiveKitService()

    # Generate unique room name
    room_name = service.create_voice_session_room(str(user.id))
    
    # Prepare user metadata for the voice agent's security context
    user_metadata = json.dumps({
        "user_id": str(user.id),
        "organization_id": str(user.organization_id),
        "role": user.role.value,
        "full_name": user.full_name,
    })
    
    # Create the room explicitly with agent dispatch
    # This is required for named agents (explicit dispatch mode)
    if settings.ENABLE_AGENT_DISPATCH:
        lk_api = api.LiveKitAPI(
            url=settings.LIVEKIT_URL,
            api_key=settings.LIVEKIT_API_KEY,
            api_secret=settings.LIVEKIT_API_SECRET,
        )
        try:
            await lk_api.room.create_room(
                api.CreateRoomRequest(
                    name=room_name,
                    empty_timeout=300,  # 5 minutes
                    metadata=user_metadata,  # Room-level metadata for agent
                )
            )
            # Dispatch the named agent to this room
            await lk_api.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    room=room_name,
                    agent_name=settings.VOICE_AGENT_NAME,
                    metadata=user_metadata,
                )
            )
        finally:
            await lk_api.aclose()

    # Generate access token for the user with metadata
    token = service.create_room_token(
        room_name=room_name,
        participant_name=user.full_name,
        participant_id=str(user.id),
        participant_metadata=user_metadata,
    )

    return success_response(
        status_code=status.HTTP_200_OK,
        message="Voice session created",
        data={
            "room_name": room_name,
            "token": token,
            "livekit_url": settings.LIVEKIT_URL,
        },
    )


@router.delete(
    "/session/{room_name}",
    status_code=status.HTTP_200_OK,
    summary="End voice session",
)
async def end_voice_session(
    room_name: str,
    user: CurrentUser,
    db: DbSession,
):
    """End a voice session and clean up the room."""
    if not room_name.startswith(f"voice-{user.id}"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to end this session",
        )

    service = LiveKitService()

    try:
        await service.delete_room(room_name)
    except Exception:
        pass

    return success_response(
        status_code=status.HTTP_200_OK,
        message="Voice session ended",
    )


@router.get(
    "/sessions",
    status_code=status.HTTP_200_OK,
    summary="List active voice sessions",
    dependencies=[Depends(require_permission("agents:read"))],
)
async def list_voice_sessions(
    user: CurrentUser,
    db: DbSession,
):
    """List all active voice sessions (admin only)."""
    service = LiveKitService()
    rooms = await service.list_rooms()

    return success_response(
        status_code=status.HTTP_200_OK,
        message="Active voice sessions",
        data={
            "sessions": [
                {"room_name": r.name, "participants": r.num_participants}
                for r in rooms
            ]
        },
    )
