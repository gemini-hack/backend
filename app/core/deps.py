from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import Optional
import uuid

from app.core.config import settings
from app.db.database import get_db
from app.models.user import User, UserRole
from app.utils.security import decode_token

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Dependency to get the current authenticated user.
    Validates the access token and returns the User object.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception
    
    token = credentials.credentials

    try:
        payload = decode_token(token)
        
        # Verify token type
        if payload.get("type") != "access":
            raise credentials_exception
        
        user_id = payload.get("sub")
        org_id = payload.get("org_id")
        role = payload.get("role")
        
        if not user_id:
            raise credentials_exception
        
        # Store in request state for logging/middleware
        request.state.user_id = user_id
        request.state.org_id = org_id
        request.state.role = role
        
    except JWTError:
        raise credentials_exception

    # Convert user_id string to UUID
    try:
        user_id_uuid = uuid.UUID(user_id)
    except (ValueError, AttributeError):
        raise credentials_exception

    # Async query with eager loading of organization
    result = await db.execute(
        select(User)
        .options(selectinload(User.organization))
        .where(User.id == user_id_uuid)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Dependency to verify user is active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    return current_user


def require_role(*allowed_roles: UserRole):
    """
    Factory function to create a dependency that checks for specific roles.
    
    Usage:
        @app.get("/admin-only")
        async def admin_route(user: User = Depends(require_role(UserRole.ORG_ADMIN, UserRole.ORG_OWNER))):
            ...
    """
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {[r.value for r in allowed_roles]}",
            )
        return current_user
    return role_checker


async def get_org_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """Dependency to verify user is an organization admin or owner."""
    if current_user.role not in [UserRole.ORG_ADMIN, UserRole.ORG_OWNER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization admin access required",
        )
    return current_user


async def get_org_owner(
    current_user: User = Depends(get_current_user)
) -> User:
    """Dependency to verify user is the organization owner."""
    if current_user.role != UserRole.ORG_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization owner access required",
        )
    return current_user
