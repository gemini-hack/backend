import uuid
from datetime import datetime
from typing import List, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Organization
from app.models.patient import Patient
from app.models.agent import AgentAction, Alert, AlertSeverity, AlertStatus
from app.agents.supervisor import SupervisorAgent
from app.utils.logger import logger


def _serialize_for_json(obj: Any) -> Any:
    """Recursively convert datetime objects to ISO strings for JSONB storage."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: _serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_for_json(item) for item in obj]
    elif isinstance(obj, uuid.UUID):
        return str(obj)
    return obj


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

    async def execute_for_org(self, organization_id: uuid.UUID, cycle_id: uuid.UUID = None):
        """
        Run morning rounds for a specific organization.
        
        Args:
            organization_id: The organization to analyze
            cycle_id: Optional cycle_id for SSE streaming. If provided, clients can
                      subscribe to the thought stream before analysis starts.
        """
        logger.info(f"Running daily analysis for organization {organization_id}" + 
                   (f" with cycle_id {cycle_id}" if cycle_id else ""))
        
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
        
        # 4. Run the cycle (Morning Rounds) - pass cycle_id for streaming
        context = await supervisor.run_cycle(organization_id, cycle_id=cycle_id)
        
        # 5. Persist decisions
        await self._persist_actions(context)
        
        await self.db.commit()
        logger.info(f"Daily analysis complete for org {organization_id}. {len(context.final_actions)} actions generated.")

    async def _persist_actions(self, context):
        """
        Converts agent actions from context into database records with FULL TRACE.
        
        Builds a decision_trace that captures:
        - Specialist thoughts (who proposed what and why)
        - Supervisor reasoning (final synthesis)
        - Critic validation (safety review)
        
        Includes deduplication: skips actions if an identical pending action
        already exists for the same (patient_id, action_type).
        
        Complexity: O(n × m) where n=actions, m=workers
        """
        from app.models.agent import ActionOutcome as DBActionOutcome
        from sqlalchemy import and_
        
        alert_count = 0
        action_types_seen = set()
        skipped_duplicates = 0
        
        # 1. Capture Critic Reviews (Global for this cycle)
        critic_results = context.worker_results.get("quality_doctor_critic")
        critic_feedback_map = {}
        if critic_results:
            # Map critic findings to patient IDs for easy lookup
            for finding in critic_results.findings:
                for action in context.final_actions:
                    if str(action.target_id) in finding:
                        critic_feedback_map[action.target_id] = finding
        
        for action in context.final_actions:
            action_types_seen.add(action.type)
            
            # DEDUPLICATION: Skip if identical pending action already exists
            existing_query = select(AgentAction.id).where(
                and_(
                    AgentAction.patient_id == uuid.UUID(action.target_id),
                    AgentAction.organization_id == context.organization_id,
                    AgentAction.action_type == action.type,
                    AgentAction.outcome.in_([
                        DBActionOutcome.PENDING,
                        DBActionOutcome.SENT,
                    ])
                )
            ).limit(1)
            existing_result = await self.db.execute(existing_query)
            if existing_result.scalar_one_or_none():
                skipped_duplicates += 1
                logger.debug(f"Skipping duplicate action {action.type} for patient {action.target_id}")
                continue
            
            # 2. Build the Decision Trace (The "Brain Dump")
            trace = {
                "cycle_id": str(context.cycle_id),
                "cycle_timestamp": context.start_time.isoformat(),
                "workers_in_cycle": list(context.worker_results.keys()),
                "specialists": [],
                "supervisor": {
                    "reasoning": action.reasoning,
                    "confidence": action.confidence,
                    "action_type": action.type
                },
                "critic": None,
                "execution_log": []
            }
            
            # A. Trace Specialist Thoughts
            # Look through all workers to see who proposed something for this patient
            for worker_name, result in context.worker_results.items():
                if worker_name == "quality_doctor_critic":
                    continue
                
                relevant_findings = []
                
                # Check proposals from this worker for this patient
                for proposal in result.proposed_actions:
                    if proposal.target_id == action.target_id:
                        relevant_findings.append(f"Proposed {proposal.type}: {proposal.reasoning}")
                
                # Also include general findings if any mention this patient
                for finding in result.findings:
                    if action.target_id in finding:
                        relevant_findings.append(finding)
                
                # If we found relevant thoughts, add them to the trace
                if relevant_findings:
                    trace["specialists"].append({
                        "role": worker_name,
                        "thoughts": relevant_findings,
                        "evaluated_at": result.timestamp.isoformat() if result.timestamp else None,
                        "patient_ids_flagged": [str(pid) for pid in result.flagged_patients]
                    })
            
            # B. Trace Critic Review
            if action.target_id in critic_feedback_map:
                trace["critic"] = {
                    "decision": "REVIEWED",
                    "reasoning": critic_feedback_map[action.target_id]
                }
            else:
                trace["critic"] = {
                    "decision": "NOT_REVIEWED",
                    "reasoning": "No specific criticism logged for this action."
                }
            
            # C. Capture execution status if auto-executed
            if action.content and action.content.get("execution_status"):
                trace["execution_log"].append(action.content.get("execution_status"))
            if action.content and action.content.get("execution_error"):
                trace["execution_log"].append(f"ERROR: {action.content.get('execution_error')}")
            
            # 3. Create AgentAction record with trace
            db_action = AgentAction(
                patient_id=uuid.UUID(action.target_id),
                organization_id=context.organization_id,
                action_type=action.type,
                status=action.status,
                content=_serialize_for_json(action.content),
                ai_reasoning=action.reasoning,
                confidence_score=action.confidence,
                decision_trace=_serialize_for_json(trace)  # Save the full trace!
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
            elif action.type in [
                "defaulter_tracing",
                "engagement_nudge",
                "onboarding_reminder",
                "medication_reminder",
                "appointment_reminder",
                "schedule_checkin",
                "low_level_viremia_review",
            ]:
                severity = AlertSeverity.WARNING
            
            if severity:
                alert = Alert(
                    patient_id=uuid.UUID(action.target_id),
                    organization_id=context.organization_id,
                    severity=severity,
                    status=AlertStatus.PENDING,
                    title=f"AI Agent: {action.type.replace('_', ' ').title()}",
                    description=action.reasoning,
                    ai_assessment=_serialize_for_json(action.content)
                )
                self.db.add(alert)
                alert_count += 1
        
        # Commit to get IDs
        await self.db.commit()
        
        # Push real-time notifications to connected dashboards
        try:
            from app.services.dashboard_notifier import DashboardNotifier
            notifier = DashboardNotifier(context.organization_id)
            
            # Notify cycle complete with summary
            await notifier.notify_cycle_completed(
                cycle_id=context.cycle_id,
                actions_count=len(context.final_actions),
                alerts_count=alert_count
            )
            logger.info(f"Dashboard notified: {len(context.final_actions)} actions, {alert_count} alerts")
        except Exception as e:
            # Non-blocking - don't fail the workflow if notification fails
            logger.warning(f"Dashboard notification failed (non-blocking): {e}")
        
        logger.info(f"Action types seen: {action_types_seen}")
        logger.info(f"Created {alert_count} alerts from {len(context.final_actions)} actions (with decision traces). Skipped {skipped_duplicates} duplicates.")

