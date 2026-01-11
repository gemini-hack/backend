from typing import Annotated
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.deps import get_current_user
from app.models.user import User

# Type aliases for cleaner route signatures
CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request."""
    # Check for forwarded IP first (if behind proxy)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    
    # Check for real IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fall back to direct client
    if request.client:
        return request.client.host
    
    return "unknown"


def get_user_agent(request: Request) -> str:
    """Extract user agent from request."""
    return request.headers.get("User-Agent", "unknown")


def require_permission(permission: str):
    """
    Dependency factory for permission checks.
    
    For now, this is a placeholder. You can implement proper
    permission-based access control based on your requirements.
    
    Example permissions: "invitations:create", "invitations:read", "invitations:revoke"
    """
    async def permission_checker(user: CurrentUser) -> User:
        # TODO: Implement actual permission checking logic
        # For now, allow any authenticated user with a valid role
        from app.models.user import UserRole
        
        # All roles (Owner, Admin, Doctor, Nurse, Coordinator) are allowed
    
        if user.role in [
            UserRole.ORG_OWNER, 
            UserRole.ORG_ADMIN, 
            UserRole.DOCTOR, 
            UserRole.NURSE, 
            UserRole.COORDINATOR
        ]:
            return user
        
        from app.utils.exceptions import PermissionDeniedException
        raise PermissionDeniedException(f"Permission '{permission}' required")
    
    return permission_checker
