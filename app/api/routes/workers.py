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
    "",
    status_code=status.HTTP_200_OK,
    summary="List workers",
    dependencies=[Depends(require_permission("users:read"))],
)
async def list_workers(
    user: CurrentUser,
    db: DbSession,
    search: Optional[str] = Query(None, description="Search by name or email"),
    role: Optional[str] = Query(None, description="Filter by role (nurse, doctor, coordinator, etc.)"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=100, description="Pagination limit"),
):
    """List all healthcare workers in the organization."""
    user_service = UserService(db)
    result = await user_service.list_workers(
        organization_id=user.organization_id,
        search=search,
        role=role,
        is_active=is_active,
        skip=skip,
        limit=limit,
    )
    
    result["workers"] = [UserResponse.model_validate(w) for w in result["workers"]]
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Workers retrieved successfully",
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
    invitation_status: Optional[InvitationStatus] = Query(None, alias="status"),
):
    """List organization invitations."""
    service = UserService(db)
    invitations = await service.list_invitations(
        organization_id=user.organization_id,
        status=invitation_status,
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


@router.get(
    "/{worker_id}/caseload",
    status_code=status.HTTP_200_OK,
    summary="Get worker caseload",
    dependencies=[Depends(require_permission("caseload:view"))],
)
async def get_worker_caseload(
    worker_id: str,
    user: CurrentUser,
    db: DbSession,
    search: Optional[str] = Query(None, description="Search by patient name or UID"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=100, description="Pagination limit"),
):
    """Get caseload for a specific worker (Admin/Coordinator only)."""
    try:
        w_uuid = uuid.UUID(worker_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid worker ID")

    user_service = UserService(db)
    target_worker = await user_service.get_user_by_id(w_uuid)

    if not target_worker or target_worker.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Worker not found")

    caseload_service = CaseloadService(db)
    result = await caseload_service.get_my_caseload(
        worker=target_worker,
        search=search,
        skip=skip,
        limit=limit,
    )
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Worker caseload retrieved successfully",
        data=jsonable_encoder(result),
    )


@router.patch(
    "/{worker_id}/status",
    status_code=status.HTTP_200_OK,
    summary="Update worker status",
    dependencies=[Depends(require_permission("workers:status"))],
)
async def update_worker_status(
    worker_id: str,
    is_active: bool,
    user: CurrentUser,
    db: DbSession,
):
    """Activate/deactivate a worker. Admin only."""
    try:
        w_uuid = uuid.UUID(worker_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid worker ID")

    user_service = UserService(db)
    worker = await user_service.update_worker_status(
        worker_id=w_uuid,
        organization_id=user.organization_id,
        is_active=is_active,
        admin_id=user.id,
    )
    return success_response(
        status_code=status.HTTP_200_OK,
        message=f"Worker {worker.email} status updated",
        data={"worker_id": str(worker.id), "is_active": worker.is_active},
    )
