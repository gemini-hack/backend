from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.services.base import BaseService
from app.utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    generate_token,
)
from app.utils.logger import logger
from app.utils.exceptions import (
    InvalidCredentialsException,
    AccountLockedException,
    AccountInactiveException,
    EmailNotVerifiedException,
    TokenExpiredException,
    TokenInvalidException,
    UserAlreadyExistsException,
    OrganizationAlreadyExistsException,
)
from app.models.user import (
    User,
    Organization,
    RefreshToken,
    EmailVerificationToken,
    UserRole,
)
from app.schemas.auth import (
    RegisterRequest,
    RegisterResponse,
    LoginRequest,
    LoginResponse,
    RefreshResponse,
    UserWithOrgResponse,
)


class AuthService(BaseService):
    """Core authentication service."""
    
    async def register_organization(
        self,
        data: RegisterRequest,
        ip_address: Optional[str] = None,
    ) -> RegisterResponse:
        """Register a new organization with its owner."""
        
        existing_user = await self._get_user_by_email(data.owner_email)
        if existing_user:
            logger.warning(f"Registration failed: email already exists - {data.owner_email}")
            raise UserAlreadyExistsException()
        
        # Check if organization email already exists
        existing_org = await self._get_organization_by_email(data.owner_email)
        if existing_org:
            raise OrganizationAlreadyExistsException()
        
        # Create organization
        organization = Organization(
            name=data.organization_name,
            type=data.organization_type,
            email=data.owner_email,
            phone=data.phone,
            is_active=True,
            is_onboarded=False,
        )
        self.db.add(organization)
        await self.db.flush()
        
        # Create owner user
        user = User(
            email=data.owner_email,
            password_hash=hash_password(data.owner_password),
            first_name=data.owner_first_name,
            last_name=data.owner_last_name,
            phone=data.phone,
            role=UserRole.ORG_OWNER,
            organization_id=organization.id,
            is_active=True,
            email_verified=False,
        )
        self.db.add(user)
        await self.db.flush()
        
        # Create email verification token
        verification_token = EmailVerificationToken(
            user_id=user.id,
            token=generate_token(64),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        self.db.add(verification_token)
        
        # Log audit event
        await self._log_audit(
            user_id=user.id,
            organization_id=organization.id,
            action="registration",
            resource_type="organization",
            resource_id=str(organization.id),
            details={"organization_name": organization.name},
            ip_address=ip_address,
        )
        
        await self.db.commit()
        
        # TODO: Send verification email
        
        logger.info(f"Organization registered: {organization.name} (owner: {user.email})")
        
        return RegisterResponse(
            message="Registration successful. Please verify your email.",
            organization_id=organization.id,
            user_id=user.id,
        )
    
    async def login(
        self,
        data: LoginRequest,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> LoginResponse:
        """Authenticate user and return tokens."""
        
        user = await self._get_user_by_email(data.email, include_org=True)
        
        if not user:
            logger.warning(f"Login failed: user not found - {data.email}")
            raise InvalidCredentialsException()
        
        # Check if account is locked
        if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            if user.lockout_until and user.lockout_until > datetime.now(timezone.utc):
                raise AccountLockedException()
            else:
                user.failed_login_attempts = 0
                user.lockout_until = None
        
        # Verify password
        if not verify_password(data.password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
                user.lockout_until = datetime.now(timezone.utc) + timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)
            await self.db.commit()
            logger.warning(f"Login failed: invalid password - {data.email}")
            raise InvalidCredentialsException()
        
        # Check if user is active
        if not user.is_active:
            raise AccountInactiveException()
        
        # Check if organization is active
        if not user.organization.is_active:
            raise AccountInactiveException("Organization account is deactivated")
        
        # Check email verification
        if settings.REQUIRE_EMAIL_VERIFICATION and not user.email_verified:
            raise EmailNotVerifiedException()
        
        # Reset failed attempts on successful login
        user.failed_login_attempts = 0
        user.lockout_until = None
        user.last_login_at = datetime.now(timezone.utc)
        user.last_login_ip = ip_address
        
        # Generate tokens
        access_token = create_access_token(
            user_id=str(user.id),
            organization_id=str(user.organization_id),
            role=user.role.value,
        )
        
        # Pre-generate session UUID so we can include it in JWT
        import uuid as uuid_lib
        session_id = uuid_lib.uuid4()
        
        # Create JWT refresh token with session ID
        refresh_token_str = create_refresh_token(
            user_id=str(user.id),
            organization_id=str(user.organization_id),
            role=user.role.value,
            session_id=str(session_id),
        )
        
        # Store refresh token with pre-generated ID
        refresh_token_obj = RefreshToken(
            id=session_id,
            token=refresh_token_str,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            device_info=user_agent,
            ip_address=ip_address,
        )
        self.db.add(refresh_token_obj)
        
        # Log audit
        await self._log_audit(
            user_id=user.id,
            organization_id=user.organization_id,
            action="login",
            resource_type="session",
            details={"device": user_agent},
            ip_address=ip_address,
        )
        
        await self.db.commit()
        
        logger.info(f"User logged in: {user.email}")
        
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token_str,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserWithOrgResponse.model_validate(user),
        )
    
    async def refresh_token(
        self,
        refresh_token: str,
        ip_address: Optional[str] = None,
    ) -> RefreshResponse:
        """Refresh access token using refresh token."""
        
        result = await self.db.execute(
            select(RefreshToken)
            .options(selectinload(RefreshToken.user).selectinload(User.organization))
            .where(
                and_(
                    RefreshToken.token == refresh_token,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        )
        token_obj = result.scalar_one_or_none()
        
        if not token_obj:
            raise TokenInvalidException()
        
        # Check expiration
        if token_obj.expires_at < datetime.now(timezone.utc):
            token_obj.revoked_at = datetime.now(timezone.utc)
            await self.db.commit()
            raise TokenExpiredException()
        
        user = token_obj.user
        
        # Check if user/org is still active
        if not user.is_active or not user.organization.is_active:
            raise AccountInactiveException()
        
        # Update last used
        token_obj.last_used_at = datetime.now(timezone.utc)
        token_obj.ip_address = ip_address
        
        # Generate new access token
        access_token = create_access_token(
            user_id=str(user.id),
            organization_id=str(user.organization_id),
            role=user.role.value,
        )
        
        await self.db.commit()
        
        logger.info(f"Token refreshed for user: {user.id}")
        
        return RefreshResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
    
    async def logout(
        self,
        user_id: UUID,
        refresh_token: Optional[str] = None,
        logout_all: bool = False,
        ip_address: Optional[str] = None,
    ) -> None:
        """Logout user by revoking refresh token(s)."""
        
        if logout_all:
            result = await self.db.execute(
                select(RefreshToken).where(
                    and_(
                        RefreshToken.user_id == user_id,
                        RefreshToken.revoked_at.is_(None),
                    )
                )
            )
            tokens = result.scalars().all()
            for token in tokens:
                token.revoked_at = datetime.now(timezone.utc)
        elif refresh_token:
            result = await self.db.execute(
                select(RefreshToken).where(
                    and_(
                        RefreshToken.token == refresh_token,
                        RefreshToken.user_id == user_id,
                    )
                )
            )
            token_obj = result.scalar_one_or_none()
            if token_obj:
                token_obj.revoked_at = datetime.now(timezone.utc)
        
        # Get user for audit log
        user = await self.db.get(User, user_id)
        if user:
            await self._log_audit(
                user_id=user_id,
                organization_id=user.organization_id,
                action="logout",
                resource_type="session",
                details={"logout_all": logout_all},
                ip_address=ip_address,
            )
        logger.info(f"User logged out: {user_id} (all_sessions={logout_all})")
        
        await self.db.commit()
