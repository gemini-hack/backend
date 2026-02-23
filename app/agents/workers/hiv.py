from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.base import BaseWorker
from app.agents.context import AgentContext, WorkerResult, AgentAction
from app.models.patient import PatientStatus
from app.models.conditions import Condition
from app.core.medical_guidelines import is_regimen_valid
from app.schemas.thought_stream import ThoughtStage
from app.services.action_idempotency import get_patients_with_recent_actions
from app.utils.logger import logger

# HIV action types for idempotency checking
HIV_ACTION_TYPES = [
    "unsuppressed_vl_intervention",
    "low_level_viremia_review", 
    "defaulter_tracing",
    "iit_recovery_plan",
    "regimen_optimization",
    "initiate_art"
]


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
        emitter = context.emitter  # Get the thought emitter
        
        patients = context.get("patients", [])
        if not patients:
            return result

        # Load hiv_profiles for HIV patients 
        from app.models.patient import Patient
        hiv_patient_ids = [p.id for p in patients if p.primary_condition == Condition.HIV]
        
        # IDEMPOTENCY: Get patients with recent actions to skip
        patients_with_recent_actions = await get_patients_with_recent_actions(
            self.db,
            context.organization_id,
            HIV_ACTION_TYPES
        )
        
        if emitter:
            await emitter.emit(
                agent_name=self.name,
                stage=ThoughtStage.SPECIALIST_ANALYSIS,
                content=f"🔬 Starting HIV review for {len(hiv_patient_ids)} HIV patients ({len(patients_with_recent_actions)} have recent actions, will skip duplicates)..."
            )
        
        if hiv_patient_ids:
            # Eager load hiv_profiles
            query = (
                select(Patient)
                .where(Patient.id.in_(hiv_patient_ids))
                .options(selectinload(Patient.hiv_profile))
            )
            result_set = await self.db.execute(query)
            loaded_patients = {p.id: p for p in result_set.scalars().all()}
        else:
            loaded_patients = {}

        analyzed_count = 0
        skipped_count = 0
        for patient in patients:
            if patient.primary_condition != Condition.HIV:
                continue
            
            analyzed_count += 1
            
            # IDEMPOTENCY: Skip patients with recent unresolved actions
            if patient.id in patients_with_recent_actions:
                skipped_count += 1
                if emitter:
                    await emitter.emit(
                        agent_name=self.name,
                        stage=ThoughtStage.SPECIALIST_ANALYSIS,
                        content=f"⏭️ Skipping patient (recent action pending): {str(patient.id)[:8]}",
                        patient_id=patient.id
                    )
                continue
            
            # Use the loaded patient with eager-loaded profile
            loaded_patient = loaded_patients.get(patient.id, patient)
            
            # Ensure hiv_profile is loaded (usually it is from Supervisor or Service)
            profile = loaded_patient.hiv_profile
            if not profile:
                logger.warning(f"Patient {patient.id} has HIV as primary condition but no HIVProfile")
                continue

            patient_name = f"{patient.first_name} {patient.last_name}" if patient.first_name else str(patient.id)[:8]

            # 1. Analyze Viral Load
            vl = profile.last_viral_load_result
            if vl is not None:
                if vl > 1000:
                    if emitter:
                        await emitter.emit(
                            agent_name=self.name,
                            stage=ThoughtStage.SPECIALIST_ANALYSIS,
                            content=f"⚠️ {patient_name}: VL={vl} copies/ml (UNSUPPRESSED). High risk. Requires urgent adherence counseling.",
                            patient_id=patient.id
                        )
                    result.flagged_patients.append(patient.id)
                    result.proposed_actions.append(AgentAction(
                        type="unsuppressed_vl_intervention",
                        target_id=str(patient.id),
                        content={"viral_load": vl, "status": "UNSUPPRESSED"},
                        reasoning=f"Viral Load is {vl} (>1000). Patient is unsuppressed. Requires urgent adherence counseling.",
                        confidence=1.0
                    ))
                elif 50 <= vl <= 1000:
                    if emitter:
                        await emitter.emit(
                            agent_name=self.name,
                            stage=ThoughtStage.SPECIALIST_ANALYSIS,
                            content=f"⚡ {patient_name}: VL={vl} copies/ml (Low Level Viremia). Needs close monitoring.",
                            patient_id=patient.id
                        )
                    result.proposed_actions.append(AgentAction(
                        type="low_level_viremia_review",
                        target_id=str(patient.id),
                        content={"viral_load": vl, "status": "LLV"},
                        reasoning=f"Viral Load is {vl} (50-1000). Low level viremia detected. Monitor closely.",
                        confidence=0.8
                    ))
                elif vl < 50:
                    if emitter:
                        await emitter.emit(
                            agent_name=self.name,
                            stage=ThoughtStage.SPECIALIST_ANALYSIS,
                            content=f"✅ {patient_name}: VL<50 copies/ml (UNDETECTABLE). Excellent response!",
                            patient_id=patient.id
                        )
                    result.findings.append(f"Patient {patient.id} is undetectable (VL < 50). Excellent treatment response.")

            # 2. Analyze Treatment Status & Refills
            # (Note: Status auto-update logic is in the service, here we flag concerns)
            if patient.status == PatientStatus.ACTIVE_DEFAULTER:
                if emitter:
                    await emitter.emit(
                        agent_name=self.name,
                        stage=ThoughtStage.SPECIALIST_ANALYSIS,
                        content=f"🚨 {patient_name}: DEFAULTER! Missed refill date. Needs tracing.",
                        patient_id=patient.id
                    )
                result.flagged_patients.append(patient.id)
                result.proposed_actions.append(AgentAction(
                    type="defaulter_tracing",
                    target_id=str(patient.id),
                    content={"last_refill": profile.last_refill_date, "next_refill": profile.next_refill_date},
                    reasoning="Patient missed refill date and is now an active defaulter.",
                    confidence=0.9
                ))
            elif patient.status == PatientStatus.IIT:
                if emitter:
                    await emitter.emit(
                        agent_name=self.name,
                        stage=ThoughtStage.SPECIALIST_ANALYSIS,
                        content=f"🆘 {patient_name}: IIT (>28 days since missed refill). HIGH RISK of drug resistance!",
                        patient_id=patient.id
                    )
                result.flagged_patients.append(patient.id)
                result.proposed_actions.append(AgentAction(
                    type="iit_recovery_plan",
                    target_id=str(patient.id),
                    reasoning="Interrupted in Treatment (IIT) (>28 days since missed refill). High risk of drug resistance.",
                    confidence=1.0
                ))

            # 3. Regimen Safety Check
            current_regimen = profile.current_art_regimen
            
            if current_regimen:
                if not is_regimen_valid(current_regimen):
                    if emitter:
                        await emitter.emit(
                            agent_name=self.name,
                            stage=ThoughtStage.SPECIALIST_ANALYSIS,
                            content=f"💊 {patient_name}: On '{current_regimen}' - NOT on approved Green List. Consider switch to TLD.",
                            patient_id=patient.id
                        )
                    result.flagged_patients.append(patient.id)
                    result.proposed_actions.append(AgentAction(
                        type="regimen_optimization",
                        target_id=str(patient.id),
                        content={"current_regimen": current_regimen, "issue": "Regimen not in approved Green List"},
                        reasoning=f"Patient is on '{current_regimen}', which is not a currently approved Green List regimen. Evaluate for switch to TLD or approved alternative.",
                        confidence=1.0 
                    ))
            else:
                 # Logic for newly identified client with no regimen
                 if patient.status == PatientStatus.ACTIVE and not profile.art_start_date:
                     if emitter:
                         await emitter.emit(
                             agent_name=self.name,
                             stage=ThoughtStage.SPECIALIST_ANALYSIS,
                             content=f"🆕 {patient_name}: Newly diagnosed HIV+, not yet on ART. Immediate initiation recommended!",
                             patient_id=patient.id
                         )
                     result.flagged_patients.append(patient.id)
                     result.proposed_actions.append(AgentAction(
                        type="initiate_art",
                        target_id=str(patient.id),
                        content={"recommended": "TDF(300mg)+3TC(300mg)+DTG(50mg)"},
                        reasoning="Newly identified HIV+ client not yet on ART. Immediate initiation recommended.",
                        confidence=1.0
                     ))

        if emitter:
            await emitter.emit(
                agent_name=self.name,
                stage=ThoughtStage.SPECIALIST_ANALYSIS,
                content=f"📊 HIV Review complete: {analyzed_count} patients analyzed, {len(result.proposed_actions)} interventions proposed."
            )

        context.add_worker_result(result)
        return result

