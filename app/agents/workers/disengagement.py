import uuid
from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseWorker
from app.agents.context import AgentContext, WorkerResult, AgentAction
from app.models.patient import Patient
from app.schemas.thought_stream import ThoughtStage
from app.services.action_idempotency import get_patients_with_recent_actions
from app.utils.logger import logger

# Engagement action types for idempotency checking
ENGAGEMENT_ACTION_TYPES = ["onboarding_reminder", "engagement_nudge"]


class DisengagementWorker(BaseWorker):
    """
    Specialist for Patient Engagement.
    Flags patients who haven't submitted readings recently.
    """
    
    def __init__(self, db_session: AsyncSession = None):
        super().__init__("engagement_specialist")
        self.db = db_session

    async def run(self, context: AgentContext) -> WorkerResult:
        logger.info(f"Worker {self.name} checking patient activity")
        result = WorkerResult(worker_name=self.name)
        emitter = context.emitter
        
        patients = context.get("patients", [])
        now = datetime.now(timezone.utc)
        threshold_days = context.get("disengagement_threshold_days", 3)
        
        # IDEMPOTENCY: Get patients with recent actions to skip
        patients_with_recent_actions = {}
        if self.db:
            patients_with_recent_actions = await get_patients_with_recent_actions(
                self.db,
                context.organization_id,
                ENGAGEMENT_ACTION_TYPES
            )
        
        if emitter:
            await emitter.emit(
                agent_name=self.name,
                stage=ThoughtStage.SPECIALIST_ANALYSIS,
                content=f"📊 Checking engagement for {len(patients)} patients ({len(patients_with_recent_actions)} have recent actions)..."
            )
        
        engaged_count = 0
        disengaged_count = 0
        skipped_count = 0
        
        for patient in patients:
            patient_name = f"{patient.first_name} {patient.last_name}" if patient.first_name else str(patient.id)[:8]
            
            # IDEMPOTENCY: Skip patients with recent unresolved actions
            if patient.id in patients_with_recent_actions:
                skipped_count += 1
                continue
            
            last_reading = patient.last_reading_at
            
            if not last_reading:
                # Never had a reading
                disengaged_count += 1
                if emitter:
                    await emitter.emit(
                        agent_name=self.name,
                        stage=ThoughtStage.SPECIALIST_ANALYSIS,
                        content=f"🆕 {patient_name}: New patient - never submitted a health reading. Needs onboarding reminder.",
                        patient_id=patient.id
                    )
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
                disengaged_count += 1
                if emitter:
                    await emitter.emit(
                        agent_name=self.name,
                        stage=ThoughtStage.SPECIALIST_ANALYSIS,
                        content=f"😴 {patient_name}: No reading in {days_since} days. Risk of disengagement.",
                        patient_id=patient.id
                    )
                result.flagged_patients.append(patient.id)
                result.proposed_actions.append(AgentAction(
                    type="engagement_nudge",
                    target_id=str(patient.id),
                    reasoning=f"Patient hasn't submitted a reading in {days_since} days.",
                    content={"days_missing": days_since}
                ))
            else:
                engaged_count += 1
        
        if emitter:
            await emitter.emit(
                agent_name=self.name,
                stage=ThoughtStage.SPECIALIST_ANALYSIS,
                content=f"📈 Engagement check: {engaged_count} active, {disengaged_count} need attention, {skipped_count} skipped (recent action)."
            )
                
        context.add_worker_result(result)
        return result


