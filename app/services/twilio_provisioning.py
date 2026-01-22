import asyncio
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.utils.logger import logger


class TwilioProvisioningService:
    """
    Manages Twilio subaccounts and phone numbers for organizations.
    
    Uses the master Twilio account to create isolated subaccounts
    for each organization, enabling per-org billing and phone numbers.
    """
    
    def __init__(self):
        self.master_sid = settings.TWILIO_MASTER_ACCOUNT_SID
        self.master_token = settings.TWILIO_MASTER_AUTH_TOKEN
        self._client = None
    
    @property
    def client(self):
        """Lazy-load Twilio client."""
        if self._client is None:
            try:
                from twilio.rest import Client
                self._client = Client(self.master_sid, self.master_token)
            except ImportError:
                raise ImportError("twilio package not installed. Run: pip install twilio")
        return self._client
    
    def is_configured(self) -> bool:
        """Check if master Twilio credentials are configured."""
        return bool(self.master_sid and self.master_token)
    
    async def create_subaccount(self, org_name: str) -> dict:
        """
        Create a Twilio subaccount for an organization.
        
        Args:
            org_name: Organization name for the friendly name
            
        Returns:
            Dict with subaccount sid and auth_token
        """
        if not self.is_configured():
            raise ValueError("Twilio master credentials not configured")
        
        friendly_name = f"MIRA-{org_name[:50]}"
        
        try:
            account = await asyncio.to_thread(
                self.client.api.v2010.accounts.create,
                friendly_name=friendly_name
            )
            
            logger.info(f"Created Twilio subaccount: {account.sid} for {org_name}")
            
            return {
                "sid": account.sid,
                "auth_token": account.auth_token,
                "friendly_name": friendly_name,
                "status": account.status,
            }
        except Exception as e:
            logger.error(f"Failed to create Twilio subaccount: {e}")
            raise
    
    async def search_available_numbers(
        self,
        country: str = "US",
        area_code: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Search for available phone numbers.
        
        Args:
            country: ISO country code
            area_code: Optional area code filter
            limit: Max results to return
            
        Returns:
            List of available numbers with details
        """
        if not self.is_configured():
            raise ValueError("Twilio master credentials not configured")
        
        kwargs = {"voice_enabled": True, "sms_enabled": True, "limit": limit}
        if area_code:
            kwargs["area_code"] = area_code
        
        try:
            numbers = await asyncio.to_thread(
                self.client.available_phone_numbers(country).local.list,
                **kwargs
            )
            
            return [
                {
                    "phone_number": n.phone_number,
                    "friendly_name": n.friendly_name,
                    "locality": n.locality,
                    "region": n.region,
                    "postal_code": n.postal_code,
                    "capabilities": {
                        "voice": n.capabilities.get("voice", False),
                        "sms": n.capabilities.get("SMS", False),
                    },
                }
                for n in numbers
            ]
        except Exception as e:
            logger.error(f"Failed to search phone numbers: {e}")
            raise
    
    async def provision_number(
        self,
        subaccount_sid: str,
        phone_number: str,
        voice_url: Optional[str] = None,
        status_callback: Optional[str] = None,
    ) -> dict:
        """
        Provision a phone number in a subaccount.
        
        Args:
            subaccount_sid: The subaccount to provision in
            phone_number: E.164 format phone number
            voice_url: Webhook URL for incoming calls
            status_callback: Webhook URL for status updates
            
        Returns:
            Dict with phone_sid and details
        """
        if not self.is_configured():
            raise ValueError("Twilio master credentials not configured")
        
        try:
            from twilio.rest import Client
            
            # Use master auth token with subaccount SID
            sub_client = Client(subaccount_sid, self.master_token)
            
            kwargs = {"phone_number": phone_number}
            if voice_url:
                kwargs["voice_url"] = voice_url
                kwargs["voice_method"] = "POST"
            if status_callback:
                kwargs["status_callback"] = status_callback
                kwargs["status_callback_method"] = "POST"
            
            incoming = await asyncio.to_thread(
                sub_client.incoming_phone_numbers.create,
                **kwargs
            )
            
            logger.info(f"Provisioned number {phone_number} in subaccount {subaccount_sid}")
            
            return {
                "phone_sid": incoming.sid,
                "phone_number": incoming.phone_number,
                "friendly_name": incoming.friendly_name,
                "provisioned_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error(f"Failed to provision number: {e}")
            raise
    
    async def release_number(self, subaccount_sid: str, phone_sid: str) -> bool:
        """
        Release a phone number from a subaccount.
        
        Args:
            subaccount_sid: The subaccount owning the number
            phone_sid: The phone number SID (PN...)
            
        Returns:
            True if successfully released
        """
        if not self.is_configured():
            raise ValueError("Twilio master credentials not configured")
        
        try:
            from twilio.rest import Client
            
            sub_client = Client(subaccount_sid, self.master_token)
            await asyncio.to_thread(
                sub_client.incoming_phone_numbers(phone_sid).delete
            )
            
            logger.info(f"Released phone {phone_sid} from subaccount {subaccount_sid}")
            return True
        except Exception as e:
            logger.error(f"Failed to release number: {e}")
            raise
    
    async def suspend_subaccount(self, subaccount_sid: str) -> bool:
        """Suspend a subaccount (pauses all activity)."""
        try:
            await asyncio.to_thread(
                self.client.api.v2010.accounts(subaccount_sid).update,
                status="suspended"
            )
            logger.info(f"Suspended subaccount: {subaccount_sid}")
            return True
        except Exception as e:
            logger.error(f"Failed to suspend subaccount: {e}")
            raise
    
    async def reactivate_subaccount(self, subaccount_sid: str) -> bool:
        """Reactivate a suspended subaccount."""
        try:
            await asyncio.to_thread(
                self.client.api.v2010.accounts(subaccount_sid).update,
                status="active"
            )
            logger.info(f"Reactivated subaccount: {subaccount_sid}")
            return True
        except Exception as e:
            logger.error(f"Failed to reactivate subaccount: {e}")
            raise
    
    async def close_subaccount(self, subaccount_sid: str) -> bool:
        """Permanently close a subaccount (cannot be undone)."""
        try:
            await asyncio.to_thread(
                self.client.api.v2010.accounts(subaccount_sid).update,
                status="closed"
            )
            logger.info(f"Closed subaccount: {subaccount_sid}")
            return True
        except Exception as e:
            logger.error(f"Failed to close subaccount: {e}")
            raise
    
    # =========================================================================
    # LiveKit SIP Trunk Management
    # =========================================================================
    
    async def create_livekit_sip_trunk(
        self,
        org_name: str,
        phone_number: str,
        auth_username: str,
        auth_password: str,
    ) -> str:
        """
        Create a LiveKit outbound SIP trunk for an organization.
        
        This allows the organization to place outbound calls via Twilio
        using their own provisioned phone number.
        
        Args:
            org_name: Organization name for trunk identification
            phone_number: E.164 phone number (e.g., +15105550100)
            auth_username: Twilio SIP username for authentication
            auth_password: Twilio SIP password for authentication
            
        Returns:
            LiveKit SIP trunk ID (e.g., ST_xxxxxxxxxxxx)
        """
        try:
            from livekit import api
            from livekit.protocol.sip import CreateSIPOutboundTrunkRequest, SIPOutboundTrunkInfo
            
            lk_api = api.LiveKitAPI(
                url=settings.LIVEKIT_URL,
                api_key=settings.LIVEKIT_API_KEY,
                api_secret=settings.LIVEKIT_API_SECRET,
            )
            
            # Create trunk info
            # Address format for Twilio: <trunk-name>.pstn.twilio.com
            trunk_info = SIPOutboundTrunkInfo(
                name=f"mira-{org_name[:30]}",
                address=settings.TWILIO_SIP_DOMAIN,  # e.g., mira-ai.pstn.twilio.com
                numbers=[phone_number],
                auth_username=auth_username,
                auth_password=auth_password,
            )
            
            request = CreateSIPOutboundTrunkRequest(trunk=trunk_info)
            
            trunk = await lk_api.sip.create_outbound_trunk(request)
            await lk_api.aclose()
            
            trunk_id = trunk.sip_trunk_id
            logger.info(f"Created LiveKit SIP trunk: {trunk_id} for {org_name}")
            
            return trunk_id
            
        except ImportError as e:
            logger.error(f"livekit package not properly installed: {e}")
            raise ImportError("livekit package required for SIP trunk creation")
        except Exception as e:
            logger.error(f"Failed to create LiveKit SIP trunk: {e}")
            raise
    
    async def delete_livekit_sip_trunk(self, trunk_id: str) -> bool:
        """
        Delete a LiveKit SIP trunk.
        
        Args:
            trunk_id: The SIP trunk ID (ST_xxxx)
            
        Returns:
            True if successfully deleted
        """
        try:
            from livekit import api
            from livekit.protocol.sip import DeleteSIPTrunkRequest
            
            lk_api = api.LiveKitAPI(
                url=settings.LIVEKIT_URL,
                api_key=settings.LIVEKIT_API_KEY,
                api_secret=settings.LIVEKIT_API_SECRET,
            )
            
            await lk_api.sip.delete_trunk(
                DeleteSIPTrunkRequest(sip_trunk_id=trunk_id)
            )
            await lk_api.aclose()
            
            logger.info(f"Deleted LiveKit SIP trunk: {trunk_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete LiveKit SIP trunk: {e}")
            raise
    
    async def list_livekit_sip_trunks(self) -> list[dict]:
        """
        List all LiveKit outbound SIP trunks.
        
        Returns:
            List of trunk details
        """
        try:
            from livekit import api
            from livekit.protocol.sip import ListSIPOutboundTrunkRequest
            
            lk_api = api.LiveKitAPI(
                url=settings.LIVEKIT_URL,
                api_key=settings.LIVEKIT_API_KEY,
                api_secret=settings.LIVEKIT_API_SECRET,
            )
            
            response = await lk_api.sip.list_outbound_trunk(
                ListSIPOutboundTrunkRequest()
            )
            await lk_api.aclose()
            
            return [
                {
                    "sip_trunk_id": t.sip_trunk_id,
                    "name": t.name,
                    "address": t.address,
                    "numbers": list(t.numbers),
                }
                for t in response.items
            ]
            
        except Exception as e:
            logger.error(f"Failed to list LiveKit SIP trunks: {e}")
            raise


async def provision_phone_with_sip_trunk(
    service: TwilioProvisioningService,
    org_name: str,
    phone_number: str,
    subaccount_sid: str,
    sip_username: str,
    sip_password: str,
    voice_webhook_url: Optional[str] = None,
) -> dict:
    """
    Complete provisioning: Twilio number + LiveKit SIP trunk.
    
    Args:
        service: TwilioProvisioningService instance
        org_name: Organization name
        phone_number: Phone number to provision
        subaccount_sid: Twilio subaccount SID
        sip_username: SIP auth username
        sip_password: SIP auth password
        voice_webhook_url: Optional webhook for incoming calls
        
    Returns:
        Dict with phone_sid, sip_trunk_id, and other details
    """
    # 1. Provision phone number in Twilio
    provision_result = await service.provision_number(
        subaccount_sid=subaccount_sid,
        phone_number=phone_number,
        voice_url=voice_webhook_url,
    )
    
    # 2. Create LiveKit SIP trunk
    sip_trunk_id = await service.create_livekit_sip_trunk(
        org_name=org_name,
        phone_number=phone_number,
        auth_username=sip_username,
        auth_password=sip_password,
    )
    
    return {
        **provision_result,
        "sip_trunk_id": sip_trunk_id,
    }

