import json
import uuid
from datetime import datetime, timezone

from livekit import api

from app.core.config import settings
from app.utils.logger import logger


class LiveKitSIPService:
    """
    Service for managing phone calls via LiveKit SIP + Twilio.
    
    This service handles:
    - Outbound calls: MIRA dials patients via Twilio SIP trunk
    - Inbound calls: Patients dial in, routed to MIRA
    
    Note: Requires LiveKit SIP support and Twilio credentials configured.
    """
    
    def __init__(self):
        self.api_key = settings.LIVEKIT_API_KEY
        self.api_secret = settings.LIVEKIT_API_SECRET
        self.host = settings.LIVEKIT_URL
        self.sip_enabled = settings.LIVEKIT_SIP_ENABLED
        
        # Twilio Config
        self.sip_domain = settings.TWILIO_SIP_DOMAIN
        self.account_sid = settings.TWILIO_ACCOUNT_SID
        self.auth_token = settings.TWILIO_AUTH_TOKEN
        self.phone_number = settings.TWILIO_PHONE_NUMBER
        self.trunk_id = settings.TWILIO_SIP_TRUNK_ID
    
    @property
    def from_number(self) -> str:
        """Get the outbound phone number."""
        return self.phone_number
    
    def _get_api(self) -> api.LiveKitAPI:
        """Create a LiveKit API client."""
        return api.LiveKitAPI(
            url=self.host,
            api_key=self.api_key,
            api_secret=self.api_secret,
        )
    
    async def initiate_outbound_call(
        self,
        patient_phone: str,
        session_id: str,
        metadata: dict,
    ) -> str:
        """
        Initiate an outbound SIP call to a patient via Twilio.
        
        Args:
            patient_phone: Patient's phone number (E.164 format)
            session_id: Unique session identifier
            metadata: Call context
        
        Returns:
            Room name for tracking the call
        """
        if not self.is_sip_enabled():
            raise ValueError(
                "LiveKit SIP is not enabled or Twilio is not configured. "
                "Set LIVEKIT_SIP_ENABLED=true and configure Twilio credentials."
            )
        
        room_name = f"call-{session_id}"
        
        # Add provider info to metadata
        metadata["sip_provider"] = "twilio"
        metadata["from_number"] = self.from_number
        
        lk_api = self._get_api()
        try:
            # Create the room for this call
            await lk_api.room.create_room(
                api.CreateRoomRequest(
                    name=room_name,
                    empty_timeout=300,  # 5 min timeout if empty
                    metadata=json.dumps(metadata),
                )
            )
            logger.info(f"Created call room: {room_name}")
            
            # Create SIP participant to dial the patient via Twilio
            # For Twilio, we typically use the SIP URI format: sip:number@domain
            # Note: This assumes LiveKit is configured to accept outbound SIP
            # requests that map to your Twilio trunk.
            
            # Construct SIP URI for Twilio
            # Often maps to: sip:{phone}@{your-twilio-domain}
            # Or if using direct trunking, LiveKit handles the trunk selection by ID
            
            sip_request = api.CreateSIPParticipantRequest(
                sip_trunk_id=self.trunk_id,
                sip_call_to=patient_phone,
                sip_number=self.phone_number,  # Caller ID / From number
                room_name=room_name,
                participant_identity=f"patient-{session_id}",
                participant_name="Patient",
                participant_metadata=json.dumps({
                    "type": "sip_caller",
                    "phone": patient_phone,
                    "provider": "twilio",
                }),
                play_dialtone=True,  # Audio feedback while dialing
            )
            
            await lk_api.sip.create_sip_participant(sip_request)
            logger.info(f"Twilio SIP call initiated to {patient_phone} from {self.phone_number}")
            
            return room_name
            
        except Exception as e:
            logger.error(f"Failed to initiate Twilio SIP call: {e}")
            # Attempt cleanup
            try:
                await lk_api.room.delete_room(api.DeleteRoomRequest(room=room_name))
            except Exception:
                pass
            raise
        finally:
            await lk_api.aclose()
    
    async def end_call(self, room_name: str) -> None:
        """End a call by closing the LiveKit room."""
        lk_api = self._get_api()
        try:
            await lk_api.room.delete_room(api.DeleteRoomRequest(room=room_name))
            logger.info(f"Ended call room: {room_name}")
        except Exception as e:
            logger.warning(f"Failed to delete call room {room_name}: {e}")
        finally:
            await lk_api.aclose()
    
    async def get_call_participants(self, room_name: str) -> list:
        """Get list of participants in a call room."""
        lk_api = self._get_api()
        try:
            response = await lk_api.room.list_participants(
                api.ListParticipantsRequest(room=room_name)
            )
            return [
                {
                    "identity": p.identity,
                    "name": p.name,
                    "state": p.state,
                    "joined_at": p.joined_at,
                }
                for p in response.participants
            ]
        except Exception as e:
            logger.warning(f"Failed to get participants for {room_name}: {e}")
            return []
        finally:
            await lk_api.aclose()
    
    def is_sip_enabled(self) -> bool:
        """Check if SIP calling is enabled and properly configured for Twilio."""
        return (
            self.sip_enabled
            and bool(self.account_sid)
            and bool(self.phone_number)
            and bool(self.sip_domain)
        )
    
    def get_provider_status(self) -> dict:
        """Get detailed status of the Twilio configuration."""
        return {
            "enabled": self.sip_enabled,
            "provider": "twilio",
            "configured": self.is_sip_enabled(),
            "phone_number": self.phone_number if self.is_sip_enabled() else "",
            "sip_domain": self.sip_domain,
        }

