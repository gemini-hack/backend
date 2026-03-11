"""
Follow-Up Specialist Agent.

Identifies upcoming appointments and schedules intelligent reminders
based on patient preferences, urgency, and no-show history.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload

from app.agents.base import BaseWorker
from app.agents.context import AgentContext, WorkerResult, AgentAction
from app.models.appointment import Appointment, AppointmentStatus
from app.models.patient import Patient, CommunicationPreference
from app.models.reminder import AppointmentReminder, ReminderChannel, ReminderStatus
from app.schemas.thought_stream import ThoughtStage
from app.utils.logger import logger


class FollowUpSpecialist(BaseWorker):
    """
    Specialist Doctor for Appointment Follow-Up.
    
    Responsibilities:
    - Identifies upcoming appointments (next 72 hours)
    - Determines optimal reminder strategy per patient
    - Proposes reminder scheduling with channel preferences
    - Escalates no-show risk patients to voice calls
    
    Smart Channel Selection Logic:
    1. Patient preference (from CommunicationPreference)
    2. Urgency (30min = call, 24h = email)
    3. No-show history (> 2 no-shows = escalate to voice)
    4. Time of day (avoid calling outside business hours)
    
    Complexity Analysis:
    - Time: O(n * m) where n = patients, m = appointments per patient
    - Space: O(k) where k = number of proposed actions
    """
    
    def __init__(self, db_session):
        super().__init__("followup_specialist")
        self.db = db_session
    
    async def run(self, context: AgentContext) -> WorkerResult:
        """Run follow-up analysis and propose reminder actions."""
        logger.info(f"Worker {self.name} starting analysis for org {context.organization_id}")
        
        result = WorkerResult(worker_name=self.name)
        emitter = context.emitter
        
        # Query upcoming appointments in next 72 hours
        upcoming_appointments = await self._get_upcoming_appointments(
            context.organization_id,
            hours_ahead=72
        )
        
        if emitter:
            await emitter.emit(
                agent_name=self.name,
                stage=ThoughtStage.SPECIALIST_ANALYSIS,
                content=f"📅 Found {len(upcoming_appointments)} upcoming appointments in next 72 hours..."
            )
        
        if not upcoming_appointments:
            result.findings.append("No upcoming appointments in next 72 hours")
            context.add_worker_result(result)
            return result
        
        result.findings.append(f"Found {len(upcoming_appointments)} upcoming appointments")
        
        for appointment in upcoming_appointments:
            # Skip if reminder already exists
            existing_reminder = await self._get_existing_reminder(appointment.id)
            if existing_reminder:
                continue
            
            patient = appointment.patient
            patient_name = f"{patient.first_name} {patient.last_name}" if patient.first_name else str(patient.id)[:8]
            
            # Check no-show history
            no_show_count = await self._get_no_show_count(patient.id)
            
            # Build reminder strategy
            strategy = self._build_reminder_strategy(
                patient=patient,
                appointment=appointment,
                no_show_count=no_show_count
            )
            
            if emitter:
                priority_emoji = "🚨" if strategy["priority"] == "high" else "📋"
                await emitter.emit(
                    agent_name=self.name,
                    stage=ThoughtStage.SPECIALIST_ANALYSIS,
                    content=f"{priority_emoji} {patient_name}: Appt in {strategy['hours_until']:.0f}h. Strategy: {', '.join(c.value for c in strategy['channels'])}. {strategy['reasoning']}",
                    patient_id=patient.id
                )
            
            # Build decision trace for observability
            decision_trace = {
                "specialist_findings": {
                    "followup_specialist": [
                        f"Appointment in {strategy['hours_until']} hours",
                        f"Patient preference: {patient.preferred_contact_method.value if patient.preferred_contact_method else 'none'}",
                        f"No-show history: {no_show_count}",
                    ]
                },
                "strategy": strategy,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Propose action
            result.proposed_actions.append(AgentAction(
                type="schedule_appointment_reminder",
                target_id=str(patient.id),
                content={
                    "appointment_id": str(appointment.id),
                    "channels": [c.value for c in strategy["channels"]],
                    "send_time": strategy["send_time"].isoformat(),
                    "priority": strategy["priority"],
                    "decision_trace": decision_trace,
                },
                reasoning=strategy["reasoning"],
                confidence=strategy["confidence"]
            ))
            
            # Flag high-risk patients
            if no_show_count >= 2 or strategy["priority"] == "high":
                result.flagged_patients.append(patient.id)
        
        if emitter:
            await emitter.emit(
                agent_name=self.name,
                stage=ThoughtStage.SPECIALIST_ANALYSIS,
                content=f"📬 Follow-up analysis complete: {len(result.proposed_actions)} reminders scheduled."
            )
        
        context.add_worker_result(result)
        logger.info(f"FollowUpSpecialist proposed {len(result.proposed_actions)} reminder actions")
        return result
    
    async def _get_upcoming_appointments(
        self,
        organization_id: uuid.UUID,
        hours_ahead: int = 72
    ) -> List[Appointment]:
        """Get scheduled appointments in the specified time window."""
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours_ahead)
        
        query = (
            select(Appointment)
            .where(
                and_(
                    Appointment.organization_id == organization_id,
                    Appointment.status == AppointmentStatus.SCHEDULED,
                    Appointment.scheduled_time >= now,
                    Appointment.scheduled_time <= cutoff,
                )
            )
            .options(selectinload(Appointment.patient))
            .order_by(Appointment.scheduled_time)
        )
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def _get_existing_reminder(self, appointment_id: uuid.UUID) -> Optional[AppointmentReminder]:
        """Check if a reminder already exists for this appointment."""
        return await AppointmentReminder.fetch_unique(
            self.db,
            appointment_id=appointment_id,
            status=ReminderStatus.SCHEDULED
        )
    
    async def _get_no_show_count(self, patient_id: uuid.UUID) -> int:
        """Get count of past no-show appointments for a patient (SQL-level count, no row loading)."""
        query = select(func.count()).select_from(Appointment).where(
            and_(
                Appointment.patient_id == patient_id,
                Appointment.status == AppointmentStatus.NO_SHOW
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one()
    
    def _build_reminder_strategy(
        self,
        patient: Patient,
        appointment: Appointment,
        no_show_count: int
    ) -> dict:
        """
        Build smart reminder strategy based on multiple factors.
        
        Returns:
            dict with channels, send_time, priority, reasoning, confidence
        """
        now = datetime.now(timezone.utc)
        appt_time = appointment.scheduled_time
        hours_until = (appt_time - now).total_seconds() / 3600
        
        channels: List[ReminderChannel] = []
        reasoning_parts: List[str] = []
        priority = "normal"
        confidence = 0.9
        
        # Get patient preference
        pref = patient.preferred_contact_method
        
        # Base channel selection based on urgency
        if hours_until <= 2:
            # Very urgent - prioritize voice
            if patient.phone and pref == CommunicationPreference.CALL:
                channels.append(ReminderChannel.VOICE)
                reasoning_parts.append("Urgent: <2h until appointment, using voice call")
            elif patient.phone:
                channels.append(ReminderChannel.SMS)
                reasoning_parts.append("Urgent: <2h until appointment, using SMS")
            if patient.email:
                channels.append(ReminderChannel.EMAIL)
        
        elif hours_until <= 24:
            # Moderate urgency - SMS primary
            if patient.phone:
                channels.append(ReminderChannel.SMS)
                reasoning_parts.append(f"Moderate urgency: {hours_until:.0f}h until appointment")
            if patient.email:
                channels.append(ReminderChannel.EMAIL)
        
        else:
            # Advance notice - email primary
            if patient.email:
                channels.append(ReminderChannel.EMAIL)
                reasoning_parts.append(f"Advance notice: {hours_until:.0f}h until appointment")
            if patient.phone and pref in [CommunicationPreference.SMS, CommunicationPreference.CALL]:
                channels.append(ReminderChannel.SMS)
        
        # Escalation for no-show history
        if no_show_count >= 2:
            priority = "high"
            confidence = 0.95
            reasoning_parts.append(f"High risk: {no_show_count} prior no-shows")
            
            # Force voice call if patient has preference for calls or high no-show
            if patient.phone and ReminderChannel.VOICE not in channels:
                channels.insert(0, ReminderChannel.VOICE)
                reasoning_parts.append("Escalated to voice call due to no-show history")
        
        elif no_show_count == 1:
            priority = "medium"
            reasoning_parts.append("1 prior no-show - monitoring")
        
        # Override with patient preference if specified
        if pref == CommunicationPreference.SMS and ReminderChannel.SMS not in channels:
            if patient.phone:
                channels.insert(0, ReminderChannel.SMS)
                reasoning_parts.append("Patient prefers SMS")
        
        elif pref == CommunicationPreference.EMAIL and ReminderChannel.EMAIL not in channels:
            if patient.email:
                channels.insert(0, ReminderChannel.EMAIL)
                reasoning_parts.append("Patient prefers email")
        
        elif pref == CommunicationPreference.CALL and ReminderChannel.VOICE not in channels:
            if patient.phone:
                channels.insert(0, ReminderChannel.VOICE)
                reasoning_parts.append("Patient prefers voice calls")
        
        # Determine send time (how far before appointment to send)
        if hours_until <= 2:
            send_time = now  # Send immediately
        elif hours_until <= 24:
            send_time = appt_time - timedelta(hours=2)  # 2 hours before
        elif hours_until <= 48:
            send_time = appt_time - timedelta(hours=24)  # 24 hours before
        else:
            send_time = appt_time - timedelta(hours=48)  # 48 hours before
        
        # Fallback if no channels available
        if not channels:
            reasoning_parts.append("Warning: No contact method available")
            confidence = 0.5
        
        return {
            "channels": channels,
            "send_time": send_time,
            "priority": priority,
            "hours_until": hours_until,
            "reasoning": "; ".join(reasoning_parts),
            "confidence": confidence
        }
