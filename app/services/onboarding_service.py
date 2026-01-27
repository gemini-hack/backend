from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.user import Organization
from app.schemas.onboarding import OnboardingCompleteRequest
from app.utils.exceptions import NotFoundException, BadRequestException
from app.utils.logger import logger


class OnboardingService:
    """Service for organization onboarding operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_organization(self, org_id: UUID) -> Organization:
        """Get organization by ID."""
        result = await self.db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = result.scalar_one_or_none()
        if not org:
            raise NotFoundException("Organization not found")
        return org
    
    async def get_status(self, org_id: UUID) -> dict:
        """Get onboarding status for organization."""
        org = await self.get_organization(org_id)
        
        return {
            "is_completed": org.is_onboarded,
            "completed_at": org.onboarding_completed_at,
            "organization_name": org.name,
            "organization_type": org.type,
            "timezone": getattr(org, "timezone", None),
        }
    
    async def complete(
        self,
        org_id: UUID,
        request: OnboardingCompleteRequest,
    ) -> dict:
        """Complete onboarding for organization.
        
        Args:
            org_id: Organization ID
            request: Onboarding request data (timezone from frontend JS)
            
        Returns:
            Completion result dict
            
        Raises:
            BadRequestException: If already onboarded
            NotFoundException: If organization not found
        """
        org = await self.get_organization(org_id)
        
        if org.is_onboarded:
            raise BadRequestException("Onboarding already completed")
        
        # Default to UTC if not provided
        tz = request.timezone or "UTC"
        
        # Update organization fields
        if request.address:
            org.address = request.address
        if request.license_number:
            org.license_number = request.license_number
        if request.disease_specializations:
            org.disease_specializations = request.disease_specializations
            flag_modified(org, "disease_specializations")
        org.timezone = tz
        
        # Mark complete
        completed_at = datetime.now(timezone.utc)
        org.is_onboarded = True
        org.onboarding_completed_at = completed_at
        
        await self.db.commit()
        await self.db.refresh(org)
        
        logger.info(f"Onboarding complete: org={org_id} tz={tz}")
        
        return {
            "success": True,
            "message": "Welcome! Your organization is ready.",
            "completed_at": completed_at,
            "timezone": tz,
        }
