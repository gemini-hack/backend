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
        if include_org:
            return await User.fetch_one_with(self.db, "organization", email=email.lower())
        return await User.fetch_unique(self.db, email=email.lower())
        
    async def _get_organization_by_email(self, email: str) -> Optional[Organization]:
        """Get organization by email."""
        return await Organization.fetch_unique(self.db, email=email.lower())
    
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
