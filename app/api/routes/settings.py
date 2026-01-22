from typing import Annotated

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_permission
from app.core.permissions import PERM_SETTINGS_READ, PERM_SETTINGS_UPDATE
from app.db.database import get_db
from app.models.user import User
from app.schemas.settings import (
    PhoneProvisionRequest,
    PhoneStatusResponse,
    PhoneProvisionResponse,
    PhoneDisableResponse,
    AvailableNumbersResponse,
    AvailableNumberResponse,
)
from app.schemas.agent_settings import (
    AgentSettingsRequest,
    AgentSettingsResponse,
    AgentSettingsResetResponse,
)
from app.services.phone_settings_service import PhoneSettingsService
from app.services.agent_settings_service import AgentSettingsService

router = APIRouter(prefix="/settings", tags=["Settings"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


# ============== Phone Settings ==============

@router.get("/phone", response_model=PhoneStatusResponse)
async def get_phone_status(
    user: Annotated[User, Depends(require_permission(PERM_SETTINGS_READ))],
    db: DbSession,
):
    """Get phone calling status."""
    service = PhoneSettingsService(db)
    
    try:
        result = await service.get_status(user.organization_id)
        return PhoneStatusResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/phone/available-numbers", response_model=AvailableNumbersResponse)
async def search_available_numbers(
    user: Annotated[User, Depends(require_permission(PERM_SETTINGS_UPDATE))],
    db: DbSession,
    country: str = "US",
    area_code: str = None,
    limit: int = 10,
):
    """Search available phone numbers."""
    service = PhoneSettingsService(db)
    
    if not service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Phone provisioning not configured"
        )
    
    try:
        numbers = await service.search_numbers(
            country=country,
            area_code=area_code,
            limit=limit,
        )
        return AvailableNumbersResponse(
            numbers=[AvailableNumberResponse(**n) for n in numbers]
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to search numbers"
        )


@router.post("/phone/provision", response_model=PhoneProvisionResponse)
async def provision_phone(
    request: PhoneProvisionRequest,
    user: Annotated[User, Depends(require_permission(PERM_SETTINGS_UPDATE))],
    db: DbSession,
):
    """Provision a phone number with auto SIP trunk creation."""
    service = PhoneSettingsService(db)
    
    if not service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Phone provisioning not configured"
        )
    
    try:
        result = await service.provision(
            org_id=user.organization_id,
            phone_number=request.phone_number,
        )
        return PhoneProvisionResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to provision: {str(e)}"
        )


@router.post("/phone/disable", response_model=PhoneDisableResponse)
async def disable_phone(
    user: Annotated[User, Depends(require_permission(PERM_SETTINGS_UPDATE))],
    db: DbSession,
):
    """Disable phone calling and release resources."""
    service = PhoneSettingsService(db)
    
    try:
        result = await service.disable(user.organization_id)
        return PhoneDisableResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disable: {str(e)}"
        )


# ============== AI Agent Settings ==============

@router.get("/agent", response_model=AgentSettingsResponse)
async def get_agent_settings(
    user: Annotated[User, Depends(require_permission(PERM_SETTINGS_READ))],
    db: DbSession,
):
    """Get AI agent configuration."""
    service = AgentSettingsService(db)
    
    try:
        result = await service.get_settings(user.organization_id)
        return AgentSettingsResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/agent", response_model=AgentSettingsResponse)
async def update_agent_settings(
    request: AgentSettingsRequest,
    user: Annotated[User, Depends(require_permission(PERM_SETTINGS_UPDATE))],
    db: DbSession,
):
    """Update AI agent configuration."""
    service = AgentSettingsService(db)
    
    try:
        result = await service.update_settings(user.organization_id, request)
        return AgentSettingsResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/agent/reset", response_model=AgentSettingsResetResponse)
async def reset_agent_settings(
    user: Annotated[User, Depends(require_permission(PERM_SETTINGS_UPDATE))],
    db: DbSession,
):
    """Reset AI agent settings to defaults."""
    service = AgentSettingsService(db)
    
    try:
        result = await service.reset_to_defaults(user.organization_id)
        return AgentSettingsResetResponse(
            success=True,
            message="Agent settings reset to defaults",
            settings=AgentSettingsResponse(**result),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

