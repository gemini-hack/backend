"""Authentication API routes."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Request, status
from fastapi.encoders import jsonable_encoder

from app.api.dependencies import (
    CurrentUser,
    DbSession,
    get_client_ip,
    get_user_agent,
)
from app.services.auth_service import AuthService
from app.services.password_service import PasswordService
from app.services.user_service import UserService
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    RefreshRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
    ResendVerificationRequest,
    AcceptInvitationRequest,
    UserProfileUpdate,
    UserWithOrgResponse,
)
from app.utils.responses import success_response, auth_response, fail_response


router = APIRouter(prefix="/auth", tags=["Authentication"])


# ============== Registration ==============

@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register organization and owner",
    description="Register a new organization along with its owner account.",
)
async def register(
    request: Request,
    data: RegisterRequest,
    db: DbSession,
):
    """Register a new organization and owner."""
    try:
        service = AuthService(db)
        result = await service.register_organization(
            data=data,
            ip_address=get_client_ip(request),
        )
        return success_response(
            status_code=status.HTTP_201_CREATED,
            message=result.message,
            data={
                "organization_id": str(result.organization_id),
                "user_id": str(result.user_id),
            },
        )
    except Exception as e:
        return fail_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )


# ============== Login / Logout ==============

@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    summary="Login",
    description="Authenticate with email and password.",
)
async def login(
    request: Request,
    data: LoginRequest,
    db: DbSession,
):
    """Login and get access tokens."""
    try:
        service = AuthService(db)
        result = await service.login(
            data=data,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        return auth_response(
            status_code=status.HTTP_200_OK,
            message="Login successful",
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            data={"user": jsonable_encoder(result.user)},
        )
    except Exception as e:
        return fail_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=str(e),
        )


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
    summary="Refresh access token",
)
async def refresh_token(
    request: Request,
    data: RefreshRequest,
    db: DbSession,
):
    """Refresh access token."""
    try:
        service = AuthService(db)
        result = await service.refresh_token(
            refresh_token=data.refresh_token,
            ip_address=get_client_ip(request),
        )
        
        # Determine refresh token to return
        next_refresh_token = getattr(result, "refresh_token", data.refresh_token) or data.refresh_token

        return auth_response(
            status_code=status.HTTP_200_OK,
            message="Token refreshed successfully",
            access_token=result.access_token,
            refresh_token=next_refresh_token,
            data=None,
        )
    except Exception as e:
        return fail_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=str(e),
        )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Logout",
)
async def logout(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    refresh_token: Optional[str] = Body(None, embed=True),
    logout_all: bool = Body(False, embed=True),
):
    """Logout user."""
    try:
        service = AuthService(db)
        await service.logout(
            user_id=user.id,
            refresh_token=refresh_token,
            logout_all=logout_all,
            ip_address=get_client_ip(request),
        )
        return success_response(
            status_code=status.HTTP_200_OK,
            message="Successfully logged out",
        )
    except Exception as e:
        return fail_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )


# ============== Password Management ==============

@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Change password",
)
async def change_password(
    request: Request,
    data: ChangePasswordRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Change user's password."""
    try:
        service = PasswordService(db)
        await service.change_password(
            user_id=user.id,
            current_password=data.current_password,
            new_password=data.new_password,
            ip_address=get_client_ip(request),
        )
        return success_response(
            status_code=status.HTTP_200_OK,
            message="Password changed successfully",
        )
    except Exception as e:
        return fail_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )


@router.post(
    "/forgot-password",
    status_code=status.HTTP_200_OK,
    summary="Request password reset",
)
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    db: DbSession,
):
    """Request password reset email."""
    try:
        service = PasswordService(db)
        await service.request_password_reset(
            email=data.email,
            ip_address=get_client_ip(request),
        )
        return success_response(
            status_code=status.HTTP_200_OK,
            message="If an account with this email exists, you will receive a password reset link",
        )
    except Exception as e:
        return fail_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )


@router.post(
    "/reset-password",
    status_code=status.HTTP_200_OK,
    summary="Reset password",
)
async def reset_password(
    request: Request,
    data: ResetPasswordRequest,
    db: DbSession,
):
    """Reset password using reset token."""
    try:
        service = PasswordService(db)
        await service.reset_password(
            token=data.token,
            new_password=data.new_password,
            ip_address=get_client_ip(request),
        )
        return success_response(
            status_code=status.HTTP_200_OK,
            message="Password reset successfully. Please login with your new password.",
        )
    except Exception as e:
        return fail_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )


