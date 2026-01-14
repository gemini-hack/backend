import uuid
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Organization
from app.models.patient import Patient
from app.models.agent import AgentAction, Alert, AlertSeverity, AlertStatus
from app.agents.supervisor import SupervisorAgent
from app.utils.logger import logger

class DailyAnalysisWorkflow:
    """
    Orchestrates the daily multi-agent analysis rounds across all organizations.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db

    async def execute_all(self):
        """Run morning rounds for all active organizations."""
        logger.info("Starting global daily analysis cycle...")
        
        query = select(Organization).where(Organization.is_active == True)
        result = await self.db.execute(query)
        organizations = result.scalars().all()
        
        for org in organizations:
            try:
                await self.execute_for_org(org.id)
            except Exception as e:
                logger.error(f"Failed to run daily analysis for organization {org.id}: {str(e)}")
        
        logger.info("Global daily analysis cycle complete.")

    async def execute_for_org(self, organization_id: uuid.UUID):
        """Run morning rounds for a specific organization."""
        logger.info(f"Running daily analysis for organization {organization_id}")
        
        # 1. Fetch organization to get specializations
        from app.models.user import Organization
        org = await Organization.fetch_unique(self.db, id=organization_id)
        if not org:
            logger.error(f"Organization {organization_id} not found")
            return

        # 2. Use Factory to get specialists based on org choices
        from app.agents.factory import AgentFactory
        specialists = AgentFactory.get_workers_for_org(self.db, org.disease_specializations)
        
        # 3. Initialize supervisor with specialists
        supervisor = SupervisorAgent(self.db, specialists)
        
        # 4. Run the cycle (Morning Rounds)
        context = await supervisor.run_cycle(organization_id)
        
        # 5. Persist decisions
        await self._persist_actions(context)
        
        await self.db.commit()
        logger.info(f"Daily analysis complete for org {organization_id}. {len(context.final_actions)} actions generated.")

    async def _persist_actions(self, context):
        """Converts agent actions from context into database records."""
        for action in context.final_actions:
            # Create AgentAction record
            db_action = AgentAction(
                patient_id=uuid.UUID(action.target_id),
                organization_id=context.organization_id,
                action_type=action.type,
                status="pending",
                content=action.details,
                ai_reasoning=action.reasoning,
                confidence_score=action.confidence
            )
            self.db.add(db_action)
            
            # Create Alert for critical/urgent findings
            severity = None
            if action.type == "emergency_escalation":
                severity = AlertSeverity.CRITICAL
            elif action.type in [
                "urgent_followup", 
                "unsuppressed_vl_intervention", 
                "iit_recovery_plan"
            ]:
                severity = AlertSeverity.URGENT
            elif action.type == "defaulter_tracing":
                severity = AlertSeverity.WARNING
            
            if severity:
                alert = Alert(
                    patient_id=uuid.UUID(action.target_id),
                    organization_id=context.organization_id,
                    severity=severity,
                    status=AlertStatus.PENDING,
                    title=f"AI Agent: {action.type.replace('_', ' ').title()}",
                    description=action.reasoning,
                    ai_assessment=action.details
                )
                self.db.add(alert)
