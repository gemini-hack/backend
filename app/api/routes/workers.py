"""Worker management API routes."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Query, Body, status
from fastapi.encoders import jsonable_encoder

from app.api.dependencies import (
    CurrentUser,
    DbSession,
    get_client_ip,
    require_permission,
)
from app.services.user_service import UserService
from app.schemas.auth import (
    InviteWorkerRequest,
)
from app.models.user import InvitationStatus
from app.utils.responses import success_response, fail_response


router = APIRouter(prefix="/workers", tags=["Workers"])


@router.post(
    "/invite",
    status_code=status.HTTP_201_CREATED,
    summary="Invite worker",
    dependencies=[Depends(require_permission("invitations:create"))],
)
async def invite_worker(
    request: Request,
    data: InviteWorkerRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Invite a worker to the organization."""
    service = UserService(db)
    result = await service.invite_worker(
        inviter=user,
        data=data,
        ip_address=get_client_ip(request),
    )
    return success_response(
        status_code=status.HTTP_201_CREATED,
        message="Invitation sent successfully",
        data=jsonable_encoder(result),
    )


@router.get(
    "/invitations",
    status_code=status.HTTP_200_OK,
    summary="List invitations",
    dependencies=[Depends(require_permission("invitations:read"))],
)
async def list_invitations(
    user: CurrentUser,
    db: DbSession,
    status: Optional[InvitationStatus] = Query(None),
):
    """List organization invitations."""
    service = UserService(db)
    invitations = await service.list_invitations(
        organization_id=user.organization_id,
        status=status,
    )
    return success_response(
        status_code=200,
        message="Invitations retrieved",
        data=jsonable_encoder(invitations),
    )


@router.delete(
    "/invitations/{invitation_id}",
    status_code=status.HTTP_200_OK,
    summary="Revoke invitation",
    dependencies=[Depends(require_permission("invitations:revoke"))],
)
async def revoke_invitation(
    request: Request,
    invitation_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    """Revoke a pending invitation."""
    service = UserService(db)
    await service.revoke_invitation(
        invitation_id=invitation_id,
        organization_id=user.organization_id,
        user_id=user.id,
        ip_address=get_client_ip(request),
    )
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Invitation revoked successfully",
    )
