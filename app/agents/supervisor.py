import uuid
import asyncio
import json
from datetime import datetime, timezone
from typing import List, Dict, Any
from app.agents.base import BaseSupervisor, BaseWorker
from app.agents.context import AgentContext, AgentAction
from app.models.patient import Patient, PatientStatus
from sqlalchemy import select
from app.utils.logger import logger

from app.services.sms_service import SMSService
from app.services.email_service import EmailService
from app.models.patient import Patient, PatientStatus, CommunicationPreference

class SupervisorAgent(BaseSupervisor):
    """
    Head Doctor. Coordinates rounds and executes autonomous actions.
    """
    
    def __init__(self, db_session, workers: List[BaseWorker]):
        super().__init__("head_doctor_supervisor", workers)
        self.db = db_session
        # Initialize services
        self.sms_service = SMSService()
        from app.services.notification_manager import NotificationManager
        self.notification_manager = NotificationManager(db_session)

    async def run_cycle(self, organization_id: uuid.UUID) -> AgentContext:
        logger.info(f"Supervisor {self.name} starting morning rounds for organization {organization_id}")
        
        # 1. Create Context & Fetch Patients
        context = AgentContext(organization_id=organization_id)
        
        # Fetch relevant patients
        query = select(Patient).where(
            Patient.organization_id == organization_id,
            Patient.status == PatientStatus.ACTIVE
        )
        result = await self.db.execute(query)
        patients = result.scalars().all()
        context.set("patients", patients)
        
        # 2. Run Workers
        for worker in self.workers:
            try:
                logger.info(f"📊 [{worker.name.upper()}] Specialist analyzing patient data...")
                await worker.run(context)
                # Sleep for 4 seconds to stay under the ~15 RPM limit (60s / 15 = 4s)
                logger.debug("Sleeping for 4s to respect Gemini Rate Limit...")
                await asyncio.sleep(4)
            except Exception as e:
                logger.error(f"Specialist {worker.name} failed during rounds: {str(e)}")

        # 3. Synthesize Decisions (The Brain)
        await self._synthesize_decisions(context)
        
        # 4. EXECUTION PHASE (The Hands - Autonomy)
        await self._execute_automated_actions(context)

        # 5. Quality Control
        from app.agents.workers.critic import CriticWorker
        critic = CriticWorker()
        await critic.run(context)
        
        return context

    async def _execute_automated_actions(self, context: AgentContext):
        """
        Executes low-risk, high-confidence actions immediately.
        """
        actions_to_keep = []

        for action in context.final_actions:
            # AUTONOMY RULES:
            # 1. Safe types: Nudges, Reminders
            # 2. High confidence: > 0.9
            safe_types = ["engagement_nudge", "schedule_appointment_reminder"]
            
            if action.type in safe_types and action.confidence >= 0.9:
                try:
                    logger.info(f"AUTONOMOUSLY EXECUTING: {action.type} for {action.target_id}")
                    
                    # Fetch patient to get phone number
                    patient = await Patient.fetch_unique(self.db, id=uuid.UUID(action.target_id))

                    if not action.content:
                        action.content = {}
                    
                    if action.type == "engagement_nudge":
                        # Use preferred method or fallback to SMS
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
                        # Fetch or create the relevant reminder/appointment context
                        # For now, we assume the action details contain enough info to trigger a general reminder
                        # OR we trigger a specific logic if we had the appointment ID.
                        
                        # However, NotificationManager requires an Appointment object.
                        # If the action is just "remind this patient", we might need to find their next appointment.
                        from app.models.appointment import Appointment, AppointmentStatus
                        from app.models.reminder import AppointmentReminder, ReminderChannel
                        
                        # Find next upcoming appointment
                        query = select(Appointment).where(
                            Appointment.patient_id == patient.id,
                            Appointment.status == AppointmentStatus.SCHEDULED,
                            Appointment.scheduled_time > datetime.now(timezone.utc)
                        ).order_by(Appointment.scheduled_time.asc()).limit(1)
                        
                        result = await self.db.execute(query)
                        next_appt = result.scalar_one_or_none()
                        
                        if next_appt:
                            # Create reminder record
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
                            
                            # Execute and CHECK RESULT
                            sent_success = await self.notification_manager.send_appointment_reminder(reminder, patient, next_appt)
                            
                            if sent_success:
                                action.content["execution_status"] = "REMINDER_SENT_AUTOMATICALLY"
                                action.content["appointment_id"] = str(next_appt.id)
                                action.status = "completed"
                            else:
                                action.content["execution_status"] = "FAILED_AT_NOTIFICATION_MANAGER"
                                # We don't mark as completed, so a human sees it pending
                        else:
                             action.content["execution_error"] = "No upcoming appointment found."

                except Exception as e:
                    logger.error(f"Failed to auto-execute {action.type}: {e}")
                    action.content["execution_error"] = str(e)
            
            # Keep action in context so the Critic/Human knows it happened
            actions_to_keep.append(action)

        context.final_actions = actions_to_keep

    async def _synthesize_decisions(self, context: AgentContext):
        """
        Uses Gemini Pro to synthesize all specialist reports and make final decisions.
        """
        from app.services.ai_service import gemini_service
        import json
        
        # Prepare the specialist reports for the prompt
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
            response = await gemini_service.get_structured_response(prompt, system_instruction)
            
            # The response should be a list of actions or a dict containing a list
            actions_data = response if isinstance(response, list) else response.get("actions", [])
            
            clean_actions = []
            for action_data in actions_data:
                # --- FIX: Map 'action_type' (DB/LLM) to 'type' (Pydantic) ---
                if "action_type" in action_data and "type" not in action_data:
                    action_data["type"] = action_data.pop("action_type")
                
                # --- FIX: Ensure content is present ---
                if "content" not in action_data or action_data["content"] is None:
                    # If 'details' exists (old format), rename it to 'content'
                    if "details" in action_data:
                         action_data["content"] = action_data.pop("details")
                    else:
                         action_data["content"] = {}

                # Create the object
                clean_actions.append(AgentAction(**action_data))
            
            context.final_actions = clean_actions
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
