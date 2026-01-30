import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder

from app.api.dependencies import CurrentUser, DbSession, require_permission
from app.models.patient import PatientStatus
from app.models.conditions import Condition
from app.services.caseload_service import CaseloadService
from app.utils.responses import success_response

router = APIRouter(prefix="/caseload", tags=["Caseload"])


@router.get(
    "/my",
    status_code=status.HTTP_200_OK,
    summary="Get my caseload",
    dependencies=[Depends(require_permission("patients:read"))],
)
async def get_my_caseload(
    user: CurrentUser,
    db: DbSession,
    search: Optional[str] = Query(None, description="Search by patient name or UID"),
    condition: Optional[Condition] = Query(None, description="Filter by primary condition"),
    patient_status: Optional[PatientStatus] = Query(None, alias="status", description="Filter by patient status"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=100, description="Pagination limit"),
):
    """Get prioritized list of patients assigned to the current worker."""
    service = CaseloadService(db)
    result = await service.get_my_caseload(
        worker=user,
        search=search,
        condition=condition,
        status=patient_status,
        skip=skip,
        limit=limit,
    )
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Caseload retrieved successfully",
        data=jsonable_encoder(result),
    )


@router.get(
    "/unassigned",
    status_code=status.HTTP_200_OK,
    summary="Get unassigned patients",
    dependencies=[Depends(require_permission("patients:read"))],
)
async def get_unassigned_patients(
    user: CurrentUser,
    db: DbSession,
    search: Optional[str] = Query(None, description="Search by patient name or UID"),
    condition: Optional[Condition] = Query(None, description="Filter by primary condition"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=100, description="Pagination limit"),
):
    """Get list of active patients with no assigned nurse."""
    service = CaseloadService(db)
    result = await service.get_unassigned_patients(
        organization_id=user.organization_id,
        search=search,
        condition=condition,
        skip=skip,
        limit=limit,
    )
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Unassigned patients retrieved successfully",
        data=jsonable_encoder(result),
    )


@router.post(
    "/assign",
    status_code=status.HTTP_200_OK,
    summary="Assign patient to worker",
    dependencies=[Depends(require_permission("caseload:assign"))],
)
async def assign_patient(
    patient_uid: str,
    worker_id: str,
    user: CurrentUser,
    db: DbSession,
):
    """Assign a patient to a worker (Admin/Coordinator only)."""
    try:
        worker_uuid = uuid.UUID(worker_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid worker ID format")

    service = CaseloadService(db)
    patient = await service.assign_patient(
        patient_uid=patient_uid,
        worker_id=worker_uuid,
        organization_id=user.organization_id,
    )
    return success_response(
        status_code=status.HTTP_200_OK,
        message=f"Patient {patient.first_name} assigned successfully",
        data={
            "patient_uid": patient.patient_uid,
            "primary_physician_id": str(patient.primary_physician_id) if patient.primary_physician_id else None,
            "assigned_nurse_id": str(patient.assigned_nurse_id) if patient.assigned_nurse_id else None,
            "care_coordinator_id": str(patient.care_coordinator_id) if patient.care_coordinator_id else None,
        },
    )


@router.post(
    "/reassign",
    status_code=status.HTTP_200_OK,
    summary="Reassign patient to a different worker",
    dependencies=[Depends(require_permission("caseload:assign"))],
)
async def reassign_patient(
    patient_uid: str,
    new_worker_id: str,
    user: CurrentUser,
    db: DbSession,
):
    """
    Reassign a patient from their current care team member to a new one.
    
    The new worker's role determines which slot (physician, nurse, coordinator) is updated.
    This endpoint is useful for workload balancing and staff changes.
    """
    try:
        worker_uuid = uuid.UUID(new_worker_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid worker ID format")

    service = CaseloadService(db)
    result = await service.reassign_patient(
        patient_uid=patient_uid,
        new_worker_id=worker_uuid,
        organization_id=user.organization_id,
    )
    return success_response(
        status_code=status.HTTP_200_OK,
        message=f"Patient reassigned from {result['previous_worker'] or 'nobody'} to {result['new_worker']}",
        data=result,
    )
