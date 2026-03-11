import asyncio

from app.agents.base import BaseWorker
from app.agents.context import AgentContext, WorkerResult
from app.utils.logger import logger

# Timeout for critic Gemini call (seconds)
CRITIC_TIMEOUT = 30

# Action types that require human review — AI cannot auto-execute clinical decisions
CLINICAL_ACTION_TYPES = {
    "initiate_art", "regimen_optimization", "iit_recovery_plan",
    "unsuppressed_vl_intervention", "emergency_escalation"
}

# Confidence floor for clinical actions — forces human review
CLINICAL_CONFIDENCE_CAP = 0.5


class CriticWorker(BaseWorker):
    """
    Quality Doctor.
    Reviews proposed actions for safety, protocol adherence, and clinical common sense.

    IMPORTANT: This worker runs BEFORE auto-execution and actively mutates
    context.final_actions to enforce safety constraints:
    - Downgrades confidence on clinical actions to force human review
    - Marks rejected actions so they are not auto-executed
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
            context.add_worker_result(result)
            return result

        # STEP 1: Hard safety rules (always applied, no LLM needed)
        self._enforce_clinical_safety(context, result)

        # STEP 2: LLM review for nuanced checks
        system_instruction = (
            "You are the Quality Assurance Doctor. You are the final safety barrier between AI and Patient. "
            "Review the Supervisor's proposed actions for Clinical Safety and Guideline Adherence. "

            "### SAFETY AUDIT CHECKLIST\n"
            "1. **Regimen Integrity:** Did the team miss a patient on a banned drug (Nevirapine/d4T)? If yes, REJECT the plan and demand 'regimen_optimization'.\n"
            "2. **Viral Load Logic:** If VL > 1000, is there an active intervention plan (Counseling/Switch)? If not, REJECT.\n"
            "3. **Autonomy Check:** Did the Supervisor mark a CLINICAL action (like 'initiate_art') for auto-execution (confidence > 0.9)? \n"
            "   - If yes, DOWNGRADE confidence to 0.5 to force Human Review. AI cannot prescribe medication autonomously.\n"

            "Output valid JSON. Return a JSON object with a 'reviews' key containing a list of reviews. "
            "Each review: {'target_id': str, 'action_type': str, 'decision': 'APPROVED'|'REJECTED'|'DOWNGRADE', 'reasoning': str, 'new_confidence': float|null}"
        )

        prompt = (
            "Review the following proposed actions for patients in this cycle:\n"
            f"{json.dumps([a.model_dump() for a in proposals], indent=2, default=str)}\n\n"
            "Return a list of reviews. Each review should include: "
            "'target_id', 'action_type', 'decision' (APPROVED/REJECTED/DOWNGRADE), "
            "'reasoning', and 'new_confidence' (float, only if DOWNGRADE)."
        )

        try:
            reviews = await asyncio.wait_for(
                gemini_service.get_structured_response(prompt, system_instruction),
                timeout=CRITIC_TIMEOUT
            )

            review_list = reviews if isinstance(reviews, list) else reviews.get("reviews", [])

            # Apply LLM review decisions to actual actions
            review_map = {}
            for r in review_list:
                if isinstance(r, dict) and "target_id" in r:
                    key = (r.get("target_id"), r.get("action_type"))
                    review_map[key] = r

            for action in context.final_actions:
                key = (action.target_id, action.type)
                review = review_map.get(key)
                if not review:
                    continue

                decision = review.get("decision", "").upper()
                reasoning = review.get("reasoning", "")

                if decision == "REJECTED":
                    action.status = "rejected_by_critic"
                    action.confidence = 0.0
                    result.findings.append(f"REJECTED: {action.type} for {action.target_id} - {reasoning}")
                    logger.warning(f"Critic REJECTED {action.type} for {action.target_id}: {reasoning}")

                elif decision == "DOWNGRADE":
                    new_conf = review.get("new_confidence", CLINICAL_CONFIDENCE_CAP)
                    if isinstance(new_conf, (int, float)) and new_conf < action.confidence:
                        action.confidence = float(new_conf)
                    result.findings.append(f"DOWNGRADED: {action.type} for {action.target_id} to confidence {action.confidence} - {reasoning}")

                else:
                    result.findings.append(f"APPROVED: {action.type} for {action.target_id} - {reasoning}")

            logger.info(f"Critic review complete. {len(review_list)} actions reviewed.")

        except asyncio.TimeoutError:
            logger.error(f"Gemini critic review timed out after {CRITIC_TIMEOUT}s. Hard safety rules still applied.")
            result.findings = [f"TIMEOUT_BASIC_APPROVED: {a.type} for {a.target_id}" for a in proposals]
        except Exception as e:
            logger.error(f"Gemini critic review failed: {str(e)}. Hard safety rules still applied.")
            result.findings = [f"FALLBACK_BASIC_APPROVED: {a.type} for {a.target_id}" for a in proposals]

        context.add_worker_result(result)
        return result

    def _enforce_clinical_safety(self, context: AgentContext, result: WorkerResult):
        """
        Hard safety rules — always applied regardless of LLM availability.
        Clinical actions must never auto-execute. This is not negotiable.
        """
        for action in context.final_actions:
            if action.type in CLINICAL_ACTION_TYPES and action.confidence > CLINICAL_CONFIDENCE_CAP:
                original_confidence = action.confidence
                action.confidence = CLINICAL_CONFIDENCE_CAP
                result.findings.append(
                    f"SAFETY_DOWNGRADE: {action.type} for {action.target_id} "
                    f"confidence {original_confidence} -> {CLINICAL_CONFIDENCE_CAP} "
                    f"(clinical actions require human review)"
                )
                logger.info(
                    f"Critic hard rule: downgraded {action.type} confidence "
                    f"{original_confidence} -> {CLINICAL_CONFIDENCE_CAP} for patient {action.target_id}"
                )
