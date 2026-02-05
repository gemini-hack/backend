from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.services.base import BaseService
from app.core.redis import SessionStore
from app.utils.security import hash_password, generate_token, create_access_token, create_refresh_token, get_token_hash
from app.utils.logger import logger
from app.utils.exceptions import (
    UserAlreadyExistsException,
    InvitationExpiredException,
    InvitationAlreadyUsedException,
    InvitationNotFoundException,
    NotFoundException,
)
from app.tasks.email import send_invitation_email_task
from app.models.user import (
    User,
    UserRole,
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
        existing_invitation = await (Invitation.query(self.db)
            .filter(
                Invitation.email == data.email,
                Invitation.organization_id == inviter.organization_id,
                Invitation.status == InvitationStatus.PENDING
            )
            .one_or_none())
        
        if existing_invitation:
            # Update existing invitation
            existing_invitation.first_name = data.first_name
            existing_invitation.last_name = data.last_name
            existing_invitation.role = data.role
            existing_invitation.team_id = data.team_id  # Update team assignment
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
                team_id=data.team_id,  # Include team assignment
                organization_id=inviter.organization_id,
                invited_by=inviter.id,
                token=generate_token(64),
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                status=InvitationStatus.PENDING,
            )
            invitation.add(self.db)
        
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
        
        # Send invitation email
        send_invitation_email_task.delay(
            to_email=invitation.email,
            inviter_name=f"{inviter.first_name} {inviter.last_name}".strip() or inviter.email,
            organization_name=inviter.organization.name,
            invitation_link=f"{settings.FRONTEND_URL}/accept-invite?token={invitation.token}",
            expires_at_str=invitation.expires_at.strftime('%Y-%m-%d %H:%M UTC')
        )
        
        logger.info(f"Invitation sent to {data.email} by {inviter.email}")
        
        # Build response with team name if applicable
        team_name = None
        if invitation.team_id:
            from app.models.user import Team
            team = await Team.fetch_by_id(self.db, invitation.team_id)
            if team:
                team_name = team.name
        
        return InvitationResponse(
            id=invitation.id,
            email=invitation.email,
            first_name=invitation.first_name,
            last_name=invitation.last_name,
            role=invitation.role,
            team_id=invitation.team_id,
            team_name=team_name,
            status=invitation.status.value,
            expires_at=invitation.expires_at,
            created_at=invitation.created_at,
        )
    
    async def get_invitation_details(self, token: str) -> InvitationDetailsResponse:
        """Get invitation details for the accept page."""
        
        invitation = await (Invitation.query(self.db)
            .with_relations("organization", "invited_by_user")
            .filter(Invitation.token == token)
            .one_or_none())
        
        if not invitation:
            raise InvitationNotFoundException()
        
        if invitation.status != InvitationStatus.PENDING:
            raise InvitationAlreadyUsedException()
        
        if invitation.expires_at < datetime.now(timezone.utc):
            raise InvitationExpiredException()
        
        # Get team name if applicable
        team_name = None
        if invitation.team_id:
            from app.models.user import Team
            team = await Team.fetch_by_id(self.db, invitation.team_id)
            if team:
                team_name = team.name
        
        return InvitationDetailsResponse(
            email=invitation.email,
            first_name=invitation.first_name,
            last_name=invitation.last_name,
            role=invitation.role,
            organization_name=invitation.organization.name,
            inviter_name=f"{invitation.invited_by_user.first_name} {invitation.invited_by_user.last_name}",
            team_id=invitation.team_id,
            team_name=team_name,
            expires_at=invitation.expires_at,
        )
    
    async def accept_invitation(
        self,
        token: str,
        password: str,
        ip_address: Optional[str] = None,
    ) -> LoginResponse:
        """Accept invitation and create user account."""
        
        invitation = await (Invitation.query(self.db)
            .with_relations("organization")
            .filter(Invitation.token == token)
            .one_or_none())
        
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
        
        # Create user with team assignment from invitation
        user = User(
            email=invitation.email,
            password_hash=hash_password(password),
            first_name=invitation.first_name or "",
            last_name=invitation.last_name or "",
            role=invitation.role,
            organization_id=invitation.organization_id,
            team_id=invitation.team_id,  # Assign to team from invitation
            is_active=True,
            email_verified=True,  # Email verified since they received invitation
        )
        await user.insert(self.db, commit=False, flush=True)
        
        # Update invitation status
        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = datetime.now(timezone.utc)
        
        await self.db.flush()
        
        # Generate session ID
        session_id = SessionStore.generate_session_id()
        
        access_token = create_access_token(
            user_id=str(user.id),
            organization_id=str(user.organization_id),
            role=user.role.value,
            session_id=str(session_id),
        )
        
        # Create JWT refresh token with session ID
        refresh_token_str = create_refresh_token(
            user_id=str(user.id),
            organization_id=str(user.organization_id),
            role=user.role.value,
            session_id=str(session_id),
        )
        
        # Store session in Redis
        await SessionStore.create(
            user_id=user.id,
            org_id=user.organization_id,
            session_id=session_id,
            token_hash=get_token_hash(refresh_token_str),
            ip_address=ip_address,
        )
        
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
        
        # Build responses with team names
        responses = []
        from app.models.user import Team
        
        for inv in invitations:
            team_name = None
            if inv.team_id:
                team = await Team.fetch_by_id(self.db, inv.team_id)
                if team:
                    team_name = team.name
            
            responses.append(InvitationResponse(
                id=inv.id,
                email=inv.email,
                first_name=inv.first_name,
                last_name=inv.last_name,
                role=inv.role,
                team_id=inv.team_id,
                team_name=team_name,
                status=inv.status.value,
                expires_at=inv.expires_at,
                created_at=inv.created_at,
            ))
        
        return responses
    
    async def revoke_invitation(
        self,
        invitation_id: UUID,
        organization_id: UUID,
        user_id: UUID,
        ip_address: Optional[str] = None,
    ) -> None:
        """Revoke a pending invitation."""
        
        invitation = await (Invitation.query(self.db)
            .filter(
                Invitation.id == invitation_id,
                Invitation.organization_id == organization_id,
                Invitation.status == InvitationStatus.PENDING
            )
            .one_or_none())
        
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
        current_session_id: Optional[UUID] = None,
    ) -> list[SessionResponse]:
        """List all active sessions for a user."""
        
        session_list = await SessionStore.list_all(user_id)
        
        sessions = []
        for session_id, data in session_list:
            try:
                session = SessionResponse(
                    id=session_id,
                    device_info=data.get("device_info"),
                    ip_address=data.get("ip_address"),
                    created_at=datetime.fromisoformat(data.get("created_at")),
                    last_used_at=datetime.fromisoformat(data.get("last_used_at")),
                    is_current=(current_session_id == session_id),
                )
                sessions.append(session)
            except (ValueError, KeyError):
                continue
        
        # Sort by last_used_at desc
        sessions.sort(key=lambda x: x.last_used_at, reverse=True)
        
        return sessions
    
    async def revoke_session(
        self,
        session_id: UUID,
        user_id: UUID,
        ip_address: Optional[str] = None,
    ) -> None:
        """Revoke a specific session."""
        
        deleted = await SessionStore.delete(user_id, session_id)
        
        if not deleted:
            raise NotFoundException("Session not found")
        
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

    async def list_workers(
        self,
        organization_id: UUID,
        search: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> dict:
        """
        List healthcare workers in an organization using QueryBuilder.
        """
        conditions = [User.organization_id == organization_id]
        
        if is_active is not None:
            conditions.append(User.is_active == is_active)
            
        if role:
            try:
                role_enum = UserRole(role)
                conditions.append(User.role == role_enum)
            except ValueError:
                pass
                
        if search:
            # User requested to search only by email since it's indexed
            search_term = f"%{search}%"
            conditions.append(User.email.ilike(search_term))
        
        # Use QueryBuilder
        base_query = User.query(self.db).filter(*conditions)
        
        total = await base_query.count()
        
        workers = await (
            base_query
            .order_by(User.last_name, User.first_name)
            .offset(skip)
            .limit(limit)
            .all()
        )
        
        return {
            "workers": workers,
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    async def update_worker_status(
        self, 
        worker_id: UUID, 
        organization_id: UUID, 
        is_active: bool,
        admin_id: UUID
    ) -> User:
        """Activate or deactivate a worker account."""
        query = select(User).where(
             and_(User.id == worker_id, User.organization_id == organization_id)
        )
        result = await self.db.execute(query)
        worker = result.scalar_one_or_none()
        
        if not worker:
            raise NotFoundException("Worker not found")
            
        worker.is_active = is_active
        
        # Log audit
        await self._log_audit(
            user_id=admin_id,
            organization_id=organization_id,
            action="worker_status_updated",
            resource_type="user",
            resource_id=str(worker_id),
            details={"is_active": is_active, "admin_id": str(admin_id)},
        )
        
        await self.db.commit()
        await self.db.refresh(worker)
        logger.info(f"Worker {worker.email} status updated to active={is_active} by admin {admin_id}")
        return worker

    async def list_workers_activity(self, organization_id: UUID) -> list[dict]:
        """
        Get activity stats for all workers in an organization.
        
        Aggregates data from AnalyticsService for each worker.
        """
        # Get all active workers
        workers = await User.query(self.db).filter(
            User.organization_id == organization_id,
            User.is_active == True
        ).all()
        
        from app.services.analytics_service import AnalyticsService
        analytics_service = AnalyticsService(self.db)
        
        activity_list = []
        for worker in workers:
            # Skip admins if they don't have clinical roles, unless desired
            # For now include everyone who is a worker
            
            stats = await analytics_service.get_worker_dashboard_stats(
                organization_id=organization_id,
                worker_id=worker.id,
                user_role=worker.role.value
            )
            
            # Determine online status simplistically (e.g., if last_login within 15 min)
            # For now, just return "offline" or "online" based on a heuristic if available, 
            # or default to "offline" if not tracked. 
            # Assuming 'is_active' implies account status, not presence.
            
            activity_list.append({
                "worker_id": str(worker.id),
                "name": f"{worker.first_name} {worker.last_name}",
                "role": worker.role.value,
                "email": worker.email,
                "caseload_size": stats.get("total_patients", 0),
                "active_alerts": stats.get("needs_attention", 0),
                "pending_actions": stats.get("pending_actions", 0),
                "resolved_today": stats.get("resolved_today", 0),
                # Add calculated efficiency or other metrics here
            })
            
        # Sort by caseload size descending
        activity_list.sort(key=lambda x: x["caseload_size"], reverse=True)
        
        return activity_list

    async def get_worker_activity(self, worker_id: UUID) -> dict:
        """Get activity stats for a single worker."""
        worker = await self.db.get(User, worker_id)
        if not worker:
            raise NotFoundException("Worker not found")
            
        from app.services.analytics_service import AnalyticsService
        analytics_service = AnalyticsService(self.db)
        
        stats = await analytics_service.get_worker_dashboard_stats(
            organization_id=worker.organization_id,
            worker_id=worker.id,
            user_role=worker.role.value
        )
        
        return {
            "worker_id": str(worker.id),
            "name": f"{worker.first_name} {worker.last_name}",
            "role": worker.role.value,
            "email": worker.email,
            "caseload_size": stats.get("total_patients", 0),
            "active_alerts": stats.get("needs_attention", 0),
            "pending_actions": stats.get("pending_actions", 0),
            "resolved_today": stats.get("resolved_today", 0),
        }
