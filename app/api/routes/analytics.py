from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, DbSession, require_permission
from app.services.analytics_service import AnalyticsService
from app.schemas.analytics import AdminDashboardResponse
from app.models.user import Organization

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=AdminDashboardResponse,
    summary="Get admin dashboard statistics",
    dependencies=[Depends(require_permission("reports:read"))],
)
async def get_admin_dashboard(
    user: CurrentUser,
    db: DbSession,
):
    """
    Get high-level statistics for the admin dashboard.
    Includes patient counts, alert summaries, and agent activity.
    """

    result = await db.execute(
        select(Organization).where(Organization.id == user.organization_id)
    )
    org = result.scalar_one_or_none()
    
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    service = AnalyticsService(db)
    stats = await service.get_dashboard_stats(
        organization_id=user.organization_id,
        org_name=org.name
    )

    return stats