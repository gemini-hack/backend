import uuid
from datetime import datetime, timedelta, timezone
from typing import List
from app.agents.base import BaseWorker
from app.agents.context import AgentContext, WorkerResult, AgentAction
from app.models.patient import Patient
from app.utils.logger import logger

class DisengagementWorker(BaseWorker):
    """
    Specialist for Patient Engagement.
    Flags patients who haven't submitted readings recently.
    """
    
    def __init__(self):
        super().__init__("engagement_specialist")

    async def run(self, context: AgentContext) -> WorkerResult:
        logger.info(f"Worker {self.name} checking patient activity")
        result = WorkerResult(worker_name=self.name)
        
        patients = context.get("patients", [])
        now = datetime.now(timezone.utc)
        threshold_days = context.get("disengagement_threshold_days", 3)
        
        for patient in patients:
            last_reading = patient.last_reading_at
            
            if not last_reading:
                # Never had a reading
                result.flagged_patients.append(patient.id)
                result.proposed_actions.append(AgentAction(
                    type="onboarding_reminder",
                    target_id=str(patient.id),
                    reasoning="Patient has never submitted a health reading since registration.",
                    content={"days_missing": "infinity"}
                ))
                continue
                
            days_since = (now - last_reading).days
            if days_since >= threshold_days:
                result.flagged_patients.append(patient.id)
                result.proposed_actions.append(AgentAction(
                    type="engagement_nudge",
                    target_id=str(patient.id),
                    reasoning=f"Patient hasn't submitted a reading in {days_since} days.",
                    content={"days_missing": days_since}
                ))
                
        context.add_worker_result(result)
        return result
