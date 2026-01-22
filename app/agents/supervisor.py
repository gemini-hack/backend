import uuid
import json
from typing import List, Dict, Any
from app.agents.base import BaseSupervisor, BaseWorker
from app.agents.context import AgentContext, AgentAction
from app.models.patient import Patient, PatientStatus
from sqlalchemy import select
from app.utils.logger import logger

class SupervisorAgent(BaseSupervisor):
    """
    Head Doctor.
    Coordinates morning rounds, synthesizes specialist reports, 
    and makes final decisions.
    """
    
    def __init__(self, db_session, workers: List[BaseWorker]):
        super().__init__("head_doctor_supervisor", workers)
        self.db = db_session

    async def run_cycle(self, organization_id: uuid.UUID) -> AgentContext:
        logger.info(f"Supervisor {self.name} starting morning rounds for organization {organization_id}")
        
        # 1. Create context (Whiteboard)
        context = AgentContext(organization_id=organization_id)
        
        # 2. "Show patient list on whiteboard" - Fetch relevant patients
        query = select(Patient).where(
            Patient.organization_id == organization_id,
            Patient.status == PatientStatus.ACTIVE
        )
        result = await self.db.execute(query)
        patients = result.scalars().all()
        context.set("patients", patients)
        
        # 3. Call each specialist (Worker Agents)
        for worker in self.workers:
            try:
                logger.info(f"Calling specialist: {worker.name}")
                await worker.run(context)
            except Exception as e:
                logger.error(f"Specialist {worker.name} failed during rounds: {str(e)}")
        
        # 4. Synthesize findings (The "Brain" of the supervisor)
        # uses Gemini Pro for intelligent synthesis
        await self._synthesize_decisions(context)
        
        # 5. Quality Control: Call the Critic to review final decisions
        from app.agents.workers.critic import CriticWorker
        critic = CriticWorker()
        await critic.run(context)
        
        return context

    async def _synthesize_decisions(self, context: AgentContext):
        """
        Uses Gemini Pro to synthesize all specialist reports and make final decisions.
        """
        from app.services.ai_service import gemini_service
        
        # Prepare the specialist reports for the prompt
        reports = []
        for worker_name, result in context.worker_results.items():
            reports.append({
                "worker": worker_name,
                "findings": result.findings,
                "proposals": [p.model_dump() for p in result.proposed_actions]
            })
            
        system_instruction = (
            "You are the Head Doctor (Supervisor) of a highly efficient medical AI team. "
            "Your task is to synthesize reports from several specialists (Worker Agents) "
            "about multiple patients. You must output a final list of consolidated actions. "
            "Deduplicate actions, resolve conflicts, and ensure the highest priority clinical "
            "needs are addressed first. Only output valid JSON."
        )
        
        prompt = (
            f"Here are the specialists' reports from the morning rounds for Organization {context.organization_id}:\n"
            f"{json.dumps(reports, indent=2, default=str)}\n\n"
            "Produce a final list of actions for the patients. Each action should have: "
            "'type', 'target_id' (patient UUID), 'reasoning', 'confidence', and 'details' (dict). "
            "Available types: emergency_escalation, urgent_followup, schedule_checkin, engagement_nudge, onboarding_reminder, "
            "unsuppressed_vl_intervention, low_level_viremia_review, defaulter_tracing, iit_recovery_plan."
        )
        
        try:
            response = await gemini_service.get_structured_response(prompt, system_instruction)
            
            # The response should be a list of actions or a dict containing a list
            actions_data = response if isinstance(response, list) else response.get("actions", [])
            
            context.final_actions = [AgentAction(**a) for a in actions_data]
            logger.info(f"LLM Synthesis complete. Final action count: {len(context.final_actions)}")
            
        except Exception as e:
            logger.error(f"Gemini synthesis failed: {str(e)}. Falling back to rule-based synthesis.")
            # Fallback to the previous rule-based logic if LLM fails
            self._rule_based_synthesis(context)

    def _rule_based_synthesis(self, context: AgentContext):
        """Fallback rule-based synthesis."""
        all_proposals: List[AgentAction] = []
        for worker_result in context.worker_results.values():
            all_proposals.extend(worker_result.proposed_actions)
            
        final_actions_map: Dict[str, AgentAction] = {}
        priority_map = {
            "emergency_escalation": 100, "iit_recovery_plan": 95,
            "unsuppressed_vl_intervention": 90, "urgent_followup": 80,
            "defaulter_tracing": 70, "schedule_checkin": 50,
            "low_level_viremia_review": 40, "engagement_nudge": 20,
            "onboarding_reminder": 10
        }
        
        for proposal in all_proposals:
            existing = final_actions_map.get(proposal.target_id)
            if not existing or priority_map.get(proposal.type, 0) > priority_map.get(existing.type, 0):
                final_actions_map[proposal.target_id] = proposal
                    
        context.final_actions = list(final_actions_map.values())
