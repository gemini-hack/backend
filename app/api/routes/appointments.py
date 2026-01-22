"""
Appointments API Routes.

CRUD operations for appointments plus scheduling and status management.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload

from app.api.dependencies import CurrentUser, DbSession, require_permission
from app.models.appointment import Appointment, AppointmentStatus
from app.models.patient import Patient
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentUpdate,
    AppointmentResponse,
    AppointmentListResponse,
)
from app.utils.responses import success_response
from app.utils.exceptions import NotFoundException, BadRequestException
from app.utils.logger import logger


router = APIRouter(prefix="/appointments", tags=["Appointments"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=AppointmentResponse,
    summary="Create appointment",
    dependencies=[Depends(require_permission("appointments:create"))],
)
async def create_appointment(
    data: AppointmentCreate,
    user: CurrentUser,
    db: DbSession,
):
    """
    Create a new appointment.
    
    Complexity: O(1) - single insert
    """
    # Verify patient exists and belongs to organization
    patient = await Patient.fetch_unique(
        db,
        id=data.patient_id,
        organization_id=user.organization_id
    )
    if not patient:
        raise NotFoundException("Patient not found")
    
    # Create appointment
    appointment = Appointment(
        patient_id=data.patient_id,
        organization_id=user.organization_id,
        provider_id=data.provider_id,
        scheduled_time=data.scheduled_time,
        type=data.type,
        notes=data.notes,
        status=AppointmentStatus.SCHEDULED,
    )
    await appointment.insert(db)
    
    logger.info(f"Appointment created: {appointment.id} for patient {patient.id}")
    
    return success_response(
        status_code=status.HTTP_201_CREATED,
        message="Appointment created successfully",
        data=jsonable_encoder(AppointmentResponse.model_validate(appointment)),
    )


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=AppointmentListResponse,
    summary="List appointments",
    dependencies=[Depends(require_permission("appointments:read"))],
)
async def list_appointments(
    user: CurrentUser,
    db: DbSession,
    patient_id: Optional[UUID] = Query(None, description="Filter by patient"),
    appt_status: Optional[AppointmentStatus] = Query(None, alias="status", description="Filter by status"),
    from_date: Optional[datetime] = Query(None, description="Filter from date"),
    to_date: Optional[datetime] = Query(None, description="Filter to date"),
    priority_min: Optional[int] = Query(None, description="Minimum priority level"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=100, description="Pagination limit"),
):
    """
    List appointments with filtering.
    
    Complexity: O(n) where n = matching appointments (limited to 100)
    """
    conditions = [Appointment.organization_id == user.organization_id]
    
    if patient_id:
        conditions.append(Appointment.patient_id == patient_id)
    if appt_status:
        conditions.append(Appointment.status == appt_status)
    if from_date:
        conditions.append(Appointment.scheduled_time >= from_date)
    if to_date:
        conditions.append(Appointment.scheduled_time <= to_date)
    if priority_min is not None:
        conditions.append(Appointment.priority_level >= priority_min)
    
    # Count total
    total = await Appointment.query(db).filter(*conditions).count()
    
    # Fetch with pagination
    appointments = await (
        Appointment.query(db)
        .filter(*conditions)
        .order_by(Appointment.scheduled_time, desc=False)
        .offset(skip)
        .limit(limit)
        .all()
    )
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Appointments retrieved successfully",
        data=jsonable_encoder(AppointmentListResponse(
            appointments=[AppointmentResponse.model_validate(a) for a in appointments],
            total=total,
            skip=skip,
            limit=limit,
        )),
    )


@router.get(
    "/{appointment_id}",
    status_code=status.HTTP_200_OK,
    summary="Get appointment",
    dependencies=[Depends(require_permission("appointments:read"))],
)
async def get_appointment(
    appointment_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    """Get a single appointment by ID."""
    appointment = await Appointment.fetch_one_with(
        db,
        "patient",
        "reminders",
        id=appointment_id,
        organization_id=user.organization_id
    )
    
    if not appointment:
        raise NotFoundException("Appointment not found")
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Appointment retrieved successfully",
        data=jsonable_encoder(AppointmentResponse.model_validate(appointment)),
    )


@router.patch(
    "/{appointment_id}",
    status_code=status.HTTP_200_OK,
    summary="Update appointment",
    dependencies=[Depends(require_permission("appointments:update"))],
)
async def update_appointment(
    appointment_id: UUID,
    data: AppointmentUpdate,
    user: CurrentUser,
    db: DbSession,
):
    """Update an appointment."""
    appointment = await Appointment.fetch_unique(
        db,
        id=appointment_id,
        organization_id=user.organization_id
    )
    
    if not appointment:
        raise NotFoundException("Appointment not found")
    
    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if hasattr(appointment, field):
            setattr(appointment, field, value)
    
    await appointment.save(db)
    
    logger.info(f"Appointment {appointment_id} updated")
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Appointment updated successfully",
        data=jsonable_encoder(AppointmentResponse.model_validate(appointment)),
    )


@router.post(
    "/{appointment_id}/mark-no-show",
    status_code=status.HTTP_200_OK,
    summary="Mark as no-show",
    dependencies=[Depends(require_permission("appointments:update"))],
)
async def mark_no_show(
    appointment_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    """
    Mark an appointment as no-show and escalate priority on future appointments.
    
    This:
    1. Sets status to NO_SHOW
    2. Increments no_show_count
    3. Bumps priority_level on future scheduled appointments for the same patient
    """
    appointment = await Appointment.fetch_one_with(
        db,
        "patient",
        id=appointment_id,
        organization_id=user.organization_id
    )
    
    if not appointment:
        raise NotFoundException("Appointment not found")
    
    if appointment.status != AppointmentStatus.SCHEDULED:
        raise BadRequestException(f"Cannot mark {appointment.status.value} appointment as no-show")
    
    # Mark as no-show
    appointment.status = AppointmentStatus.NO_SHOW
    appointment.no_show_count += 1
    await appointment.save(db, commit=False)
    
    # Bump priority on future appointments
    now = datetime.now(timezone.utc)
    future_appts = await (
        Appointment.query(db)
        .filter(
            Appointment.patient_id == appointment.patient_id,
            Appointment.status == AppointmentStatus.SCHEDULED,
            Appointment.scheduled_time > now,
        )
        .all()
    )
    
    for future_appt in future_appts:
        future_appt.priority_level = max(future_appt.priority_level, 2)
        await future_appt.save(db, commit=False)
    
    await db.commit()
    
    logger.info(f"Appointment {appointment_id} marked as no-show, updated {len(future_appts)} future appointments")
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Appointment marked as no-show",
        data={
            "no_show_count": appointment.no_show_count,
            "future_appointments_escalated": len(future_appts)
        },
    )


@router.post(
    "/{appointment_id}/complete",
    status_code=status.HTTP_200_OK,
    summary="Mark as completed",
    dependencies=[Depends(require_permission("appointments:update"))],
)
async def mark_completed(
    appointment_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    """Mark an appointment as completed."""
    appointment = await Appointment.fetch_unique(
        db,
        id=appointment_id,
        organization_id=user.organization_id
    )
    
    if not appointment:
        raise NotFoundException("Appointment not found")
    
    if appointment.status != AppointmentStatus.SCHEDULED:
        raise BadRequestException(f"Cannot complete {appointment.status.value} appointment")
    
    appointment.status = AppointmentStatus.COMPLETED
    await appointment.save(db)
    
    logger.info(f"Appointment {appointment_id} marked as completed")
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Appointment completed",
        data=jsonable_encoder(AppointmentResponse.model_validate(appointment)),
    )


@router.delete(
    "/{appointment_id}",
    status_code=status.HTTP_200_OK,
    summary="Cancel appointment",
    dependencies=[Depends(require_permission("appointments:delete"))],
)
async def cancel_appointment(
    appointment_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    """Cancel an appointment (soft delete - sets status to CANCELLED)."""
    appointment = await Appointment.fetch_unique(
        db,
        id=appointment_id,
        organization_id=user.organization_id
    )
    
    if not appointment:
        raise NotFoundException("Appointment not found")
    
    if appointment.status != AppointmentStatus.SCHEDULED:
        raise BadRequestException(f"Cannot cancel {appointment.status.value} appointment")
    
    appointment.status = AppointmentStatus.CANCELLED
    await appointment.save(db)
    
    logger.info(f"Appointment {appointment_id} cancelled")
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Appointment cancelled",
    )
