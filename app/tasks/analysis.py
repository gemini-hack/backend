import asyncio
from app.celery_app import celery_app
from app.db.database import SessionLocal
from app.workflows.daily_analysis import DailyAnalysisWorkflow
from app.utils.logger import logger

async def _run_analysis():
    """Inner async function to run the analysis."""
    async with SessionLocal() as db:
        workflow = DailyAnalysisWorkflow(db)
        await workflow.execute_all()

@celery_app.task(name="app.tasks.analysis.run_daily_analysis")
def run_daily_analysis():
    """Celery task to trigger morning rounds."""
    logger.info("Celery task: run_daily_analysis started.")
    try:
        asyncio.run(_run_analysis())
        logger.info("Celery task: run_daily_analysis completed successfully.")
    except Exception as e:
        logger.error(f"Celery task: run_daily_analysis failed: {str(e)}")
        raise
