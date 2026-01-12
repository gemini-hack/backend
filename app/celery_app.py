import os
from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

# Initialize Celery
celery_app = Celery(
    "mira_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

# Optional configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)

# Auto-discover tasks from the tasks directory
celery_app.autodiscover_tasks(["app.tasks"])

# Set up the periodic schedule (Morning Rounds)
celery_app.conf.beat_schedule = {
    "run-daily-analysis-at-6am": {
        "task": "app.tasks.analysis.run_daily_analysis",
        "schedule": crontab(hour=6, minute=0),
    },
}
