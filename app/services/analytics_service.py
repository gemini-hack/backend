from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import Patient, PatientStatus, Condition
from app.models.agent import Alert, AgentAction, AlertStatus

class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dashboard_stats(self, organization_id: UUID, org_name: str) -> dict:
        """Aggregate stats for the admin dashboard."""
        
        # --- 1. Patient Stats ---
        # Total Active
        total_active = await self._count(
            select(func.count()).where(
                Patient.organization_id == organization_id,
                Patient.status == PatientStatus.ACTIVE
            )
        )
        
        # New This Week
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        new_this_week = await self._count(
            select(func.count()).where(
                Patient.organization_id == organization_id,
                Patient.created_at >= week_ago
            )
        )
        
        # By Condition
        condition_counts = {}
        for cond in Condition:
            count = await self._count(
                select(func.count()).where(
                    Patient.organization_id == organization_id,
                    Patient.primary_condition == cond
                )
            )
            if count > 0:
                condition_counts[cond.value] = count
                
        # By Status
        status_counts = {}
        for stat in PatientStatus:
            count = await self._count(
                select(func.count()).where(
                    Patient.organization_id == organization_id,
                    Patient.status == stat
                )
            )
            if count > 0:
                status_counts[stat.value] = count

        # --- 2. Alert Stats ---
        total_pending_alerts = await self._count(
            select(func.count()).where(
                Alert.organization_id == organization_id,
                Alert.status == AlertStatus.PENDING
            )
        )
        
        critical_alerts = await self._count(
            select(func.count()).where(
                Alert.organization_id == organization_id,
                Alert.status == AlertStatus.PENDING,
                Alert.severity == "critical"
            )
        )
        
        urgent_alerts = await self._count(
            select(func.count()).where(
                Alert.organization_id == organization_id,
                Alert.status == AlertStatus.PENDING,
                Alert.severity == "urgent"
            )
        )
        
        # --- 3. Agent Stats ---
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        actions_today = await self._count(
             select(func.count()).where(
                AgentAction.organization_id == organization_id,
                AgentAction.created_at >= today_start
            )
        )
        
        actions_pending = await self._count(
             select(func.count()).where(
                AgentAction.organization_id == organization_id,
                AgentAction.status == "pending"
            )
        )
        
        return {
            "organization_id": str(organization_id),
            "organization_name": org_name,
            "generated_at": datetime.now(timezone.utc),
            "patients": {
                "total_active": total_active,
                "new_this_week": new_this_week,
                "by_condition": condition_counts,
                "by_status": status_counts
            },
            "alerts": {
                "total_pending": total_pending_alerts,
                "critical_count": critical_alerts,
                "high_priority_count": urgent_alerts,
                "by_category": {} # Simplified for now
            },
            "agents": {
                "actions_today": actions_today,
                "actions_pending": actions_pending,
                "top_actions": [] # Can be added later
            }
        }

    async def _count(self, stmt) -> int:
        result = await self.db.execute(stmt)
        return result.scalar() or 0
