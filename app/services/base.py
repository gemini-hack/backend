from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User, Organization, AuditLog


class BaseService:
    """Base service class for shared functionality."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def _get_user_by_email(
        self,
        email: str,
        include_org: bool = False,
    ) -> Optional[User]:
        """Get user by email."""
        query = select(User).where(User.email == email.lower())
        if include_org:
            query = query.options(selectinload(User.organization))
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
        
    async def _get_organization_by_email(self, email: str) -> Optional[Organization]:
        """Get organization by email."""
        result = await self.db.execute(
            select(Organization).where(Organization.email == email.lower())
        )
        return result.scalar_one_or_none()
    
    async def _log_audit(
        self,
        user_id: UUID,
        organization_id: UUID,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        details: Optional[dict] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        """Log an audit event."""
        # Ensure AuditLog model exists and imports are correct
        audit_log = AuditLog(
            user_id=user_id,
            organization_id=organization_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
        )
        self.db.add(audit_log)
