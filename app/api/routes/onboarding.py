from typing import Annotated, Optional
from fastapi import APIRouter, status, Depends
from fastapi.encoders import jsonable_encoder

from app.api.dependencies import CurrentUser, DbSession, require_permission
from app.core.permissions import PERM_ONBOARDING_COMPLETE, PERM_SETTINGS_READ
from app.schemas.onboarding import (
    OnboardingStatusResponse,
    OnboardingCompleteRequest,
    OnboardingCompleteResponse,
)
from app.services.onboarding_service import OnboardingService
from app.utils.responses import success_response

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


@router.get(
    "/status",
    status_code=status.HTTP_200_OK,
    response_model=OnboardingStatusResponse,
    summary="Get onboarding status",
)
async def get_onboarding_status(
    user: Annotated[CurrentUser, Depends(require_permission(PERM_SETTINGS_READ))],
    db: DbSession,
):
    """Check if onboarding is complete."""
    service = OnboardingService(db)
    result = await service.get_status(user.organization_id)
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Onboarding status retrieved",
        data=jsonable_encoder(OnboardingStatusResponse(**result)),
    )


@router.post(
    "/complete",
    status_code=status.HTTP_200_OK,
    response_model=OnboardingCompleteResponse,
    summary="Complete onboarding",
)
async def complete_onboarding(
    user: Annotated[CurrentUser, Depends(require_permission(PERM_ONBOARDING_COMPLETE))],
    db: DbSession,
    request: Optional[OnboardingCompleteRequest] = None,
):
    """Complete onboarding in a single call"""
    # Default empty request
    if not request:
        request = OnboardingCompleteRequest()
    
    service = OnboardingService(db)
    result = await service.complete(
        org_id=user.organization_id,
        request=request,
    )
    
    return success_response(
        status_code=status.HTTP_200_OK,
        message=result["message"],
        data=jsonable_encoder(OnboardingCompleteResponse(**result)),
    )
