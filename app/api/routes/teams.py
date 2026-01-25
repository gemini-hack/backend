"""
Teams Router - API endpoints for team/department management.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from app.api.dependencies import CurrentUser, DbSession, require_permission, get_client_ip
from app.services.team_service import (
    TeamService,
    TeamNotFoundError,
    TeamAlreadyExistsError,
    InsufficientPermissionsError,
    MemberNotFoundError,
    PatientNotFoundError,
)
from app.schemas.teams import (
    TeamCreate,
    TeamUpdate,
    TeamResponse,
    TeamDetailResponse,
    TeamListResponse,
    AddMemberRequest,
    AssignPatientRequest,
    BulkAssignPatientsRequest,
)
from app.schemas.auth import InviteWorkerRequest
from app.services.user_service import UserService
from app.utils.responses import success_response, fail_response

router = APIRouter(prefix="/teams", tags=["Teams"])


# ============== Team CRUD ==============

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a team",
    description="Create a new team/department in the organization. Only organization owners can create teams.",
)
async def create_team(
    data: TeamCreate,
    user: CurrentUser,
    db: DbSession,
):
    """Create a new team in the organization."""
    service = TeamService(db)
    
    try:
        team = await service.create_team(user=user, data=data)
    except InsufficientPermissionsError as e:
        return fail_response(
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    except TeamAlreadyExistsError as e:
        return fail_response(
            status_code=status.HTTP_409_CONFLICT,
            message=str(e),
        )
    
    return success_response(
        status_code=status.HTTP_201_CREATED,
        message="Team created successfully",
        data=jsonable_encoder(TeamResponse(
            id=team.id,
            name=team.name,
            description=team.description,
            is_active=team.is_active,
            created_at=team.created_at,
            member_count=0,
            patient_count=0,
        )),
    )


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    summary="List teams",
    description="List all teams in the organization.",
)
async def list_teams(
    user: CurrentUser,
    db: DbSession,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=100, description="Pagination limit"),
):
    """List all teams in the organization."""
    service = TeamService(db)
    
    teams, total = await service.list_teams(
        organization_id=user.organization_id,
        is_active=is_active,
        skip=skip,
        limit=limit,
    )
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Teams retrieved successfully",
        data=jsonable_encoder(TeamListResponse(
            teams=teams,
            total=total,
            skip=skip,
            limit=limit,
        )),
    )


@router.get(
    "/{team_id}",
    status_code=status.HTTP_200_OK,
    summary="Get team details",
    description="Get detailed information about a team including members.",
)
async def get_team(
    team_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    """Get team details with members."""
    service = TeamService(db)
    
    try:
        team = await service.get_team(
            team_id=team_id,
            organization_id=user.organization_id,
            include_members=True,
        )
        members = await service.list_members(
            team_id=team_id,
            organization_id=user.organization_id,
        )
    except TeamNotFoundError:
        return fail_response(
            status_code=status.HTTP_404_NOT_FOUND,
            message=f"Team with ID {team_id} not found",
        )
    
    # Get counts
    from sqlalchemy import select, func
    from app.models.user import User
    from app.models.patient import Patient
    
    member_count_result = await db.execute(
        select(func.count()).where(User.team_id == team_id)
    )
    member_count = member_count_result.scalar() or 0
    
    patient_count_result = await db.execute(
        select(func.count()).where(Patient.team_id == team_id)
    )
    patient_count = patient_count_result.scalar() or 0
    
    response = TeamDetailResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        is_active=team.is_active,
        created_at=team.created_at,
        member_count=member_count,
        patient_count=patient_count,
        members=list(members),
    )
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Team retrieved successfully",
        data=jsonable_encoder(response),
    )


@router.patch(
    "/{team_id}",
    status_code=status.HTTP_200_OK,
    summary="Update team",
    description="Update team details. Only organization owners can update teams.",
)
async def update_team(
    team_id: UUID,
    data: TeamUpdate,
    user: CurrentUser,
    db: DbSession,
):
    """Update team details."""
    service = TeamService(db)
    
    try:
        team = await service.update_team(user=user, team_id=team_id, data=data)
    except InsufficientPermissionsError as e:
        return fail_response(
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    except TeamNotFoundError:
        return fail_response(
            status_code=status.HTTP_404_NOT_FOUND,
            message=f"Team with ID {team_id} not found",
        )
    except TeamAlreadyExistsError as e:
        return fail_response(
            status_code=status.HTTP_409_CONFLICT,
            message=str(e),
        )
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Team updated successfully",
        data=jsonable_encoder(TeamResponse(
            id=team.id,
            name=team.name,
            description=team.description,
            is_active=team.is_active,
            created_at=team.created_at,
            member_count=0,
            patient_count=0,
        )),
    )


@router.delete(
    "/{team_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete team",
    description="Delete (deactivate) a team. Only organization owners can delete teams.",
)
async def delete_team(
    team_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    """Delete team (soft delete)."""
    service = TeamService(db)
    
    try:
        await service.delete_team(user=user, team_id=team_id)
    except InsufficientPermissionsError as e:
        return fail_response(
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    except TeamNotFoundError:
        return fail_response(
            status_code=status.HTTP_404_NOT_FOUND,
            message=f"Team with ID {team_id} not found",
        )
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Team deleted successfully",
    )


# ============== Member Management ==============

@router.post(
    "/{team_id}/members",
    status_code=status.HTTP_201_CREATED,
    summary="Add member to team",
    description="Add a user to a team. Organization owners and admins can add members.",
)
async def add_member(
    team_id: UUID,
    data: AddMemberRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Add a member to the team."""
    service = TeamService(db)
    
    try:
        member = await service.add_member(
            user=user,
            team_id=team_id,
            email=data.email,
        )
    except InsufficientPermissionsError as e:
        return fail_response(
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    except TeamNotFoundError:
        return fail_response(
            status_code=status.HTTP_404_NOT_FOUND,
            message=f"Team with ID {team_id} not found",
        )
    except MemberNotFoundError as e:
        return fail_response(
            status_code=status.HTTP_404_NOT_FOUND,
            message=str(e),
        )
    
    return success_response(
        status_code=status.HTTP_201_CREATED,
        message="Member added to team successfully",
        data={
            "user_id": str(member.id),
            "team_id": str(team_id),
            "email": member.email,
            "full_name": member.full_name,
        },
    )


@router.delete(
    "/{team_id}/members/{user_id}",
    status_code=status.HTTP_200_OK,
    summary="Remove member from team",
    description="Remove a user from a team. Organization owners and admins can remove members.",
)
async def remove_member(
    team_id: UUID,
    user_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    """Remove a member from the team."""
    service = TeamService(db)
    
    try:
        member = await service.remove_member(
            user=user,
            team_id=team_id,
            member_user_id=user_id,
        )
    except InsufficientPermissionsError as e:
        return fail_response(
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    except MemberNotFoundError as e:
        return fail_response(
            status_code=status.HTTP_404_NOT_FOUND,
            message=str(e),
        )
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Member removed from team successfully",
        data={
            "user_id": str(member.id),
            "email": member.email,
        },
    )


@router.post(
    "/{team_id}/invitations",
    status_code=status.HTTP_201_CREATED,
    summary="Invite new worker to team",
    description="Invite a NEW worker via email and assign them to this team automatically upon acceptance. Organization owners and admins only.",
)
async def invite_worker_to_team(
    request: Request,
    team_id: UUID,
    data: InviteWorkerRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Invite a new worker directly to this team."""
    # Ensure team_id in URL matches body
    data.team_id = team_id
    
    # Verify team exists
    team_service = TeamService(db)
    await team_service.get_team(team_id, user.organization_id)

    # Use UserService to send invite
    user_service = UserService(db)
    
    # Check permissions (only admins/owners)
    if user.role not in ["org_owner", "org_admin"]:
         raise HTTPException(status_code=403, detail="Only admins can invite members")
    
    result = await user_service.invite_worker(
        inviter=user,
        data=data,
        ip_address=get_client_ip(request),
    )
    
    return success_response(
        status_code=status.HTTP_201_CREATED,
        message="Invitation sent successfully",
        data=jsonable_encoder(result),
    )



# ============== Patient Assignment ==============

@router.post(
    "/{team_id}/patients",
    status_code=status.HTTP_201_CREATED,
    summary="Assign patient to team",
    description="Assign a patient to a team. Admins, owners, or team members can assign patients.",
)
async def assign_patient(
    team_id: UUID,
    data: AssignPatientRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Assign a patient to the team."""
    service = TeamService(db)
    
    try:
        patient = await service.assign_patient(
            user=user,
            team_id=team_id,
            patient_id=data.patient_id,
        )
    except InsufficientPermissionsError as e:
        return fail_response(
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    except TeamNotFoundError:
        return fail_response(
            status_code=status.HTTP_404_NOT_FOUND,
            message=f"Team with ID {team_id} not found",
        )
    except PatientNotFoundError as e:
        return fail_response(
            status_code=status.HTTP_404_NOT_FOUND,
            message=str(e),
        )
    
    return success_response(
        status_code=status.HTTP_201_CREATED,
        message="Patient assigned to team successfully",
        data={
            "patient_id": str(patient.id),
            "patient_uid": patient.patient_uid,
            "team_id": str(team_id),
        },
    )


@router.post(
    "/{team_id}/patients/bulk",
    status_code=status.HTTP_200_OK,
    summary="Bulk assign patients to team",
    description="Assign multiple patients to a team. Organization owners and admins only.",
)
async def bulk_assign_patients(
    team_id: UUID,
    data: BulkAssignPatientsRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Bulk assign patients to the team."""
    service = TeamService(db)
    
    try:
        count = await service.bulk_assign_patients(
            user=user,
            team_id=team_id,
            patient_ids=data.patient_ids,
        )
    except InsufficientPermissionsError as e:
        return fail_response(
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    except TeamNotFoundError:
        return fail_response(
            status_code=status.HTTP_404_NOT_FOUND,
            message=f"Team with ID {team_id} not found",
        )
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message=f"{count} patients assigned to team successfully",
        data={
            "team_id": str(team_id),
            "patients_assigned": count,
        },
    )


@router.delete(
    "/{team_id}/patients/{patient_id}",
    status_code=status.HTTP_200_OK,
    summary="Unassign patient from team",
    description="Remove a patient from a team. Organization owners and admins only.",
)
async def unassign_patient(
    team_id: UUID,
    patient_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    """Unassign a patient from the team."""
    service = TeamService(db)
    
    try:
        patient = await service.unassign_patient(
            user=user,
            patient_id=patient_id,
        )
    except InsufficientPermissionsError as e:
        return fail_response(
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    except PatientNotFoundError as e:
        return fail_response(
            status_code=status.HTTP_404_NOT_FOUND,
            message=str(e),
        )
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Patient unassigned from team successfully",
        data={
            "patient_id": str(patient.id),
            "patient_uid": patient.patient_uid,
        },
    )
