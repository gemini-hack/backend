import uuid
from datetime import date, datetime
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseWorker
from app.agents.context import AgentContext, WorkerResult, AgentAction
from app.models.patient import Condition, PatientStatus
from app.utils.logger import logger

class HIVWorker(BaseWorker):
    """
    Specialist Doctor for HIV/ART Management.
    Analyzes Viral Load, CD4, and Refill status.
    """
    
    def __init__(self, db_session: AsyncSession):
        super().__init__("hiv_specialist")
        self.db = db_session

    async def run(self, context: AgentContext) -> WorkerResult:
        logger.info(f"Worker {self.name} starting HIV clinical review")
        result = WorkerResult(worker_name=self.name)
        
        patients = context.get("patients", [])
        if not patients:
            return result

        for patient in patients:
            if patient.primary_condition != Condition.HIV:
                continue
            
            # 1. Analyze Viral Load (Clinical Logic as per USER requirement)
            vl = patient.last_viral_load_result
            if vl is not None:
                if vl > 1000:
                    result.flagged_patients.append(patient.id)
                    result.proposed_actions.append(AgentAction(
                        type="unsuppressed_vl_intervention",
                        target_id=str(patient.id),
                        details={"viral_load": vl, "status": "UNSUPPRESSED"},
                        reasoning=f"Viral Load is {vl} (>1000). Patient is unsuppressed. Requires urgent adherence counseling.",
                        confidence=1.0
                    ))
                elif 50 <= vl <= 1000:
                    result.proposed_actions.append(AgentAction(
                        type="low_level_viremia_review",
                        target_id=str(patient.id),
                        details={"viral_load": vl, "status": "LLV"},
                        reasoning=f"Viral Load is {vl} (50-1000). Low level viremia detected. Monitor closely.",
                        confidence=0.8
                    ))
                elif vl < 50:
                    result.findings.append(f"Patient {patient.id} is undetectable (VL < 50). Excellent treatment response.")

            # 2. Analyze Treatment Status & Refills
            # (Note: Status auto-update logic is in the service, here we flag concerns)
            if patient.status == PatientStatus.ACTIVE_DEFAULTER:
                result.flagged_patients.append(patient.id)
                result.proposed_actions.append(AgentAction(
                    type="defaulter_tracing",
                    target_id=str(patient.id),
                    details={"last_refill": patient.last_refill_date, "next_refill": patient.next_refill_date},
                    reasoning="Patient missed refill date and is now an active defaulter.",
                    confidence=0.9
                ))
            elif patient.status == PatientStatus.IIT:
                result.flagged_patients.append(patient.id)
                result.proposed_actions.append(AgentAction(
                    type="iit_recovery_plan",
                    target_id=str(patient.id),
                    reasoning="Interrupted in Treatment (IIT) (>28 days since missed refill). High risk of drug resistance.",
                    confidence=1.0
                ))

        context.add_worker_result(result)
        return result
