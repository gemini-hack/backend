from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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
from app.services.storage_service import StorageService
from app.utils.responses import success_response
from app.tasks.importer import process_patient_batch_import
from fastapi import UploadFile, File, BackgroundTasks
import uuid
import os

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
    patient_status: Optional[PatientStatus] = Query(None, alias="status", description="Filter by patient status"),
    condition: Optional[Condition] = Query(None, description="Filter by primary condition"),
    search: Optional[str] = Query(None, description="Search by patient name or UID"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=100, description="Pagination limit"),
):
    """List patients for the organization."""
    service = PatientService(db)
    result = await service.get_patients(
        organization_id=user.organization_id,
        status=patient_status,
        condition=condition,
        search=search,
        skip=skip,
        limit=limit,
    )
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Patients retrieved successfully",
        data=jsonable_encoder(result),
    )


@router.post(
    "/batch-upload",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Batch upload patients via CSV",
    dependencies=[Depends(require_permission("patients:create"))],
)
async def batch_upload_patients(
    user: CurrentUser,
    file: UploadFile = File(...),
):
    """Upload a CSV file containing patient data for background processing."""
    if not file.filename.endswith('.csv'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV files are allowed"
        )

    # Generate unique key for storage
    file_ext = os.path.splitext(file.filename)[1]
    file_key = f"uploads/{user.organization_id}/{uuid.uuid4()}{file_ext}"

    # Upload to storage
    storage = StorageService()
    try:
        storage.upload_file(file, file_key)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Failed to upload file: {str(e)}"
        )
    
    # Trigger Celery task
    process_patient_batch_import.delay(
        file_key=file_key,
        organization_id=str(user.organization_id),
        user_id=str(user.id)
    )

    return success_response(
        status_code=status.HTTP_202_ACCEPTED,
        message="File uploaded successfully. Processing started in background.",
        data={"file_key": file_key}
    )


@router.get(
    "/{patient_id}",
    status_code=status.HTTP_200_OK,
    summary="Get patient",
    dependencies=[Depends(require_permission("patients:read"))],
)
async def get_patient(
    patient_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    """Get a patient by ID."""
    from app.schemas.patient import PatientDetailResponse
    
    service = PatientService(db)
    patient = await service.get_patient_by_id(
        patient_id=patient_id,
        organization_id=user.organization_id,
    )
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Patient retrieved successfully",
        data=jsonable_encoder(PatientDetailResponse.model_validate(patient)),
    )


@router.patch(
    "/{patient_id}",
    status_code=status.HTTP_200_OK,
    summary="Update patient",
    dependencies=[Depends(require_permission("patients:update"))],
)
async def update_patient(
    patient_id: UUID,
    data: PatientUpdate,
    user: CurrentUser,
    db: DbSession,
):
    """Update a patient record."""
    service = PatientService(db)
    patient = await service.update_patient(
        patient_id=patient_id,
        organization_id=user.organization_id,
        data=data.model_dump(exclude_unset=True),
    )
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Patient updated successfully",
        data=jsonable_encoder(PatientResponse.model_validate(patient)),
    )


@router.delete(
    "/{patient_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete patient",
    dependencies=[Depends(require_permission("patients:delete"))],
)
async def delete_patient(
    patient_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    """Soft delete a patient (sets status to INACTIVE)."""
    service = PatientService(db)
    await service.delete_patient(
        patient_id=patient_id,
        organization_id=user.organization_id,
    )
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Patient deleted successfully",
    )
