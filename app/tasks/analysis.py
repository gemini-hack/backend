import asyncio

from app.celery_app import celery_app
from app.db.database import get_celery_session
from app.tasks.outbound_calls import trigger_calls_for_alerts

from app.utils.logger import logger

async def _run_analysis():
    """Inner async function to run the analysis for ALL orgs."""
    from app.workflows.daily_analysis import DailyAnalysisWorkflow
    async with get_celery_session() as db:
        workflow = DailyAnalysisWorkflow(db)
        await workflow.execute_all()


async def _run_org_analysis(organization_id: str, cycle_id: str = None):
    """Inner async function to run analysis for a SINGLE org."""
    import uuid
    from app.workflows.daily_analysis import DailyAnalysisWorkflow
    async with get_celery_session() as db:
        workflow = DailyAnalysisWorkflow(db)
        org_uuid = uuid.UUID(organization_id)
        c_uuid = uuid.UUID(cycle_id) if cycle_id else None
        await workflow.execute_for_org(org_uuid, cycle_id=c_uuid)

@celery_app.task(name="app.tasks.analysis.run_daily_analysis")
def run_daily_analysis():
    """Celery task to trigger morning rounds for ALL orgs."""
    logger.info("Celery task: run_daily_analysis started.")
    try:
        asyncio.run(_run_analysis())
        
        trigger_calls_for_alerts.delay()
        
        logger.info("Celery task: run_daily_analysis completed successfully.")
    except Exception as e:
        logger.error(f"Celery task: run_daily_analysis failed: {str(e)}")
        raise


@celery_app.task(name="app.tasks.analysis.run_org_analysis")
def run_org_analysis(organization_id: str, cycle_id: str = None):
    """
    Celery task to trigger analysis for a SINGLE organization.
    
    Used by the /trigger-rounds API endpoint to offload heavy analysis
    from the FastAPI server to the Celery worker.
    
    Args:
        organization_id: UUID string of the organization
        cycle_id: Optional UUID string for SSE thought streaming
    """
    logger.info(f"Celery task: run_org_analysis started for org {organization_id}")
    try:
        asyncio.run(_run_org_analysis(organization_id, cycle_id))
        logger.info(f"Celery task: run_org_analysis completed for org {organization_id}")
    except Exception as e:
        logger.error(f"Celery task: run_org_analysis failed for org {organization_id}: {str(e)}")
        raise
