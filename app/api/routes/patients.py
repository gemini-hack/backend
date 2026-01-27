import hashlib
import os
import uuid
from typing import Optional
from uuid import UUID
from app.db.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, UploadFile, File, BackgroundTasks
from fastapi.encoders import jsonable_encoder

from app.api.dependencies import (
    CurrentUser,
    DbSession,
    get_client_ip,
    require_permission,
)
from app.core.redis import RedisManager
from app.models.patient import PatientStatus
from app.models.conditions import Condition
from app.schemas.patient import PatientCreate, PatientResponse, PatientListResponse, PatientUpdate
from app.services.patient_service import PatientService
from app.services.storage_service import StorageService
from app.agents.context import AgentAction 
from app.schemas.agent import AgentActionResponse
from app.services.ingestion_service import IngestionService
from app.tasks.importer import process_patient_batch_import
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
    # Service now returns ORM object
    patient_orm = await service.create_patient(
        creator=user,
        data=data,
        ip_address=get_client_ip(request),
    )
    return success_response(
        status_code=status.HTTP_201_CREATED,
        message="Patient created successfully",
        data=jsonable_encoder(PatientResponse.model_validate(patient_orm)),
    )

@router.post("/ingest/document")
async def ingest_medical_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None
):
    """
    Upload a photo/PDF of a patient chart. 
    Gemini extracts the data and creates the patient.
    """
    if file.content_type not in ["image/jpeg", "image/png", "application/pdf"]:
        raise HTTPException(400, "Invalid file type. Use JPG, PNG, or PDF.")

    # 1. Read Bytes
    content = await file.read()
    
    # 2. AI Processing
    ingestor = IngestionService(db)
    patient_data = await ingestor.parse_document_to_patient(content, file.content_type)
    
    if not patient_data:
        raise HTTPException(422, "Could not extract valid patient data from document.")

    # 3. Save to DB
    service = PatientService(db)
    # Ensure UID is unique or generated
    if not patient_data.patient_uid:
        import uuid
        patient_data.patient_uid = str(uuid.uuid4())

    try:
        patient, is_created = await service.upsert_patient_from_ingestion(
            creator=current_user,
            data=patient_data,
            ip_address="doc_ingestion"
        )
        
        status_msg = "Patient created successfully" if is_created else "Patient updated successfully"
        status_code = status.HTTP_201_CREATED if is_created else status.HTTP_200_OK
        
        return success_response(
            status_code=status_code,
            message=status_msg,
            data={
                "patient": jsonable_encoder(PatientResponse.model_validate(patient)),
                "extracted_data": jsonable_encoder(patient_data),
                "action": "created" if is_created else "updated"
            }
        )
    except Exception as e:
        raise HTTPException(400, f"Failed to save extracted data: {str(e)}")

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

@router.get(
    "/{patient_id}/agent-actions",
    status_code=status.HTTP_200_OK,
    response_model=list[AgentActionResponse], # Use the list of your new Schema
    summary="Get agent actions for a patient",
    dependencies=[Depends(require_permission("patients:read"))],
)
async def get_patient_agent_actions(
    patient_id: UUID,
    user: CurrentUser,
    db: DbSession,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Retrieve a log of actions taken by the Agent for this patient.
    """
    patient = await Patient.fetch_unique(
        db, 
        id=patient_id, 
        organization_id=user.organization_id
    )
    if not patient:
        raise NotFoundException("Patient not found")

    stmt = (
        select(AgentAction)
        .where(AgentAction.patient_id == patient_id)
        .order_by(AgentAction.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    
    result = await db.execute(stmt)
    actions = result.scalars().all()

    return actions


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

    # Read file content for hashing
    content = await file.read()
    await file.seek(0)  # Reset file pointer for upload
    
    # Compute content hash
    content_hash = hashlib.sha256(content).hexdigest()
    
    # Check if this file was already uploaded (within last 24 hours)
    redis = RedisManager.get_client()
    cache_key = f"batch_upload:{user.organization_id}:{content_hash}"
    existing = await redis.get(cache_key)
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This file has already been uploaded. Please wait for processing to complete or upload a different file."
        )
    
    # Mark as uploaded (expires in 24 hours)
    await redis.setex(cache_key, 86400, "processing")

    # Generate unique key for storage
    file_ext = os.path.splitext(file.filename)[1]
    file_key = f"uploads/{user.organization_id}/{uuid.uuid4()}{file_ext}"

    # Upload to storage
    storage = StorageService()
    try:
        storage.upload_file(file, file_key)
    except Exception as e:
        # Clear the cache on upload failure
        await redis.delete(cache_key)
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
    
    stmt = (
        select(Patient)
        .options(
            # Load the specialized profiles to prevent "MissingGreenlet" error
            selectinload(Patient.hiv_profile),
            selectinload(Patient.hypertension_profile),
            selectinload(Patient.diabetes_profile),
            selectinload(Patient.scheduled_checks),
            selectinload(Patient.team),             # If you show team details
            selectinload(Patient.primary_provider)  # If you show doctor name
        )
        .where(
            Patient.id == patient_id,
            Patient.organization_id == user.organization_id
        )
    )
    
    result = await db.execute(stmt)
    patient = result.scalar_one_or_none()
    
    if not patient:
        raise NotFoundException("Patient not found")
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
