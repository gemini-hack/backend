import os
from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue
from app.core.config import settings

# Define exchanges
default_exchange = Exchange('default', type='direct')
dlx_exchange = Exchange('dlx', type='direct')

# Define queues with DLQ and priority support
task_queues = (
    Queue(
        'celery',
        exchange=default_exchange,
        routing_key='celery',
        queue_arguments={
            'x-dead-letter-exchange': 'dlx',
            'x-dead-letter-routing-key': 'dlq',
            'x-max-priority': 10,
        }
    ),
    # High priority queue for critical tasks
    Queue(
        'high_priority',
        exchange=default_exchange,
        routing_key='high_priority',
        queue_arguments={
            'x-dead-letter-exchange': 'dlx',
            'x-dead-letter-routing-key': 'dlq',
            'x-max-priority': 10,
        }
    ),
    # Dead Letter Queue
    Queue(
        'dlq',
        exchange=dlx_exchange,
        routing_key='dlq',
    ),
)

# Initialize Celery
celery_app = Celery(
    "mira_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.REDIS_URL,
)

# Configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    
    # Queues
    task_queues=task_queues,
    task_default_queue='celery',
    task_default_exchange='default',
    task_default_routing_key='celery',
    
    # Retry settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # Priority support
    worker_prefetch_multiplier=1,
    
    # Task routing
    task_routes={
        'app.tasks.email.*': {'queue': 'celery'},
        'app.tasks.analysis.*': {'queue': 'high_priority'},
        'app.tasks.reminders.*': {'queue': 'celery'},
    },
    
    # Explicitly include the task modules
    include=[
        "app.tasks.email",
        "app.tasks.analysis",
        "app.tasks.reminders",
    ]
)

# Auto-discover tasks from the tasks directory
celery_app.autodiscover_tasks(["app.tasks"])

# Set up the periodic schedule (Morning Rounds + Reminders)
celery_app.conf.beat_schedule = {
    "schedule-daily-reminders-at-5am": {
        "task": "app.tasks.reminders.schedule_daily_reminders",
        "schedule": crontab(hour=5, minute=0),
    },
    "run-daily-analysis-at-6am": {
        "task": "app.tasks.analysis.run_daily_analysis",
        "schedule": crontab(hour=6, minute=0),
    },
    "escalate-no-shows-at-7am": {
        "task": "app.tasks.reminders.escalate_no_shows",
        "schedule": crontab(hour=7, minute=0),
    },
}

