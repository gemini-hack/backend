from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.encoders import jsonable_encoder

from app.api.dependencies import (
    CurrentUser,
    DbSession,
    get_client_ip,
    require_permission,
)
from app.models.patient import PatientStatus
from app.schemas.patient import PatientCreate, PatientResponse, PatientListResponse
from app.services.patient_service import PatientService
from app.utils.responses import success_response

router = APIRouter(prefix="/patients", tags=["Patients"])

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=PatientResponse,
    summary="Create patient",
    dependencies=[Depends(require_permission("patients:create"))],
)
async def create_patient(
    request: Request,
    data: PatientCreate,
    user: CurrentUser,
    db: DbSession,
):
    """Create a new patient record."""
    service = PatientService(db)
    result = await service.create_patient(
        creator=user,
        data=data,
        ip_address=get_client_ip(request),
    )
    return success_response(
        status_code=status.HTTP_201_CREATED,
        message="Patient created successfully",
        data=jsonable_encoder(result),
    )

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=PatientListResponse,
    summary="List patients",
    dependencies=[Depends(require_permission("patients:read"))],
)
async def list_patients(
    user: CurrentUser,
    db: DbSession,
    patient_status: Optional[PatientStatus] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
):
    """List patients for the organization."""
    service = PatientService(db)
    result = await service.get_patients(
        organization_id=user.organization_id,
        status=patient_status,
        skip=skip,
        limit=limit,
    )
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Patients retrieved successfully",
        data=jsonable_encoder(result),
    )
