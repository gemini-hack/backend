from fastapi import APIRouter, Depends, status
from fastapi.encoders import jsonable_encoder

from app.api.dependencies import CurrentUser, DbSession, require_permission
from app.services.analytics_service import AnalyticsService
from app.schemas.analytics import AdminDashboardResponse
from app.utils.responses import success_response

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
    service = AnalyticsService(db)
    stats = await service.get_dashboard_stats(
        organization_id=user.organization_id,
        org_name=user.organization.name
    )
    
    return success_response(
        status_code=200,
        message="Dashboard stats retrieved",
        data=jsonable_encoder(stats),
    )
