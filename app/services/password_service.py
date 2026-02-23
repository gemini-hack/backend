from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID


from app.services.base import BaseService
from app.utils.security import hash_password, verify_password, generate_token
from app.utils.logger import logger
from app.utils.exceptions import (
    InvalidCredentialsException,
    TokenExpiredException,
    TokenInvalidException,
    NotFoundException,
)
from app.models.user import (
    User,
    RefreshToken,
    PasswordResetToken,
    EmailVerificationToken,
)
from app.tasks.email import send_verification_email_task, send_password_reset_email_task

class PasswordService(BaseService):
    """Password and email verification service."""
    
    async def change_password(
        self,
        user_id: UUID,
        current_password: str,
        new_password: str,
        ip_address: Optional[str] = None,
    ) -> None:
        """Change user's password."""
        
        user = await self.db.get(User, user_id)
        if not user:
            raise NotFoundException("User not found")
        
        # Verify current password
        if not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsException("Current password is incorrect")
        
        # Update password
        user.password_hash = hash_password(new_password)
        user.password_changed_at = datetime.now(timezone.utc)
        
        # Log audit
        await self._log_audit(
            user_id=user_id,
            organization_id=user.organization_id,
            action="password_change",
            resource_type="user",
            resource_id=str(user_id),
            ip_address=ip_address,
        )
        logger.info(f"Password changed for user: {user_id}")
        
        await self.db.commit()
    
    async def request_password_reset(
        self,
        email: str,
        ip_address: Optional[str] = None,
    ) -> None:
        """Request password reset - sends email with reset link."""
        
        user = await self._get_user_by_email(email)
        
        # Always return success to prevent email enumeration
        if not user:
            return
        
        # Invalidate existing unused tokens
        tokens = await (PasswordResetToken.query(self.db)
            .filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None)
            )
            .all())
        for token in tokens:
            token.used_at = datetime.now(timezone.utc)
        
        # Create new reset token
        reset_token = PasswordResetToken(
            user_id=user.id,
            token=generate_token(64),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        reset_token.add(self.db)
        
        # Log audit
        await self._log_audit(
            user_id=user.id,
            organization_id=user.organization_id,
            action="password_reset_request",
            resource_type="user",
            resource_id=str(user.id),
            ip_address=ip_address,
        )
        
        await self.db.commit()
        
        # Send password reset email
        send_password_reset_email_task.delay(
            to_email=email,
            reset_token=reset_token.token
        )
        
        logger.info(f"Password reset requested for: {email}")
    
    async def reset_password(
        self,
        token: str,
        new_password: str,
        ip_address: Optional[str] = None,
    ) -> None:
        """Reset password using reset token."""
        
        token_obj = await (PasswordResetToken.query(self.db)
            .with_relations("user")
            .filter(
                PasswordResetToken.token == token,
                PasswordResetToken.used_at.is_(None)
            )
            .one_or_none())
        
        if not token_obj:
            raise TokenInvalidException("Invalid or already used reset token")
        
        if token_obj.expires_at < datetime.now(timezone.utc):
            raise TokenExpiredException("Reset token has expired")
        
        user = token_obj.user
        
        # Update password
        user.password_hash = hash_password(new_password)
        user.password_changed_at = datetime.now(timezone.utc)
        
        # Mark token as used
        token_obj.used_at = datetime.now(timezone.utc)
        
        # Revoke all refresh tokens (force re-login)
        tokens = await (RefreshToken.query(self.db)
            .filter(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked_at.is_(None)
            )
            .all())
        for t in tokens:
            t.revoked_at = datetime.now(timezone.utc)
        
        # Log audit
        await self._log_audit(
            user_id=user.id,
            organization_id=user.organization_id,
            action="password_reset",
            resource_type="user",
            resource_id=str(user.id),
            ip_address=ip_address,
        )
        logger.info(f"Password reset completed for user: {user.id}")
        
        await self.db.commit()
    
    async def verify_email(
        self,
        token: str,
        ip_address: Optional[str] = None,
    ) -> None:
        """Verify user's email address."""
        
        token_obj = await (EmailVerificationToken.query(self.db)
            .with_relations("user")
            .filter(
                EmailVerificationToken.token == token,
                EmailVerificationToken.verified_at.is_(None)
            )
            .one_or_none())
        
        if not token_obj:
            raise TokenInvalidException("Invalid or already used verification token")
        
        if token_obj.expires_at < datetime.now(timezone.utc):
            raise TokenExpiredException("Verification token has expired")
        
        user = token_obj.user
        
        # Mark email as verified
        user.email_verified = True
        user.email_verified_at = datetime.now(timezone.utc)
        token_obj.verified_at = datetime.now(timezone.utc)
        
        # Log audit
        await self._log_audit(
            user_id=user.id,
            organization_id=user.organization_id,
            action="email_verified",
            resource_type="user",
            resource_id=str(user.id),
            ip_address=ip_address,
        )
        logger.info(f"Email verified for user: {user.id}")
        
        await self.db.commit()
    
    async def resend_verification_email(
        self,
        email: str,
        ip_address: Optional[str] = None,
    ) -> None:
        """Resend email verification."""
        
        user = await self._get_user_by_email(email)
        
        # Always return success to prevent email enumeration
        if not user or user.email_verified:
            return
        
        # Invalidate existing unused tokens
        tokens = await (EmailVerificationToken.query(self.db)
            .filter(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.verified_at.is_(None)
            )
            .all())
        for token in tokens:
            token.verified_at = datetime.now(timezone.utc)
        
        # Create new verification token
        verification_token = EmailVerificationToken(
            user_id=user.id,
            token=generate_token(64),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        verification_token.add(self.db)
        
        await self.db.commit()
        
        logger.info(f"Verification email resent for: {email}")
        # Send verification email
        send_verification_email_task.delay(
            to_email=user.email,
            token=verification_token.token
        )

