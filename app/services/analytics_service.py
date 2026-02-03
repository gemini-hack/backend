from datetime import datetime, timedelta, timezone
from uuid import UUID
from typing import Type
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base_model import QueryBuilder
from app.models.patient import Patient, PatientStatus, Condition
from app.models.agent import Alert, AgentAction, AlertStatus, ActionOutcome


class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _query(self, model: Type) -> QueryBuilder:
        """Create a new query builder for the given model."""
        return QueryBuilder(model, self.db)

    async def get_dashboard_stats(self, organization_id: UUID, org_name: str) -> dict:
        """Aggregate stats for the admin dashboard."""
        
        # --- 1. Patient Stats ---
        total_active = await (
            self._query(Patient)
            .for_organization(organization_id)
            .with_status(PatientStatus.ACTIVE)
            .count()
        )
        
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        new_this_week = await (
            self._query(Patient)
            .for_organization(organization_id)
            .created_after(week_ago)
            .count()
        )
        
        # By Condition
        condition_counts = {}
        for cond in Condition:
            count = await (
                self._query(Patient)
                .for_organization(organization_id)
                .filter(Patient.primary_condition == cond)
                .count()
            )
            if count > 0:
                condition_counts[cond.value] = count
                
        # By Status
        status_counts = {}
        for stat in PatientStatus:
            count = await (
                self._query(Patient)
                .for_organization(organization_id)
                .with_status(stat)
                .count()
            )
            if count > 0:
                status_counts[stat.value] = count

        # --- 2. Alert Stats ---
        total_pending_alerts = await (
            self._query(Alert)
            .for_organization(organization_id)
            .with_status(AlertStatus.PENDING)
            .count()
        )
        
        critical_alerts = await (
            self._query(Alert)
            .for_organization(organization_id)
            .with_status(AlertStatus.PENDING)
            .filter(Alert.severity == "critical")
            .count()
        )
        
        urgent_alerts = await (
            self._query(Alert)
            .for_organization(organization_id)
            .with_status(AlertStatus.PENDING)
            .filter(Alert.severity == "urgent")
            .count()
        )
        
        # --- 3. Agent Stats ---
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        actions_today = await (
            self._query(AgentAction)
            .for_organization(organization_id)
            .created_after(today_start)
            .count()
        )
        
        actions_pending = await (
            self._query(AgentAction)
            .for_organization(organization_id)
            .filter(AgentAction.status == "pending")
            .count()
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
                "by_category": {}
            },
            "agents": {
                "actions_today": actions_today,
                "actions_pending": actions_pending,
                "top_actions": []
            }
        }

    async def get_worker_dashboard_stats(
        self, 
        organization_id: UUID, 
        worker_id: UUID | None = None,
        user_role: str | None = None
    ) -> dict:
        """
        Get worker-focused dashboard stats from agent actions.
        
        Args:
            organization_id: The organization to filter by
            worker_id: If provided, filter to patients assigned to this worker
            user_role: The role of the worker (doctor, nurse, coordinator) to determine assignment field
            
        Returns:
            Stats filtered to assigned patients for workers, or org-wide for admins
        """
        from app.models.user import UserRole
        
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        
        # Build patient filter based on role
        # Admins (org_owner, org_admin) see all patients; workers see only assigned
        assigned_patient_ids = None
        if worker_id and user_role and user_role not in [UserRole.ORG_OWNER.value, UserRole.ORG_ADMIN.value]:
            # Build conditions for patient assignment based on role
            base_condition = Patient.organization_id == organization_id
            
            if user_role == UserRole.DOCTOR.value:
                role_condition = Patient.primary_physician_id == worker_id
            elif user_role == UserRole.NURSE.value:
                role_condition = Patient.assigned_nurse_id == worker_id
            elif user_role == UserRole.COORDINATOR.value:
                role_condition = Patient.care_coordinator_id == worker_id
            else:
                # Unknown role - show patients where they're assigned in any capacity
                role_condition = or_(
                    Patient.primary_physician_id == worker_id,
                    Patient.assigned_nurse_id == worker_id,
                    Patient.care_coordinator_id == worker_id
                )
            
            # Get patient IDs
            result = await self.db.execute(
                select(Patient.id).where(base_condition, role_condition)
            )
            assigned_patient_ids = [row[0] for row in result.fetchall()]
            
            # If no patients assigned, return zeros early
            if not assigned_patient_ids:
                return {
                    "total_patients": 0,
                    "needs_attention": 0,
                    "pending_actions": 0,
                    "resolved_today": 0,
                    "generated_at": datetime.now(timezone.utc)
                }
        
        # Helper to build queries with optional patient filter
        def build_query() -> QueryBuilder:
            query = self._query(AgentAction).for_organization(organization_id)
            if assigned_patient_ids is not None:
                query.for_patients(assigned_patient_ids)
            return query
        
        # 1. Total patients - for admin: all patients in org, for workers: assigned patients
        if assigned_patient_ids is not None:
            # Worker: count their assigned patients
            total_patients = len(assigned_patient_ids)
        else:
            # Admin: count all patients in organization
            total_patients = await (
                self._query(Patient)
                .for_organization(organization_id)
                .count()
            )
        
        # 2. Patients needing attention (have PENDING or FAILED actions)
        needs_attention = await (
            build_query()
            .filter(AgentAction.outcome.in_([ActionOutcome.PENDING, ActionOutcome.FAILED]))
            .count_distinct(AgentAction.patient_id)
        )
        
        # 3. Total pending actions
        pending_actions = await (
            build_query()
            .filter(AgentAction.outcome == ActionOutcome.PENDING)
            .count()
        )
        
        # 4. Resolved today
        resolved_today = await (
            build_query()
            .filter(
                AgentAction.outcome == ActionOutcome.RESOLVED,
                AgentAction.outcome_detected_at >= today_start
            )
            .count()
        )
        
        return {
            "total_patients": total_patients,
            "needs_attention": needs_attention,
            "pending_actions": pending_actions,
            "resolved_today": resolved_today,
            "generated_at": datetime.now(timezone.utc)
        }
