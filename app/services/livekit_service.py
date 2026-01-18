import uuid
from datetime import timedelta
from typing import Optional

from livekit import api

from app.core.config import settings
from app.utils.logger import logger


class LiveKitService:
    """Service for managing LiveKit rooms and tokens."""

    def __init__(self):
        self.api_key = settings.LIVEKIT_API_KEY
        self.api_secret = settings.LIVEKIT_API_SECRET
        self.host = settings.LIVEKIT_URL

    def create_room_token(
        self,
        room_name: str,
        participant_name: str,
        participant_id: str,
        ttl_seconds: int = 3600,
        can_publish: bool = True,
        can_subscribe: bool = True,
        participant_metadata: Optional[str] = None,
    ) -> str:
        """
        Generate a JWT token for a participant to join a LiveKit room.

        Args:
            room_name: Name of the room to join
            participant_name: Display name of the participant
            participant_id: Unique identifier for the participant
            ttl_seconds: Token validity duration (default: 1 hour)
            can_publish: Allow publishing audio/video
            can_subscribe: Allow subscribing to others' streams
            participant_metadata: Optional JSON metadata for the participant

        Returns:
            JWT token string
        """
        token = api.AccessToken(self.api_key, self.api_secret)
        token.with_identity(participant_id)
        token.with_name(participant_name)
        
        # Set participant metadata if provided
        if participant_metadata:
            token.with_metadata(participant_metadata)
        
        # Configure video grants
        grants = api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=can_publish,
            can_subscribe=can_subscribe,
        )
        token.with_grants(grants)
        
        # Explicitly dispatch agent if configured
        # This is the "Dispatch on participant connection" method from the docs
        if settings.ENABLE_AGENT_DISPATCH:
            # We must use PROTOCOL classes for complex room config
            # Use livekit.api which exports these correctly
            from livekit.api import RoomConfiguration, RoomAgentDispatch
            
            room_config = RoomConfiguration(
                agents=[
                    RoomAgentDispatch(
                        agent_name="mira-voice-agent",
                        metadata='{"user_id": "' + participant_id + '"}'
                    )
                ]
            )
            token.with_room_config(room_config)

        token.ttl = timedelta(seconds=ttl_seconds)

        jwt_token = token.to_jwt()
        logger.info(f"Generated LiveKit token for {participant_id} in room {room_name}")

        return jwt_token

    def create_voice_session_room(self, user_id: str) -> str:
        """Generate a unique room name for a voice session."""
        return f"mira-voice-{user_id}-{uuid.uuid4().hex[:8]}"

    async def create_room(self, room_name: str, empty_timeout: int = 300) -> None:
        """
        Create a LiveKit room via API.

        Args:
            room_name: Name of the room
            empty_timeout: Seconds before empty room is closed (default: 5 min)
        """
        lk_api = api.LiveKitAPI(
            url=self.host,
            api_key=self.api_key,
            api_secret=self.api_secret,
        )

        try:
            await lk_api.room.create_room(
                api.CreateRoomRequest(
                    name=room_name,
                    empty_timeout=empty_timeout,
                )
            )
            logger.info(f"Created LiveKit room: {room_name}")
        finally:
            await lk_api.aclose()

    async def delete_room(self, room_name: str) -> None:
        """Delete a LiveKit room."""
        lk_api = api.LiveKitAPI(
            url=self.host,
            api_key=self.api_key,
            api_secret=self.api_secret,
        )

        try:
            await lk_api.room.delete_room(api.DeleteRoomRequest(room=room_name))
            logger.info(f"Deleted LiveKit room: {room_name}")
        finally:
            await lk_api.aclose()

    async def list_rooms(self) -> list:
        """List all active LiveKit rooms."""
        lk_api = api.LiveKitAPI(
            url=self.host,
            api_key=self.api_key,
            api_secret=self.api_secret,
        )

        try:
            response = await lk_api.room.list_rooms(api.ListRoomsRequest())
            return response.rooms
        finally:
            await lk_api.aclose()