# ============== Email Verification ==============

@router.get(
    "/verify",
    status_code=status.HTTP_200_OK,
    summary="Verify email",
)
async def verify_email(
    request: Request,
    db: DbSession,
    token: str,
):
    """Verify email address."""
    try:
        service = PasswordService(db)
        await service.verify_email(
            token=token,
            ip_address=get_client_ip(request),
        )
        return success_response(
            status_code=status.HTTP_200_OK,
            message="Email verified successfully",
        )
    except Exception as e:
        return fail_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )


@router.post(
    "/resend-verification",
    status_code=status.HTTP_200_OK,
    summary="Resend verification email",
)
async def resend_verification(
    request: Request,
    data: ResendVerificationRequest,
    db: DbSession,
):
    """Resend verification email."""
    try:
        service = PasswordService(db)
        await service.resend_verification_email(
            email=data.email,
            ip_address=get_client_ip(request),
        )
        return success_response(
            status_code=status.HTTP_200_OK,
            message="If an account with this email exists and is not verified, you will receive a verification link",
        )
    except Exception as e:
        return fail_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )


# ============== User Profile ==============

@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="Get current user",
)
async def get_current_user_profile(
    user: CurrentUser,
):
    """Get current user profile."""
    # We validate user in dependency, so user is present
    return success_response(
        status_code=status.HTTP_200_OK,
        message="User profile retrieved",
        data=jsonable_encoder(UserWithOrgResponse.model_validate(user)),
    )


@router.patch(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="Update profile",
)
async def update_profile(
    request: Request,
    data: UserProfileUpdate,
    user: CurrentUser,
    db: DbSession,
):
    """Update user profile."""
    try:
        service = UserService(db)
        updated_user = await service.update_user_profile(
            user_id=user.id,
            first_name=data.first_name,
            last_name=data.last_name,
            phone=data.phone,
            ip_address=get_client_ip(request),
        )
        return success_response(
            status_code=status.HTTP_200_OK,
            message="Profile updated successfully",
            data=jsonable_encoder(UserWithOrgResponse.model_validate(updated_user)),
        )
    except Exception as e:
        return fail_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )


# ============== Invitations (Public) ==============

@router.get(
    "/invite/{token}",
    status_code=status.HTTP_200_OK,
    summary="Get invitation details",
)
async def get_invitation_details(
    token: str,
    db: DbSession,
):
    """Get invitation details by token."""
    try:
        service = UserService(db)
        details = await service.get_invitation_details(token=token)
        return success_response(
            status_code=status.HTTP_200_OK,
            message="Invitation details retrieved",
            data=jsonable_encoder(details),
        )
    except Exception as e:
        return fail_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )


@router.post(
    "/accept-invite",
    status_code=status.HTTP_200_OK,
    summary="Accept invitation",
)
async def accept_invitation(
    request: Request,
    data: AcceptInvitationRequest,
    db: DbSession,
):
    """Accept invitation and create account."""
    try:
        service = UserService(db)
        result = await service.accept_invitation(
            token=data.token,
            password=data.password,
            ip_address=get_client_ip(request),
        )
        return auth_response(
            status_code=status.HTTP_200_OK,
            message="Invitation accepted and logged in",
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            data={"user": jsonable_encoder(result.user)},
        )
    except Exception as e:
        return fail_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )


# ============== Sessions ==============

@router.get(
    "/sessions",
    status_code=status.HTTP_200_OK,
    summary="List sessions",
)
async def list_sessions(
    user: CurrentUser,
    db: DbSession,
):
    """List user's active sessions."""
    try:
        service = UserService(db)
        sessions = await service.list_sessions(user_id=user.id)
        return success_response(
            status_code=status.HTTP_200_OK,
            message="Active sessions retrieved",
            data=jsonable_encoder(sessions),
        )
    except Exception as e:
        return fail_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_200_OK,
    summary="Revoke session",
)
async def revoke_session(
    request: Request,
    session_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    """Revoke a specific session."""
    try:
        service = UserService(db)
        await service.revoke_session(
            session_id=session_id,
            user_id=user.id,
            ip_address=get_client_ip(request),
        )
        return success_response(
            status_code=status.HTTP_200_OK,
            message="Session revoked successfully",
        )
    except Exception as e:
        return fail_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )
