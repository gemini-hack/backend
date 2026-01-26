from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.user import Organization
from app.services.twilio_provisioning import TwilioProvisioningService
from app.core.config import settings
from app.utils.logger import logger


class PhoneSettingsService:
    """Service for phone provisioning and management."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.twilio = TwilioProvisioningService()
    
    def is_configured(self) -> bool:
        """Check if Twilio provisioning is configured."""
        return self.twilio.is_configured()
    
    async def get_organization(self, org_id: UUID) -> Organization:
        """Get organization by ID."""
        result = await self.db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = result.scalar_one_or_none()
        if not org:
            raise ValueError("Organization not found")
        return org
    
    async def get_status(self, org_id: UUID) -> dict:
        """Get phone status for organization."""
        org = await self.get_organization(org_id)
        settings = org.phone_settings or {}
        
        return {
            "enabled": settings.get("enabled", False),
            "phone_number": settings.get("phone_number"),
            "provisioned_at": settings.get("provisioned_at"),
            "sip_trunk_id": settings.get("sip_trunk_id"),
            "status": "active" if settings.get("enabled") else "disabled",
        }
    
    async def search_numbers(
        self,
        country: str = "US",
        area_code: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """Search available phone numbers."""
        if not self.is_configured():
            raise ValueError("Phone provisioning not configured")
        
        return await self.twilio.search_available_numbers(
            country=country,
            area_code=area_code,
            limit=limit,
        )
    
    async def provision(self, org_id: UUID, phone_number: str) -> dict:
        """Provision a phone number with SIP trunk.
        
        Args:
            org_id: Organization ID
            phone_number: E.164 format phone number
            
        Returns:
            Provision result dict
        """
        if not self.is_configured():
            raise ValueError("Phone provisioning not configured")
        
        # Validate E.164 format
        import re
        if not re.match(r'^\+[1-9]\d{6,14}$', phone_number):
            raise ValueError(
                f"Invalid phone number format: {phone_number}. "
                "Must be E.164 format (e.g., +12025551234)"
            )
        
        org = await self.get_organization(org_id)
        settings = org.phone_settings.copy() if org.phone_settings else {}
        
        # Track what we've created for potential rollback
        created_subaccount = False
        created_phone = False
        phone_sid = None
        sip_trunk_id = None
        
        try:
            # Create Twilio subaccount if needed
            if not settings.get("twilio_subaccount_sid"):
                subaccount = await self.twilio.create_subaccount(org.name)
                settings["twilio_subaccount_sid"] = subaccount["sid"]
                settings["twilio_auth_token"] = subaccount["auth_token"]
                created_subaccount = True
            
            # Provision phone number with webhooks
            base_url = settings.API_BASE_URL.rstrip('/')
            voice_url = f"{base_url}/api/v1/webhooks/twilio/voice"
            status_callback = f"{base_url}/api/v1/webhooks/twilio/status"
            
            result = await self.twilio.provision_number(
                subaccount_sid=settings["twilio_subaccount_sid"],
                phone_number=phone_number,
                voice_url=voice_url,
                status_callback=status_callback,
            )
            phone_sid = result["phone_sid"]
            created_phone = True
            
            # Create LiveKit SIP trunk
            try:
                sip_trunk_id = await self.twilio.create_livekit_sip_trunk(
                    org_name=org.name,
                    phone_number=phone_number,
                    auth_username=settings["twilio_subaccount_sid"],
                    auth_password=settings["twilio_auth_token"],
                )
                settings["sip_trunk_id"] = sip_trunk_id
                logger.info(f"SIP trunk created: {sip_trunk_id}")
            except Exception as e:
                logger.warning(f"SIP trunk creation failed: {e}")
                # Continue without SIP trunk - phone can still be used
            
            # Update settings
            settings.update({
                "enabled": True,
                "phone_number": phone_number,
                "phone_sid": phone_sid,
                "provisioned_at": result["provisioned_at"],
            })
            org.phone_settings = settings
            flag_modified(org, "phone_settings")  # Force JSONB change detection
            
            await self.db.commit()
            await self.db.refresh(org)
            
            logger.info(f"Phone provisioned: org={org_id} number={phone_number}")
            
            return {
                "success": True,
                "phone_number": phone_number,
                "sip_trunk_id": sip_trunk_id,
            }
            
        except Exception as e:
            # Rollback: Clean up any created resources
            logger.error(f"Provisioning failed, rolling back: {e}")
            
            if created_phone and phone_sid:
                try:
                    await self.twilio.release_number(
                        subaccount_sid=settings["twilio_subaccount_sid"],
                        phone_sid=phone_sid,
                    )
                    logger.info("Rolled back: Released phone number")
                except Exception as rollback_err:
                    logger.warning(f"Rollback failed for phone: {rollback_err}")
            
            if sip_trunk_id:
                try:
                    await self.twilio.delete_livekit_sip_trunk(sip_trunk_id)
                    logger.info("Rolled back: Deleted SIP trunk")
                except Exception as rollback_err:
                    logger.warning(f"Rollback failed for SIP trunk: {rollback_err}")
            
            raise
    
    async def disable(self, org_id: UUID) -> dict:
        """Disable phone calling and release resources.
        
        Args:
            org_id: Organization ID
            
        Returns:
            Disable result dict
        """
        org = await self.get_organization(org_id)
        settings = org.phone_settings.copy() if org.phone_settings else {}
        
        if not settings.get("enabled"):
            raise ValueError("Phone calling not enabled")
        
        # Delete SIP trunk
        if settings.get("sip_trunk_id"):
            try:
                await self.twilio.delete_livekit_sip_trunk(settings["sip_trunk_id"])
                logger.info(f"SIP trunk deleted: {settings['sip_trunk_id']}")
            except Exception as e:
                logger.warning(f"SIP trunk delete failed: {e}")
        
        # Release phone number
        if settings.get("phone_sid") and settings.get("twilio_subaccount_sid"):
            await self.twilio.release_number(
                subaccount_sid=settings["twilio_subaccount_sid"],
                phone_sid=settings["phone_sid"],
            )
        
        # Clear settings (keep subaccount for potential reuse)
        settings.update({
            "enabled": False,
            "phone_number": None,
            "phone_sid": None,
            "sip_trunk_id": None,
            "disabled_at": datetime.now(timezone.utc).isoformat(),
        })
        org.phone_settings = settings
        flag_modified(org, "phone_settings")  # Force JSONB change detection
        
        await self.db.commit()
        await self.db.refresh(org)
        
        logger.info(f"Phone disabled: org={org_id}")
        
        return {
            "success": True,
            "message": "Phone calling disabled",
        }
