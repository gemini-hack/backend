import asyncio
from datetime import datetime, timezone

from app.agents.livekit_gemini.action_logger import get_actions
from app.agents.livekit_gemini.transcript_buffer import TranscriptBuffer
from app.celery_app import celery_app
from app.db.database import async_session_factory
from app.models.call_session import CallAction, CallSession
from app.services.ai_service import gemini_service
from app.utils.logger import logger


async def _process_call_end_async(room_name: str) -> None:
    """Async implementation of post-call processing."""
    logger.info(f"[POST-CALL] Processing call end for room: {room_name}")

    buffer = TranscriptBuffer(room_name)

    try:
        # 1. Get transcript from buffer
        transcript = await buffer.get_full_transcript()
        if not transcript:
            logger.warning(
                f"[POST-CALL] No transcript found for room: {room_name}"
            )
            transcript = ""

        logger.info(f"[POST-CALL] Retrieved transcript ({len(transcript)} chars)")

        # 2. Get actions from buffer
        actions = await get_actions(room_name)
        logger.info(f"[POST-CALL] Retrieved {len(actions)} actions")

        # 3. Generate summary using Gemini (if transcript exists)
        summary = None
        if transcript:
            try:
                summary_prompt = (
                    "Summarize this healthcare call transcript in 2-3 sentences.\n"
                    "Focus on: main topic, patient concerns, and any actions taken.\n\n"
                    f"Transcript:\n{transcript}\n\nSummary:"
                )
                summary = await gemini_service.generate_response(
                    prompt=summary_prompt,
                    system_instruction=(
                        "You are a medical assistant summarizing patient calls. "
                        "Be concise and professional."
                    )
                )
                logger.info(f"[POST-CALL] Generated summary ({len(summary)} chars)")
            except Exception as e:
                logger.error(f"[POST-CALL] Failed to generate summary: {e}")
                summary = "Summary generation failed."

        # 4. Update CallSession in database using BaseModel methods
        async with async_session_factory() as db:
            call_session = await CallSession.fetch_one(db, room_name=room_name)

            if not call_session:
                logger.error(
                    f"[POST-CALL] CallSession not found for room: {room_name}"
                )
                return

            # Update transcript and summary
            call_session.transcript = transcript
            call_session.summary = summary

            # Determine outcome based on actions
            if actions:
                action_types = [a.action_type for a in actions]
                if "reschedule_appointment" in action_types:
                    call_session.outcome = "appointment_rescheduled"
                elif "lookup_patient" in action_types:
                    call_session.outcome = "patient_lookup"
                else:
                    call_session.outcome = "actions_taken"
            elif transcript:
                call_session.outcome = "conversation_completed"
            else:
                call_session.outcome = "no_content"

            # 5. Create CallAction records from buffered actions
            for action in actions:
                timestamp = (
                    datetime.fromisoformat(action.timestamp)
                    if action.timestamp
                    else datetime.now(timezone.utc)
                )
                db_action = CallAction(
                    call_session_id=call_session.id,
                    action_type=action.action_type,
                    action_data=action.action_data,
                    result=action.result,
                    timestamp=timestamp
                )
                db_action.add(db)

            await db.commit()
            logger.info(
                f"[POST-CALL] Saved transcript, summary, and {len(actions)} "
                f"actions for room: {room_name}"
            )

        # 6. Clear buffers
        await buffer.clear()
        logger.info(f"[POST-CALL] Cleared buffers for room: {room_name}")

    except Exception as e:
        logger.exception(f"[POST-CALL] Error processing call end: {e}")
        raise


@celery_app.task(bind=True, max_retries=3)
def process_call_end(self, room_name: str) -> None:
    """
    Celery task for post-call processing.

    Retrieves transcript and actions from Redis, generates summary,
    and persists everything to the CallSession.
    """
    try:
        asyncio.run(_process_call_end_async(room_name))
    except Exception as e:
        logger.error(f"[POST-CALL] Task failed, retrying... Error: {e}")
        raise self.retry(exc=e, countdown=5)
