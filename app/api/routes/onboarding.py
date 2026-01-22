from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_permission
from app.core.permissions import PERM_ONBOARDING_COMPLETE, PERM_SETTINGS_READ
from app.db.database import get_db
from app.models.user import User
from app.schemas.onboarding import (
    OnboardingStatusResponse,
    OnboardingCompleteRequest,
    OnboardingCompleteResponse,
)
from app.services.onboarding_service import OnboardingService

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    user: Annotated[User, Depends(require_permission(PERM_SETTINGS_READ))],
    db: DbSession,
):
    """Check if onboarding is complete."""
    service = OnboardingService(db)
    
    try:
        result = await service.get_status(user.organization_id)
        return OnboardingStatusResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/complete", response_model=OnboardingCompleteResponse)
async def complete_onboarding(
    user: Annotated[User, Depends(require_permission(PERM_ONBOARDING_COMPLETE))],
    db: DbSession,
    request: OnboardingCompleteRequest = None,
):
    """Complete onboarding in a single call"""
    # Default empty request
    if not request:
        request = OnboardingCompleteRequest()
    
    service = OnboardingService(db)
    
    try:
        result = await service.complete(
            org_id=user.organization_id,
            request=request,
        )
        return OnboardingCompleteResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
