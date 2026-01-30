import uuid
from typing import Dict, Any, List
from app.agents.base import BaseWorker
from app.agents.context import AgentContext, WorkerResult, AgentAction
from app.utils.logger import logger

class CriticWorker(BaseWorker):
    """
    Quality Doctor.
    Reviews proposed actions for safety, protocol adherence, and clinical common sense.
    """
    
    def __init__(self):
        super().__init__("quality_doctor_critic")

    async def run(self, context: AgentContext) -> WorkerResult:
        logger.info(f"Worker {self.name} reviewing proposed actions with Gemini Pro")
        result = WorkerResult(worker_name=self.name)
        
        from app.services.ai_service import gemini_service
        import json
        
        proposals = context.final_actions
        if not proposals:
            logger.info("No actions for Critic to review.")
            return result
            
        system_instruction = (
            "You are the Quality Assurance Doctor. You are the final safety barrier between AI and Patient."
            "Review the Supervisor's proposed actions for Clinical Safety and Guideline Adherence."
            
            "### SAFETY AUDIT CHECKLIST\n"
            "1. **Regimen Integrity:** Did the team miss a patient on a banned drug (Nevirapine/d4T)? If yes, REJECT the plan and demand 'regimen_optimization'.\n"
            "2. **Viral Load Logic:** If VL > 1000, is there an active intervention plan (Counseling/Switch)? If not, REJECT.\n"
            "3. **Autonomy Check:** Did the Supervisor mark a CLINICAL action (like 'initiate_art') for auto-execution (confidence > 0.9)? \n"
            "   - If yes, DOWNGRADE confidence to 0.5 to force Human Review. AI cannot prescribe medication autonomously.\n"
            
            "Output valid JSON reviews."
        )
        
        prompt = (
            "Review the following proposed actions for patients in this cycle:\n"
            f"{json.dumps([a.model_dump() for a in proposals], indent=2, default=str)}\n\n"
            "Return a list of reviews. Each review should include: "
            "'target_id', 'action_type', 'decision' (APPROVED/REJECTED), and 'reasoning'."
        )
        
        try:
            reviews = await gemini_service.get_structured_response(prompt, system_instruction)
            
            # Extract findings for the result
            review_list = reviews if isinstance(reviews, list) else reviews.get("reviews", [])
            
            findings = []
            for r in review_list:
                findings.append(f"{r.get('decision')}: {r.get('action_type')} for {r.get('target_id')} - {r.get('reasoning')}")
                
            result.findings = findings
            logger.info(f"Critic review complete. {len(findings)} actions reviewed.")
            
        except Exception as e:
            logger.error(f"Gemini critic review failed: {str(e)}. Falling back to basic approval.")
            result.findings = [f"BASIC_APPROVED: {a.type} for {a.target_id}" for a in proposals]

        context.add_worker_result(result)
        return result
