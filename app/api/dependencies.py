from typing import Annotated
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.core.permissions import ROLE_PERMISSIONS
from app.utils.exceptions import PermissionDeniedException

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
    
    Verifies if the current user has the required permission based on their role.
    """
    async def permission_checker(user: CurrentUser) -> User:
        
        # Get permissions for user's role
        user_permissions = ROLE_PERMISSIONS.get(user.role, [])
        
        # Check for superuser wildcard
        if "*" in user_permissions:
            return user
            
        # Check specific permission
        # Logic: 
        # 1. Exact match
        # 2. Resource wildcard (e.g. "patients:*")
        
        # Split required permission into resource:action
        try:
            resource, action = permission.split(":")
        except ValueError:
            # Fallback for simple permissions without colon
            if permission in user_permissions:
                return user
            raise PermissionDeniedException(f"Permission '{permission}' required")

        # Check exact and wildcard matches
        for user_perm in user_permissions:
            if user_perm == permission:
                return user
            
            # Check if user has "resource:*" permission
            if user_perm == f"{resource}:*":
                return user
        
        raise PermissionDeniedException(f"Permission '{permission}' required")
    
    return permission_checker
