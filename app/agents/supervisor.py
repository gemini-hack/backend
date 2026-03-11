import uuid
import asyncio
import json
from datetime import datetime, timezone
from typing import List
from app.agents.base import BaseSupervisor, BaseWorker
from app.agents.context import AgentContext, AgentAction, ReflectionVerdict
from app.agents.thought_emitter import ThoughtEmitter
from app.schemas.thought_stream import ThoughtStage
from app.models.patient import Patient, PatientStatus
from sqlalchemy import select
from app.utils.logger import logger

from app.services.sms_service import SMSService
from app.services.email_service import EmailService
from app.models.patient import CommunicationPreference

# Timeout for individual Gemini API calls (seconds)
GEMINI_CALL_TIMEOUT = 30

# How long to wait for SSE clients to connect before starting
SSE_STARTUP_DELAY = 2

# Maximum rounds of Plan → Execute → Reflect (hard cap, non-negotiable)
MAX_ROUNDS = 3


class SupervisorAgent(BaseSupervisor):
    """
    Head Doctor. Coordinates rounds using a Plan → Execute → Reflect loop.

    Instead of a flat pipeline, the supervisor runs in bounded rounds:

    Round N:
      1. PLAN   — Decide which workers to run (round 1 = all, round 2+ = only gaps)
      2. EXECUTE — Run selected workers in parallel
      3. REFLECT — LLM evaluates: are the results complete? Any gaps?
         - If complete → proceed to synthesis
         - If gaps found AND rounds < MAX_ROUNDS → loop back to PLAN
         - If MAX_ROUNDS hit → proceed with what we have (escape hatch)

    After the loop:
      4. SYNTHESIZE — Merge all worker results into final actions
      5. CRITIC     — Safety gate (hard rules + LLM review)
      6. EXECUTE    — Auto-execute low-risk actions
    """

    def __init__(self, db_session, workers: List[BaseWorker]):
        super().__init__("head_doctor_supervisor", workers)
        self.db = db_session
        self.sms_service = SMSService()
        from app.services.notification_manager import NotificationManager
        self.notification_manager = NotificationManager(db_session)
        # Index workers by name for selective re-runs
        self._worker_map = {w.name: w for w in workers}

    async def run_cycle(self, organization_id: uuid.UUID, cycle_id: uuid.UUID = None) -> AgentContext:
        logger.info(f"Supervisor {self.name} starting morning rounds for organization {organization_id}")

        if cycle_id:
            context = AgentContext(organization_id=organization_id, cycle_id=cycle_id)
        else:
            context = AgentContext(organization_id=organization_id)

        emitter = ThoughtEmitter(context.cycle_id, organization_id)
        context.set_emitter(emitter)

        # Brief delay for SSE clients — thoughts are buffered locally regardless
        await asyncio.sleep(SSE_STARTUP_DELAY)

        await emitter.emit(
            agent_name=self.name,
            stage=ThoughtStage.LOADING_DATA,
            content="🏥 Beginning morning rounds for organization..."
        )

        # PHASE 0: Resolve outcomes from previous cycle
        from app.services.action_idempotency import detect_and_resolve_outcomes
        resolved_counts = await detect_and_resolve_outcomes(self.db, organization_id)

        if resolved_counts["total"] > 0:
            await emitter.emit(
                agent_name=self.name,
                stage=ThoughtStage.LOADING_DATA,
                content=f"✅ Auto-resolved {resolved_counts['total']} actions from previous rounds"
            )

        # PHASE 1: Load patient data (bounded query)
        query = select(Patient).where(
            Patient.organization_id == organization_id,
            Patient.status == PatientStatus.ACTIVE
        ).limit(500)
        result = await self.db.execute(query)
        patients = result.scalars().all()
        context.set("patients", patients)

        await emitter.emit(
            agent_name=self.name,
            stage=ThoughtStage.LOADING_DATA,
            content=f"📋 Loaded {len(patients)} active patients for analysis"
        )

        # ============================================================
        # PLAN → EXECUTE → REFLECT LOOP (bounded by MAX_ROUNDS)
        # ============================================================
        verdict: ReflectionVerdict | None = None

        for round_num in range(1, MAX_ROUNDS + 1):
            context.current_round = round_num

            await emitter.emit(
                agent_name=self.name,
                stage=ThoughtStage.SPECIALIST_ANALYSIS,
                content=f"🔄 Round {round_num}/{MAX_ROUNDS}: Planning analysis..."
            )

            # PLAN: Decide which workers to run this round
            if round_num == 1 or verdict is None:
                # First round: run all workers
                workers_to_run = list(self.workers)
            else:
                # Subsequent rounds: only re-run workers identified by reflection
                workers_to_run = [
                    self._worker_map[name]
                    for name in verdict.retry_workers
                    if name in self._worker_map
                ]
                if not workers_to_run:
                    logger.info(f"Round {round_num}: No workers to retry, breaking loop")
                    break

                # Inject any additional context from reflection into the whiteboard
                for key, value in verdict.additional_context.items():
                    context.set(key, value)

            # EXECUTE: Run selected workers
            await emitter.emit(
                agent_name=self.name,
                stage=ThoughtStage.SPECIALIST_ANALYSIS,
                content=f"🔬 Running {len(workers_to_run)} specialist(s): {', '.join(w.name for w in workers_to_run)}"
            )
            await self._run_workers(context, emitter, workers_to_run)

            context.add_step(
                step_name=f"round_{round_num}_execute",
                status="success",
                output={
                    "workers_run": [w.name for w in workers_to_run],
                    "total_proposals": sum(
                        len(r.proposed_actions)
                        for r in context.worker_results.values()
                    ),
                    "total_flagged": sum(
                        len(r.flagged_patients)
                        for r in context.worker_results.values()
                    )
                }
            )

            # REFLECT: Should we do another round?
            # Skip reflection on last allowed round (we must proceed regardless)
            if round_num >= MAX_ROUNDS:
                await emitter.emit(
                    agent_name=self.name,
                    stage=ThoughtStage.SPECIALIST_ANALYSIS,
                    content=f"⚠️ Max rounds ({MAX_ROUNDS}) reached. Proceeding with current results."
                )
                break

            verdict = await self._reflect(context, emitter)

            context.add_step(
                step_name=f"round_{round_num}_reflect",
                status="success",
                output={
                    "is_complete": verdict.is_complete,
                    "gaps": verdict.gaps,
                    "retry_workers": verdict.retry_workers,
                    "reasoning": verdict.reasoning
                }
            )

            if verdict.is_complete:
                await emitter.emit(
                    agent_name=self.name,
                    stage=ThoughtStage.SPECIALIST_ANALYSIS,
                    content=f"✅ Reflection: Analysis complete after {round_num} round(s). {verdict.reasoning}"
                )
                break
            else:
                await emitter.emit(
                    agent_name=self.name,
                    stage=ThoughtStage.SPECIALIST_ANALYSIS,
                    content=f"🔁 Reflection: Gaps found — {', '.join(verdict.gaps)}. Retrying: {', '.join(verdict.retry_workers)}"
                )

        # ============================================================
        # POST-LOOP: Synthesize → Critic → Execute
        # ============================================================

        # SYNTHESIZE
        await emitter.emit(
            agent_name=self.name,
            stage=ThoughtStage.SUPERVISOR_SYNTHESIS,
            content="🧠 Synthesizing specialist reports into final action plan..."
        )
        await self._synthesize_decisions(context)

        await emitter.emit(
            agent_name=self.name,
            stage=ThoughtStage.SUPERVISOR_SYNTHESIS,
            content=f"📝 Synthesis complete. {len(context.final_actions)} final actions decided."
        )

        # CRITIC (safety gate — runs BEFORE execution)
        await emitter.emit(
            agent_name="quality_doctor_critic",
            stage=ThoughtStage.CRITIC_REVIEW,
            content="🔍 Critic reviewing all proposed actions for safety..."
        )
        from app.agents.workers.critic import CriticWorker
        critic = CriticWorker()
        await critic.run(context)

        # AUTO-EXECUTE (only after critic approval)
        await emitter.emit(
            agent_name=self.name,
            stage=ThoughtStage.AUTO_EXECUTION,
            content="⚡ Executing automated low-risk actions..."
        )
        await self._execute_automated_actions(context)

        # COMPLETE
        await emitter.emit(
            agent_name=self.name,
            stage=ThoughtStage.COMPLETE,
            content=f"✅ Morning rounds complete. {len(context.final_actions)} actions ready. ({context.current_round} round(s), {len(context.step_history)} steps)",
            metadata={
                "action_count": len(context.final_actions),
                "cycle_id": str(context.cycle_id),
                "rounds": context.current_round,
                "steps": len(context.step_history)
            }
        )

        return context

    # ------------------------------------------------------------------
    # REFLECT — The LLM evaluates its own work
    # ------------------------------------------------------------------

    async def _reflect(self, context: AgentContext, emitter: ThoughtEmitter) -> ReflectionVerdict:
        """
        Reflection step: LLM evaluates whether the current round's results are
        sufficient, or if gaps exist that require re-running specific workers.

        Returns a ReflectionVerdict that drives the next iteration of the loop.
        Falls back to "complete" if Gemini fails (safe default — don't loop forever).
        """
        from app.services.ai_service import gemini_service

        await emitter.emit(
            agent_name=self.name,
            stage=ThoughtStage.SPECIALIST_ANALYSIS,
            content="🤔 Reflecting on analysis results..."
        )

        # Build a summary of what each worker found
        worker_summaries = {}
        for name, result in context.worker_results.items():
            worker_summaries[name] = {
                "findings_count": len(result.findings),
                "proposals_count": len(result.proposed_actions),
                "flagged_count": len(result.flagged_patients),
                "sample_findings": result.findings[:3],
                "action_types": list({a.type for a in result.proposed_actions})
            }

        patient_count = len(context.get("patients", []))

        system_instruction = (
            "You are MIRA's Head Supervisor reviewing the results of a specialist analysis round. "
            "Your job is to decide: is the analysis COMPLETE, or are there GAPS that require re-running specific specialists?\n\n"
            "RULES:\n"
            "1. If all active patients have been analyzed by the relevant specialists → COMPLETE.\n"
            "2. If a specialist returned 0 findings but there are patients matching its condition → GAP.\n"
            "3. If a specialist's analysis seems to have missed obvious cases (e.g. HIV specialist didn't flag any unsuppressed patients in a large cohort) → GAP.\n"
            "4. Do NOT request re-runs for workers that don't exist. Available workers: " + ", ".join(self._worker_map.keys()) + "\n"
            "5. Be conservative — only request re-runs if there's a clear gap. Extra rounds cost time and API calls.\n"
            "6. NEVER request more than 2 workers for retry.\n\n"
            "Output valid JSON matching this schema:\n"
            '{"is_complete": bool, "reasoning": str, "gaps": [str], "retry_workers": [str], "additional_context": {}}'
        )

        prompt = (
            f"Round {context.current_round} results for Organization {context.organization_id}:\n"
            f"Total patients: {patient_count}\n"
            f"Worker results: {json.dumps(worker_summaries, indent=2, default=str)}\n"
            f"Step history: {json.dumps([s.model_dump() for s in context.step_history], indent=2, default=str)}\n\n"
            "Is this analysis complete or are there gaps requiring another round?"
        )

        try:
            response = await asyncio.wait_for(
                gemini_service.get_structured_response(prompt, system_instruction),
                timeout=GEMINI_CALL_TIMEOUT
            )

            # Validate retry_workers against actual available workers
            retry_workers = response.get("retry_workers", [])
            valid_retries = [w for w in retry_workers if w in self._worker_map]
            if len(valid_retries) != len(retry_workers):
                invalid = set(retry_workers) - set(valid_retries)
                logger.warning(f"Reflection requested non-existent workers: {invalid}")
            response["retry_workers"] = valid_retries[:2]  # Cap at 2

            verdict = ReflectionVerdict(**response)
            logger.info(f"Reflection verdict: complete={verdict.is_complete}, gaps={verdict.gaps}, retry={verdict.retry_workers}")
            return verdict

        except asyncio.TimeoutError:
            logger.error(f"Reflection timed out after {GEMINI_CALL_TIMEOUT}s. Defaulting to complete.")
            return ReflectionVerdict(is_complete=True, reasoning="Reflection timed out — proceeding with current results")
        except Exception as e:
            logger.error(f"Reflection failed: {e}. Defaulting to complete.")
            return ReflectionVerdict(is_complete=True, reasoning=f"Reflection error: {str(e)[:100]} — proceeding with current results")

    # ------------------------------------------------------------------
    # EXECUTE WORKERS
    # ------------------------------------------------------------------

    async def _run_workers(self, context: AgentContext, emitter: ThoughtEmitter, workers: List[BaseWorker] = None):
        """Run specified workers in parallel with rate limiting and retries."""
        workers = workers or self.workers
        base_delay = 4
        max_retries = 3
        gemini_semaphore = asyncio.Semaphore(2)

        async def _run_single_worker(worker):
            """Run a single worker with retry logic and rate limiting."""
            retries = 0
            delay = base_delay

            await emitter.emit(
                agent_name=self.name,
                stage=ThoughtStage.SPECIALIST_ANALYSIS,
                content=f"🔬 Dispatching {worker.name.replace('_', ' ').title()} specialist..."
            )

            worker_result = None
            while retries <= max_retries:
                try:
                    async with gemini_semaphore:
                        logger.info(f"📊 [{worker.name.upper()}] Specialist analyzing patient data...")
                        worker_result = await asyncio.wait_for(
                            worker.run(context),
                            timeout=GEMINI_CALL_TIMEOUT * 2
                        )

                    if worker_result:
                        await emitter.emit(
                            agent_name=worker.name,
                            stage=ThoughtStage.SPECIALIST_ANALYSIS,
                            content=f"✅ Analysis complete. {len(worker_result.proposed_actions)} actions proposed, {len(worker_result.flagged_patients)} patients flagged."
                        )

                    await asyncio.sleep(base_delay)
                    break
                except asyncio.TimeoutError:
                    logger.error(f"Specialist {worker.name} timed out after {GEMINI_CALL_TIMEOUT * 2}s")
                    await emitter.emit(
                        agent_name=worker.name,
                        stage=ThoughtStage.ERROR,
                        content="❌ Specialist timed out"
                    )
                    break
                except Exception as e:
                    error_str = str(e)
                    if "RESOURCE_EXHAUSTED" in error_str and retries < max_retries:
                        retries += 1
                        delay = base_delay * (2 ** retries)
                        logger.warning(f"Rate limit hit for {worker.name}. Retry {retries}/{max_retries} after {delay}s backoff...")
                        await emitter.emit(
                            agent_name=worker.name,
                            stage=ThoughtStage.ERROR,
                            content=f"⏳ Rate limited. Retrying in {delay}s..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"Specialist {worker.name} failed during rounds: {error_str}")
                        await emitter.emit(
                            agent_name=worker.name,
                            stage=ThoughtStage.ERROR,
                            content=f"❌ Specialist failed: {error_str[:100]}"
                        )
                        break

            return worker_result

        results = await asyncio.gather(
            *[_run_single_worker(w) for w in workers],
            return_exceptions=True
        )

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Worker {workers[i].name} raised exception: {result}")

    # ------------------------------------------------------------------
    # AUTO-EXECUTION
    # ------------------------------------------------------------------

    async def _execute_automated_actions(self, context: AgentContext):
        """
        Executes low-risk, high-confidence actions immediately.
        Only runs AFTER critic review has had a chance to downgrade confidence.
        """
        actions_to_keep = []

        for action in context.final_actions:
            safe_types = ["engagement_nudge", "schedule_appointment_reminder"]

            if action.type in safe_types and action.confidence >= 0.9:
                try:
                    logger.info(f"AUTONOMOUSLY EXECUTING: {action.type} for {action.target_id}")

                    patient = await Patient.fetch_unique(self.db, id=uuid.UUID(action.target_id))

                    if not action.content:
                        action.content = {}

                    if action.type == "engagement_nudge":
                        method = patient.preferred_contact_method if patient else CommunicationPreference.SMS

                        if method == CommunicationPreference.EMAIL and patient and patient.email:
                            email_service = EmailService(self.db)
                            await email_service._send(
                                to_email=patient.email,
                                subject="How are you doing today?",
                                html_content=f"Hi {patient.first_name}, <br><br>We noticed you haven't checked in recently. Are you okay? Please reply to let us know."
                            )
                            action.content["execution_status"] = "EMAIL_SENT_AUTOMATICALLY"
                            action.status = "completed"
                            logger.info(f"✅ Email Nudge sent to {patient.email}")

                        elif patient and patient.phone:
                            await self.sms_service.send_generic_sms(
                                to_phone=patient.phone,
                                message_body="Hi, MIRA here. We noticed you haven't checked in recently. Are you okay? Reply YES if you need a call.",
                                organization_id=str(context.organization_id)
                            )
                            action.content["execution_status"] = "SMS_SENT_AUTOMATICALLY"
                            action.status = "completed"
                            logger.info(f"✅ SMS Nudge sent to {patient.phone}")
                        else:
                            action.content["execution_error"] = "No contact info (Phone/Email) found"

                    elif action.type == "schedule_appointment_reminder":

                        from app.models.appointment import Appointment, AppointmentStatus
                        from app.models.reminder import AppointmentReminder, ReminderChannel

                        query = select(Appointment).where(
                            Appointment.patient_id == patient.id,
                            Appointment.status == AppointmentStatus.SCHEDULED,
                            Appointment.scheduled_time > datetime.now(timezone.utc)
                        ).order_by(Appointment.scheduled_time.asc()).limit(1)

                        result = await self.db.execute(query)
                        next_appt = result.scalar_one_or_none()

                        if next_appt:
                            reminder = AppointmentReminder(
                                appointment_id=next_appt.id,
                                patient_id=patient.id,
                                organization_id=context.organization_id,
                                channels=[ReminderChannel.SMS, ReminderChannel.EMAIL],
                                scheduled_send_time=datetime.now(timezone.utc),
                                idempotency_key=str(uuid.uuid4()),
                                created_by_agent="supervisor_auto"
                            )
                            self.db.add(reminder)
                            await self.db.flush()

                            sent_success = await self.notification_manager.send_appointment_reminder(reminder, patient, next_appt)

                            if sent_success:
                                action.content["execution_status"] = "REMINDER_SENT_AUTOMATICALLY"
                                action.content["appointment_id"] = str(next_appt.id)
                                action.status = "completed"
                            else:
                                action.content["execution_status"] = "FAILED_AT_NOTIFICATION_MANAGER"
                        else:
                            logger.warning(f"Cannot remind {patient.first_name}: No upcoming appointment.")
                            action.status = "escalated"
                            action.content["execution_error"] = "No upcoming appointment found."
                            action.content["suggested_next_step"] = "schedule_checkin"

                except Exception as e:
                    logger.error(f"Failed to auto-execute {action.type}: {e}")
                    if not action.content:
                        action.content = {}
                    action.content["execution_error"] = str(e)

            actions_to_keep.append(action)

        context.final_actions = actions_to_keep

    # ------------------------------------------------------------------
    # SYNTHESIS
    # ------------------------------------------------------------------

    async def _synthesize_decisions(self, context: AgentContext):
        """
        Uses Gemini to synthesize all specialist reports and make final decisions.
        Falls back to rule-based synthesis if Gemini fails or times out.
        """
        from app.services.ai_service import gemini_service

        reports = []
        for worker_name, result in context.worker_results.items():
            reports.append({
                "worker": worker_name,
                "findings": result.findings,
                "proposals": [p.model_dump() for p in result.proposed_actions]
            })

        system_instruction = (
            "You are MIRA's Head Supervisor, the strategic lead of an autonomous medical AI team. "
            "Your goal is to synthesize specialist reports into a definitive, prioritized Action Plan. "

            "### CRITICAL CONTEXT RULES\n"
            "1. **Newly Identified Clients (Diagnosed < 6 months):** \n"
            "   - Primary Goal: Retention & ART Initiation.\n"
            "   - If no ART start date exists, you MUST generate an 'initiate_art' action.\n"
            "   - Reasoning must explicitly state: 'Newly Identified Client - Priority: Onboarding'.\n"
            "2. **Returning Clients (Diagnosed > 6 months):** \n"
            "   - Primary Goal: Adherence (Viral Load) & Convenience.\n"
            "   - If stable (VL < 50), focus on 'schedule_appointment_reminder' or 'refill_reminder'.\n"
            "   - Reasoning must explicitly state: 'Returning Stable Client - Priority: Maintenance'.\n"
            "3. **Regimen Safety (The Green List):** \n"
            "   - If a specialist flags a regimen as 'Red' or 'Phased Out' (e.g., Nevirapine), you MUST generate a 'regimen_optimization' action.\n"

            "### AUTONOMY THRESHOLDS\n"
            "- **Auto-Execute (Confidence > 0.9):** Routine tasks (SMS nudges, reminders). These will happen without human approval.\n"
            "- **Human Review (Confidence < 0.9):** Clinical decisions (changing meds, diagnosis, IIT recovery plans). These require a human doctor.\n"

            "Output valid JSON only."
        )

        prompt = (
            f"Analyze these reports for Organization {context.organization_id}:\n"
            f"{json.dumps(reports, indent=2, default=str)}\n\n"
            "Produce a final list of actions. For each action, include a 'reasoning' field that explicitly mentions "
            "if the patient is 'Newly Identified' or a 'Returning Client' based on their history. "
            "Available types: emergency_escalation, urgent_followup, schedule_appointment_reminder, engagement_nudge, "
            "regimen_optimization, initiate_art, defaulter_tracing."
        )

        try:
            response = await asyncio.wait_for(
                gemini_service.get_structured_response(prompt, system_instruction),
                timeout=GEMINI_CALL_TIMEOUT
            )

            actions_data = response if isinstance(response, list) else response.get("actions", [])

            if not isinstance(actions_data, list):
                logger.warning(f"Gemini returned unexpected structure: {type(actions_data)}. Falling back to rule-based.")
                self._rule_based_synthesis(context)
                return

            clean_actions = []
            for action_data in actions_data:
                try:
                    if "action_type" in action_data and "type" not in action_data:
                        action_data["type"] = action_data.pop("action_type")

                    if "content" not in action_data or action_data["content"] is None:
                        action_data["content"] = action_data.get("details", {})

                    if "type" not in action_data or "target_id" not in action_data:
                        logger.warning(f"Skipping malformed action from Gemini: {action_data}")
                        continue
                    if "reasoning" not in action_data:
                        action_data["reasoning"] = "No reasoning provided by LLM"

                    clean_actions.append(AgentAction(**action_data))
                except Exception as e:
                    logger.warning(f"Skipping invalid action from Gemini: {e}")
                    continue

            context.final_actions = clean_actions
            logger.info(f"LLM Synthesis complete. Final action count: {len(context.final_actions)}")

        except asyncio.TimeoutError:
            logger.error(f"Gemini synthesis timed out after {GEMINI_CALL_TIMEOUT}s. Falling back to rule-based synthesis.")
            self._rule_based_synthesis(context)
        except Exception as e:
            logger.error(f"Gemini synthesis failed: {str(e)}. Falling back to rule-based synthesis.")
            self._rule_based_synthesis(context)

    def _rule_based_synthesis(self, context: AgentContext):
        """Fallback rule-based synthesis. Deduplicates by patient, keeping highest priority action."""
        all_proposals = []
        for worker_result in context.worker_results.values():
            all_proposals.extend(worker_result.proposed_actions)

        priority_map = {
            "emergency_escalation": 100, "iit_recovery_plan": 95,
            "unsuppressed_vl_intervention": 90, "urgent_followup": 80,
            "defaulter_tracing": 70, "schedule_checkin": 50,
            "low_level_viremia_review": 40, "engagement_nudge": 20,
            "onboarding_reminder": 10
        }

        final_actions_map = {}
        for proposal in all_proposals:
            existing = final_actions_map.get(proposal.target_id)
            if not existing or priority_map.get(proposal.type, 0) > priority_map.get(existing.type, 0):
                final_actions_map[proposal.target_id] = proposal

        context.final_actions = list(final_actions_map.values())
        logger.info(f"Rule-based synthesis complete. Final action count: {len(context.final_actions)}")
