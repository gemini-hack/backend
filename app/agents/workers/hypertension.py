import uuid
from typing import List, Dict, Any
from app.agents.base import BaseWorker
from app.agents.context import AgentContext, WorkerResult, AgentAction
from app.models.patient import Condition, HealthReading
from sqlalchemy import select, and_
from app.utils.logger import logger

class HypertensionWorker(BaseWorker):
    """
    Specialist Doctor for Hypertension.
    Analyzes blood pressure readings and proposes actions.
    """
    
    def __init__(self, db_session):
        super().__init__("hypertension_specialist")
        self.db = db_session

    async def run(self, context: AgentContext) -> WorkerResult:
        logger.info(f"Worker {self.name} starting analysis for org {context.organization_id}")
        
        result = WorkerResult(worker_name=self.name)
        
        # Get patients with hypertension in this org
        # In a real scenario, we might get them from context if Supervisor already fetched them
        patients = context.get("patients", [])
        if not patients:
            # Fallback/Safety: If Supervisor didn't pre-fetch, we could fetch here
            # But according to PRD, Supervisor "shows patient list on whiteboard"
            logger.warning("No patients found on whiteboard for hypertension analysis")
            return result

        for patient in patients:
            if patient.primary_condition != Condition.HYPERTENSION:
                continue
            
            # Fetch latest readings for this patient
            query = (
                select(HealthReading)
                .where(HealthReading.patient_id == patient.id)
                .order_by(HealthReading.reading_time.desc())
                .limit(5)
            )
            reading_exec = await self.db.execute(query)
            readings = reading_exec.scalars().all()
            
            if not readings:
                result.findings.append(f"Patient {patient.id} has no recent BP readings.")
                continue
                
            latest = readings[0]
            # Hypertension logic (AHA Standards as per PRD)
            # value = systolic, secondary_value = diastolic (mapping from HealthReading model)
            systolic = latest.value
            diastolic = latest.secondary_value or 0
            
            if systolic >= 180 or diastolic >= 120:
                result.flagged_patients.append(patient.id)
                result.proposed_actions.append(AgentAction(
                    type="emergency_escalation",
                    target_id=str(patient.id),
                    details={
                        "systolic": systolic,
                        "diastolic": diastolic,
                        "severity": "CRITICAL"
                    },
                    reasoning=f"Hypertensive Crisis detected: {systolic}/{diastolic}",
                    confidence=1.0
                ))
            elif systolic >= 140 or diastolic >= 90:
                result.flagged_patients.append(patient.id)
                result.proposed_actions.append(AgentAction(
                    type="urgent_followup",
                    target_id=str(patient.id),
                    details={
                        "systolic": systolic,
                        "diastolic": diastolic,
                        "severity": "URGENT"
                    },
                    reasoning=f"High BP Stage 2 detected: {systolic}/{diastolic}",
                    confidence=0.9
                ))
            elif systolic >= 130 or diastolic >= 80:
                result.proposed_actions.append(AgentAction(
                    type="schedule_checkin",
                    target_id=str(patient.id),
                    details={"days_from_now": 7},
                    reasoning=f"High BP Stage 1: {systolic}/{diastolic}. Weekly follow-up recommended.",
                    confidence=0.8
                ))
        
        context.add_worker_result(result)
        return result
