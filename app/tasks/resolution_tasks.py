"""
Continuous Resolution Tasks.

Periodically checks for agent actions that can be auto-resolved
because the patient has taken the desired action (e.g., attended appointment,
submitted a health reading, or responded to outreach).

Runs every 30 minutes via Celery Beat — ensures the dashboard stays current
instead of waiting for the next daily analysis cycle.
"""
import asyncio

from app.celery_app import celery_app
from app.db.database import get_celery_session
from app.utils.logger import logger


async def _resolve_all_orgs():
    """Resolve completed actions for every active organization."""
    from sqlalchemy import select
    from app.models.user import Organization
    from app.services.action_idempotency import detect_and_resolve_outcomes

    async with get_celery_session() as db:
        query = select(Organization).where(Organization.is_active == True)
        result = await db.execute(query)
        organizations = result.scalars().all()

        total_resolved = 0

        for org in organizations:
            try:
                counts = await detect_and_resolve_outcomes(db, org.id)
                if counts["total"] > 0:
                    total_resolved += counts["total"]
                    logger.info(
                        f"Auto-resolved {counts['total']} actions for org {org.id}: "
                        f"appointments={counts.get('appointment_reminder', 0)}, "
                        f"nudges={counts.get('engagement_nudge', 0)}, "
                        f"vl={counts.get('vl_intervention', 0)}"
                    )

                    # Notify dashboard of resolved actions
                    try:
                        from app.services.dashboard_notifier import DashboardNotifier
                        notifier = DashboardNotifier(org.id)
                        await notifier.notify_cycle_completed(
                            cycle_id=None,
                            actions_count=0,
                            alerts_count=0,
                        )
                    except Exception as e:
                        logger.debug(f"Dashboard notification skipped: {e}")

            except Exception as e:
                logger.error(f"Resolution check failed for org {org.id}: {e}")

        await db.commit()

        if total_resolved > 0:
            logger.info(f"Resolution sweep complete: {total_resolved} actions resolved across {len(organizations)} orgs")


async def _expire_stale_actions():
    """Expire actions that have been PENDING for more than 7 days."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select, and_
    from app.models.agent import AgentAction, ActionOutcome

    async with get_celery_session() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        query = select(AgentAction).where(
            and_(
                AgentAction.outcome.in_([ActionOutcome.PENDING, ActionOutcome.SENT]),
                AgentAction.created_at < cutoff,
            )
        )
        result = await db.execute(query)
        stale_actions = result.scalars().all()

        for action in stale_actions:
            action.outcome = ActionOutcome.EXPIRED
            action.outcome_detected_at = datetime.now(timezone.utc)
            action.outcome_reason = "Auto-expired: no resolution detected within 7 days"

        await db.commit()

        if stale_actions:
            logger.info(f"Expired {len(stale_actions)} stale actions (>7 days with no resolution)")


@celery_app.task(name="app.tasks.resolution_tasks.resolve_completed_actions")
def resolve_completed_actions():
    """
    Celery task: resolve actions where the patient has responded.
    Runs every 30 minutes via Beat.
    """
    logger.info("Resolution sweep starting...")
    try:
        asyncio.run(_resolve_all_orgs())
    except Exception as e:
        logger.error(f"Resolution sweep failed: {e}")
        raise


@celery_app.task(name="app.tasks.resolution_tasks.expire_stale_actions")
def expire_stale_actions():
    """
    Celery task: expire actions older than 7 days that never resolved.
    Runs daily at midnight via Beat.
    """
    logger.info("Stale action expiry starting...")
    try:
        asyncio.run(_expire_stale_actions())
    except Exception as e:
        logger.error(f"Stale action expiry failed: {e}")
        raise
