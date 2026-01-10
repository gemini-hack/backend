from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.services.base import BaseService
from app.utils.security import hash_password, generate_token, create_access_token, create_refresh_token
from app.utils.logger import logger
from app.utils.exceptions import (
    UserAlreadyExistsException,
    InvitationExpiredException,
    InvitationAlreadyUsedException,
    InvitationNotFoundException,
    NotFoundException,
)
from app.models.user import (
    User,
    RefreshToken,
    Invitation,
    InvitationStatus,
)
from app.schemas.auth import (
    LoginResponse,
    UserWithOrgResponse,
    InviteWorkerRequest,
    InvitationResponse,
    InvitationDetailsResponse,
    SessionResponse,
)


class UserService(BaseService):
    """User management service."""
    
    # ============== Invitations ==============
    
    async def invite_worker(
        self,
        inviter: User,
        data: InviteWorkerRequest,
        ip_address: Optional[str] = None,
    ) -> InvitationResponse:
        """Invite a worker to join the organization."""
        
        # Check if email already exists as a user
        existing_user = await self._get_user_by_email(data.email)
        if existing_user:
            raise UserAlreadyExistsException("A user with this email already exists")
        
        # Check for pending invitation
        result = await self.db.execute(
            select(Invitation).where(
                and_(
                    Invitation.email == data.email,
                    Invitation.organization_id == inviter.organization_id,
                    Invitation.status == InvitationStatus.PENDING,
                )
            )
        )
        existing_invitation = result.scalar_one_or_none()
        
        if existing_invitation:
            # Update existing invitation
            existing_invitation.first_name = data.first_name
            existing_invitation.last_name = data.last_name
            existing_invitation.role = data.role
            existing_invitation.token = generate_token(64)
            existing_invitation.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
            existing_invitation.invited_by = inviter.id
            invitation = existing_invitation
        else:
            # Create new invitation
            invitation = Invitation(
                email=data.email,
                first_name=data.first_name,
                last_name=data.last_name,
                role=data.role,
                organization_id=inviter.organization_id,
                invited_by=inviter.id,
                token=generate_token(64),
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                status=InvitationStatus.PENDING,
            )
            self.db.add(invitation)
        
        # Log audit
        await self._log_audit(
            user_id=inviter.id,
            organization_id=inviter.organization_id,
            action="invitation_sent",
            resource_type="invitation",
            details={"email": data.email, "role": data.role.value},
            ip_address=ip_address,
        )
        
        await self.db.commit()
        await self.db.refresh(invitation)
        
        # TODO: Send invitation email
        
        logger.info(f"Invitation sent to {data.email} by {inviter.email}")
        
        return InvitationResponse.model_validate(invitation)
    
    async def get_invitation_details(self, token: str) -> InvitationDetailsResponse:
        """Get invitation details for the accept page."""
        
        result = await self.db.execute(
            select(Invitation)
            .options(
                selectinload(Invitation.organization),
                selectinload(Invitation.invited_by_user),
            )
            .where(Invitation.token == token)
        )
        invitation = result.scalar_one_or_none()
        
        if not invitation:
            raise InvitationNotFoundException()
        
        if invitation.status != InvitationStatus.PENDING:
            raise InvitationAlreadyUsedException()
        
        if invitation.expires_at < datetime.now(timezone.utc):
            raise InvitationExpiredException()
        
        return InvitationDetailsResponse(
            email=invitation.email,
            first_name=invitation.first_name,
            last_name=invitation.last_name,
            role=invitation.role,
            organization_name=invitation.organization.name,
            inviter_name=f"{invitation.invited_by_user.first_name} {invitation.invited_by_user.last_name}",
            expires_at=invitation.expires_at,
        )
    
    async def accept_invitation(
        self,
        token: str,
        password: str,
        ip_address: Optional[str] = None,
    ) -> LoginResponse:
        """Accept invitation and create user account."""
        
        result = await self.db.execute(
            select(Invitation)
            .options(selectinload(Invitation.organization))
            .where(Invitation.token == token)
        )
        invitation = result.scalar_one_or_none()
        
        if not invitation:
            raise InvitationNotFoundException()
        
        if invitation.status != InvitationStatus.PENDING:
            raise InvitationAlreadyUsedException()
        
        if invitation.expires_at < datetime.now(timezone.utc):
            invitation.status = InvitationStatus.EXPIRED
            await self.db.commit()
            raise InvitationExpiredException()
        
        # Check if email is taken (race condition protection)
        existing_user = await self._get_user_by_email(invitation.email)
        if existing_user:
            invitation.status = InvitationStatus.ACCEPTED
            await self.db.commit()
            raise UserAlreadyExistsException("A user with this email already exists")
        
        # Create user
        user = User(
            email=invitation.email,
            password_hash=hash_password(password),
            first_name=invitation.first_name or "",
            last_name=invitation.last_name or "",
            role=invitation.role,
            organization_id=invitation.organization_id,
            is_active=True,
            email_verified=True,  # Email verified since they received invitation
        )
        self.db.add(user)
        
        # Update invitation status
        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = datetime.now(timezone.utc)
        
        await self.db.flush()
        
        access_token = create_access_token(
            user_id=str(user.id),
            organization_id=str(user.organization_id),
            role=user.role.value,
        )
        
        # Pre-generate session UUID
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
            ip_address=ip_address,
        )
        self.db.add(refresh_token_obj)
        
        # Log audit
        await self._log_audit(
            user_id=user.id,
            organization_id=user.organization_id,
            action="invitation_accepted",
            resource_type="user",
            resource_id=str(user.id),
            details={"invitation_id": str(invitation.id)},
            ip_address=ip_address,
        )
        
        await self.db.commit()
        await self.db.refresh(user, ["organization"])
        
        logger.info(f"Invitation accepted: {invitation.email} joined {invitation.organization.name}")
        
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token_str,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserWithOrgResponse.model_validate(user),
        )
    
    async def list_invitations(
        self,
        organization_id: UUID,
        status: Optional[InvitationStatus] = None,
    ) -> list[InvitationResponse]:
        """List all invitations for an organization."""
        
        query = select(Invitation).where(Invitation.organization_id == organization_id)
        
        if status:
            query = query.where(Invitation.status == status)
        
        query = query.order_by(Invitation.created_at.desc())
        
        result = await self.db.execute(query)
        invitations = result.scalars().all()
        
        return [InvitationResponse.model_validate(inv) for inv in invitations]
    
    async def revoke_invitation(
        self,
        invitation_id: UUID,
        organization_id: UUID,
        user_id: UUID,
        ip_address: Optional[str] = None,
    ) -> None:
        """Revoke a pending invitation."""
        
        result = await self.db.execute(
            select(Invitation).where(
                and_(
                    Invitation.id == invitation_id,
                    Invitation.organization_id == organization_id,
                    Invitation.status == InvitationStatus.PENDING,
                )
            )
        )
        invitation = result.scalar_one_or_none()
        
        if not invitation:
            raise InvitationNotFoundException()
        
        invitation.status = InvitationStatus.REVOKED
        
        # Log audit
        await self._log_audit(
            user_id=user_id,
            organization_id=organization_id,
            action="invitation_revoked",
            resource_type="invitation",
            resource_id=str(invitation_id),
            details={"email": invitation.email},
            ip_address=ip_address,
        )
        
        await self.db.commit()
        
        logger.info(f"Invitation revoked: {invitation.email}")
    
    # ============== Sessions ==============
    
    async def list_sessions(
        self,
        user_id: UUID,
        current_token: Optional[str] = None,
    ) -> list[SessionResponse]:
        """List all active sessions for a user."""
        
        result = await self.db.execute(
            select(RefreshToken).where(
                and_(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                    RefreshToken.expires_at > datetime.now(timezone.utc),
                )
            ).order_by(RefreshToken.created_at.desc())
        )
        tokens = result.scalars().all()
        
        sessions = []
        for token in tokens:
            session = SessionResponse.model_validate(token)
            if current_token and token.token == current_token:
                session.is_current = True
            sessions.append(session)
        
        return sessions
    
    async def revoke_session(
        self,
        session_id: UUID,
        user_id: UUID,
        ip_address: Optional[str] = None,
    ) -> None:
        """Revoke a specific session."""
        
        result = await self.db.execute(
            select(RefreshToken).where(
                and_(
                    RefreshToken.id == session_id,
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        )
        token = result.scalar_one_or_none()
        
        if not token:
            raise NotFoundException("Session not found")
        
        token.revoked_at = datetime.now(timezone.utc)
        
        # Get user for audit
        user = await self.db.get(User, user_id)
        if user:
            await self._log_audit(
                user_id=user_id,
                organization_id=user.organization_id,
                action="session_revoked",
                resource_type="session",
                resource_id=str(session_id),
                ip_address=ip_address,
            )
        
        await self.db.commit()
        
        logger.info(f"Session revoked: {session_id} for user {user_id}")
    
    # ============== User Profile ==============
    
    async def get_user_by_id(
        self,
        user_id: UUID,
        include_org: bool = False,
    ) -> Optional[User]:
        """Get user by ID."""
        
        query = select(User).where(User.id == user_id)
        if include_org:
            query = query.options(selectinload(User.organization))
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def update_user_profile(
        self,
        user_id: UUID,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        phone: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> User:
        """Update user profile."""
        
        user = await self.db.get(User, user_id)
        if not user:
            raise NotFoundException("User not found")
        
        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name
        if phone is not None:
            user.phone = phone
        
        # Log audit
        await self._log_audit(
            user_id=user_id,
            organization_id=user.organization_id,
            action="profile_updated",
            resource_type="user",
            resource_id=str(user_id),
            ip_address=ip_address,
        )
        
        await self.db.commit()
        await self.db.refresh(user, ["organization"])
        
        logger.info(f"Profile updated for user: {user_id}")
        
        return user
