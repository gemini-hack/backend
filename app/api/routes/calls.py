import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.dependencies import CurrentUser, DbSession
from app.models import Patient, CallSession, CallType, CallStatus
from app.services.livekit_sip_service import LiveKitSIPService
from app.tasks.outbound_calls import trigger_patient_call
from app.core.config import settings
from app.utils.responses import success_response
from app.utils.logger import logger

router = APIRouter(prefix="/calls", tags=["Calls"])


class InitiateCallRequest(BaseModel):
    """Request to initiate an outbound call."""
    patient_id: str
    call_type: str = "outbound_manual"


class CallSessionResponse(BaseModel):
    """Response for a call session."""
    id: str
    room_name: str
    patient_id: str
    call_type: str
    status: str
    from_number: str
    to_number: str
    started_at: datetime
    answered_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None


@router.post(
    "/initiate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Initiate outbound call to patient",
)
async def initiate_call(
    request: InitiateCallRequest,
    user: CurrentUser,
    db: DbSession,
):
    """
    Initiate an outbound call to a patient.
    
    The call is triggered asynchronously via Celery task.
    Returns immediately with the task ID.
    """
    # Validate patient exists and belongs to user's organization
    patient = await Patient.fetch_by_id(db, uuid.UUID(request.patient_id))
    
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found"
        )
    
    if patient.organization_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Patient not in your organization"
        )
    
    if not patient.phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Patient has no phone number"
        )
    
    # Check if SIP is enabled
    sip_service = LiveKitSIPService()
    if not sip_service.is_sip_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Phone calling is not enabled"
        )
    
    # Trigger call asynchronously
    task = trigger_patient_call.delay(
        patient_id=request.patient_id,
        call_type=request.call_type,
        triggered_by_id=str(user.id),
    )
    
    logger.info(f"Call initiated by {user.id} to patient {request.patient_id}, task: {task.id}")
    
    return success_response(
        status_code=status.HTTP_202_ACCEPTED,
        message="Call initiated",
        data={
            "task_id": task.id,
            "patient_id": request.patient_id,
            "call_type": request.call_type,
        },
    )


@router.get(
    "/sessions",
    status_code=status.HTTP_200_OK,
    summary="List call sessions",
)
async def list_call_sessions(
    user: CurrentUser,
    db: DbSession,
    patient_id: Optional[str] = Query(None, description="Filter by patient ID"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """List call sessions for the user's organization."""
    query = CallSession.query(db).filter(
        CallSession.organization_id == user.organization_id
    )
    
    if patient_id:
        query = query.filter(CallSession.patient_id == uuid.UUID(patient_id))
    
    if status_filter:
        query = query.filter(CallSession.status == CallStatus(status_filter))
    
    sessions = await query.order_by(
        CallSession.started_at, desc=True
    ).paginate(page, per_page).all()
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Call sessions",
        data={
            "sessions": [
                {
                    "id": str(s.id),
                    "room_name": s.room_name,
                    "patient_id": str(s.patient_id),
                    "call_type": s.call_type.value,
                    "status": s.status.value,
                    "from_number": s.from_number,
                    "to_number": s.to_number,
                    "started_at": s.started_at.isoformat(),
                    "answered_at": s.answered_at.isoformat() if s.answered_at else None,
                    "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                    "duration_seconds": s.duration_seconds,
                }
                for s in sessions
            ],
            "page": page,
            "per_page": per_page,
        },
    )


@router.get(
    "/sessions/{session_id}",
    status_code=status.HTTP_200_OK,
    summary="Get call session details",
)
async def get_call_session(
    session_id: str,
    user: CurrentUser,
    db: DbSession,
):
    """Get details of a specific call session."""
    session = await CallSession.fetch_by_id(db, uuid.UUID(session_id))
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call session not found"
        )
    
    if session.organization_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Call session not in your organization"
        )
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Call session details",
        data={
            "id": str(session.id),
            "room_name": session.room_name,
            "patient_id": str(session.patient_id),
            "call_type": session.call_type.value,
            "status": session.status.value,
            "from_number": session.from_number,
            "to_number": session.to_number,
            "started_at": session.started_at.isoformat(),
            "answered_at": session.answered_at.isoformat() if session.answered_at else None,
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "duration_seconds": session.duration_seconds,
            "transcript": session.transcript,
            "summary": session.summary,
            "outcome": session.outcome,
        },
    )


@router.post(
    "/sessions/{room_name}/end",
    status_code=status.HTTP_200_OK,
    summary="End an active call",
)
async def end_call(
    room_name: str,
    user: CurrentUser,
    db: DbSession,
):
    """End an active call by closing the LiveKit room."""
    session = await CallSession.fetch_one(db, room_name=room_name)
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call session not found"
        )
    
    if session.organization_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Call session not in your organization"
        )
    
    if session.status in (CallStatus.COMPLETED, CallStatus.FAILED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Call already ended"
        )
    
    # End the call
    sip_service = LiveKitSIPService()
    await sip_service.end_call(room_name)
    
    # Update session
    session.status = CallStatus.COMPLETED
    session.ended_at = datetime.now(timezone.utc)
    if session.answered_at:
        session.duration_seconds = int(
            (session.ended_at - session.answered_at).total_seconds()
        )
    await session.save(db)
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Call ended",
    )


@router.get(
    "/status",
    status_code=status.HTTP_200_OK,
    summary="Get calling service status",
)
async def get_call_status(user: CurrentUser):
    """Check if phone calling is enabled and configured."""
    sip_service = LiveKitSIPService()
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Call service status",
        data={
            "sip_enabled": settings.LIVEKIT_SIP_ENABLED,
            "fully_configured": sip_service.is_sip_enabled(),
            "from_number": sip_service.from_number if sip_service.is_sip_enabled() else None,
        },
    )
