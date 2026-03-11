from typing import List, Optional
import json
import asyncio
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, status as http_status, Request, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    CurrentUser,
    DbSession,
    require_permission,
)
from app.models.agent import Alert, AgentAction, AlertStatus, ActionOutcome
from app.schemas.agent import AlertResponse, AgentActionResponse
from app.schemas.auth import OrganizationResponse
from app.models.user import Organization
from app.utils.responses import success_response
from app.utils.logger import logger
from app.middleware.rate_limit import limiter
from sqlalchemy import select, desc, func

router = APIRouter(prefix="/agents", tags=["Agents"])

@router.get(
    "/actions",
    status_code=http_status.HTTP_200_OK,
    response_model=List[AgentActionResponse],
    summary="List agent actions",
    dependencies=[Depends(require_permission("agents:read"))],
)
async def list_agent_actions(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200, description="Max results to return"),
    assigned_to_me: bool = False,
):
    """
    List recent actions taken by the AI agents.
    
    - **assigned_to_me**: If true, returns only actions for patients assigned to the current user (Physician, Nurse, or Coordinator).
    """
    from app.models.patient import Patient
    from sqlalchemy import or_
    
    query = select(AgentAction).join(AgentAction.patient).where(
        AgentAction.organization_id == user.organization_id
    )
    
    if assigned_to_me:
        query = query.where(
            or_(
                Patient.primary_physician_id == user.id,
                Patient.assigned_nurse_id == user.id,
                Patient.care_coordinator_id == user.id
            )
        )
        
    query = query.order_by(desc(AgentAction.created_at)).limit(limit)
    
    result = await db.execute(query)
    actions = result.scalars().all()
    
    return actions


@router.get(
    "/actions/resolved",
    status_code=http_status.HTTP_200_OK,
    summary="List resolved agent actions",
    dependencies=[Depends(require_permission("agents:read"))],
)
async def list_resolved_actions(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=100, le=500, description="Max results to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    action_type: Optional[str] = Query(default=None, description="Filter by action type"),
    from_date: Optional[datetime] = Query(default=None, description="Filter from date (inclusive)"),
    to_date: Optional[datetime] = Query(default=None, description="Filter to date (inclusive)"),
):
    """
    List all resolved agent actions for the organization.
    
    Resolved actions are cases where the patient took the desired action
    (e.g., attended appointment, submitted health reading, responded to outreach).
    
    - **action_type**: Filter by specific action type (e.g., "appointment_reminder", "engagement_nudge")
    - **from_date**: Start date for filtering
    - **to_date**: End date for filtering

    """
    query = select(AgentAction).where(
        AgentAction.organization_id == user.organization_id,
        AgentAction.outcome == ActionOutcome.RESOLVED
    )
    
    if action_type:
        query = query.where(AgentAction.action_type == action_type)
    
    if from_date:
        query = query.where(AgentAction.outcome_detected_at >= from_date)
    
    if to_date:
        query = query.where(AgentAction.outcome_detected_at <= to_date)
    
    query = query.order_by(desc(AgentAction.outcome_detected_at)).offset(offset).limit(limit)
    
    result = await db.execute(query)
    actions = result.scalars().all()
    
    # Get total count for pagination
    count_query = select(func.count(AgentAction.id)).where(
        AgentAction.organization_id == user.organization_id,
        AgentAction.outcome == ActionOutcome.RESOLVED
    )
    if action_type:
        count_query = count_query.where(AgentAction.action_type == action_type)
    if from_date:
        count_query = count_query.where(AgentAction.outcome_detected_at >= from_date)
    if to_date:
        count_query = count_query.where(AgentAction.outcome_detected_at <= to_date)
    
    total_result = await db.execute(count_query)
    total_count = total_result.scalar()
    
    return success_response(
        status_code=200,
        message=f"Found {len(actions)} resolved actions",
        data={
            "total": total_count,
            "offset": offset,
            "limit": limit,
            "actions": [AgentActionResponse.model_validate(a).model_dump() for a in actions]
        }
    )


@router.post(
    "/actions/{action_id}/resolve",
    status_code=http_status.HTTP_200_OK,
    summary="Manually resolve an agent action",
    dependencies=[Depends(require_permission("agents:write"))],
)
async def resolve_action_endpoint(
    action_id: UUID,
    user: CurrentUser,
    db: DbSession,
    reason: str = Query(..., min_length=5, description="Resolution reason"),
):
    """
    Manually mark an agent action as resolved.
    
    Use this when a clinician has verified the patient action was completed
    outside of the automated detection system.
    
    - **reason**: Explanation of how the action was resolved
    """
    from app.services.action_idempotency import resolve_action
    from app.models.agent import ActionOutcome
    
    action = await db.get(AgentAction, action_id)
    
    if not action:
        from app.utils.responses import fail_response
        return fail_response(
            status_code=404,
            message="Action not found"
        )
    
    if action.organization_id != user.organization_id:
        from app.utils.responses import fail_response
        return fail_response(
            status_code=403,
            message="Action belongs to different organization"
        )
    
    if action.outcome == ActionOutcome.RESOLVED:
        return success_response(
            status_code=200,
            message="Action was already resolved",
            data={"action_id": str(action_id), "outcome_reason": action.outcome_reason}
        )
    
    await resolve_action(db, action_id, f"Manually resolved by {user.email}: {reason}")

    # Audit trail for clinical action resolution
    from app.models.user import AuditLog
    audit = AuditLog(
        user_id=user.id,
        organization_id=user.organization_id,
        action="agent_action.resolve",
        resource_type="agent_action",
        resource_id=str(action_id),
        details={
            "action_type": action.action_type,
            "patient_id": str(action.patient_id),
            "reason": reason,
        },
    )
    db.add(audit)
    await db.commit()
    
    # Push real-time notification to dashboard (triggers toast + stat card update)
    try:
        from app.services.dashboard_notifier import DashboardNotifier
        notifier = DashboardNotifier(user.organization_id)
        await notifier.notify_action_resolved(
            action_id=action_id,
            action_type=action.action_type,
            reason=reason,
        )
    except Exception as e:
        logger.warning(f"Dashboard notification failed (non-blocking): {e}")
    
    return success_response(
        status_code=200,
        message="Action resolved successfully",
        data={
            "action_id": str(action_id),
            "outcome": "resolved",
            "outcome_reason": reason,
            "resolved_by": str(user.id)
        }
    )



@router.get(
    "/alerts",
    status_code=http_status.HTTP_200_OK,
    response_model=List[AlertResponse],
    summary="List active alerts",
    dependencies=[Depends(require_permission("alerts:read"))],
)
async def list_alerts(
    user: CurrentUser,
    db: DbSession,
    alert_status: AlertStatus = AlertStatus.PENDING,
    limit: int = 50,
):
    """List pending or active alerts generated by agents."""
    query = select(Alert).where(
        Alert.organization_id == user.organization_id,
        Alert.status == alert_status
    ).order_by(desc(Alert.created_at)).limit(limit)
    
    result = await db.execute(query)
    alerts = result.scalars().all()
    
    return alerts

@router.post(
    "/trigger-rounds",
    status_code=http_status.HTTP_202_ACCEPTED,
    summary="Trigger daily analysis",
    dependencies=[Depends(require_permission("agents:trigger"))],
)
@limiter.limit("3/15minutes")
async def trigger_analysis_rounds(
    request: Request,
    user: CurrentUser,
    db: DbSession,
):
    """
    Manually trigger a morning rounds analysis for the organization.

    The analysis runs on the Celery worker (not the API server) to avoid
    blocking HTTP requests during heavy LLM processing.

    Returns a cycle_id that can be used to subscribe to the thought stream.
    Connect to `/agents/stream/{cycle_id}` BEFORE calling this endpoint
    to observe the AI's thinking in real-time.
    """
    import uuid
    from app.tasks.analysis import run_org_analysis
    
    cycle_id = uuid.uuid4()
    
    # Dispatch to Celery worker — keeps the API server free
    run_org_analysis.delay(str(user.organization_id), str(cycle_id))
    
    return success_response(
        status_code=202,
        message="Analysis rounds dispatched to worker. Subscribe to stream for real-time thoughts.",
        data={
            "cycle_id": str(cycle_id),
            "stream_url": f"/api/v1/agents/stream/{cycle_id}",
            "organization_id": str(user.organization_id),
        }
    )


@router.get(
    "/stream/{cycle_id}",
    summary="Stream agent thoughts in real-time (SSE)",
    dependencies=[Depends(require_permission("agents:read"))],
)
async def stream_agent_thoughts(
    cycle_id: UUID,
    request: Request,
    user: CurrentUser,
):
    """
    Server-Sent Events (SSE) endpoint to stream real-time agent thoughts.
    
    **How to use:**
    1. Connect to this endpoint BEFORE triggering analysis
    2. Call POST `/agents/trigger-rounds` to start the analysis
    3. Watch thoughts stream in real-time as each specialist analyzes patients
    4. Stream ends when analysis is complete
    
    **Event Format:**
    ```json
    {
        "cycle_id": "uuid",
        "timestamp": "ISO datetime",
        "agent_name": "hiv_specialist",
        "stage": "specialist_analysis",
        "content": "Analyzing viral load for patient...",
        "patient_id": "uuid or null",
        "metadata": {}
    }
    ```
    
    **Stages:**
    - `loading_data`: Initial data loading
    - `specialist_analysis`: Specialists analyzing patients
    - `supervisor_synthesis`: Supervisor making final decisions
    - `critic_review`: Quality control review
    - `auto_execution`: Automated actions being executed
    - `complete`: Analysis finished
    """
    from app.core.redis import RedisManager
    
    channel = f"thoughts:org:{user.organization_id}:cycle:{cycle_id}"
    
    async def event_generator():
        try:
            redis = RedisManager.get_client()
            pubsub = redis.pubsub()
            await pubsub.subscribe(channel)
            
            # Send connection confirmation
            yield f"data: {json.dumps({'event': 'connected', 'cycle_id': str(cycle_id), 'channel': channel})}\n\n"
            
            # Set timeout for stream (5 minutes max)
            timeout = 300  # 5 minutes
            start_time = asyncio.get_event_loop().time()
            
            async for message in pubsub.listen():
                # Check timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > timeout:
                    yield f"data: {json.dumps({'event': 'timeout', 'message': 'Stream timeout after 5 minutes'})}\n\n"
                    break
                
                # Check if client disconnected
                if await request.is_disconnected():
                    logger.info(f"Client disconnected from thought stream {cycle_id}")
                    break
                
                if message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    
                    yield f"data: {data}\n\n"
                    
                    # Check for completion signal
                    try:
                        parsed = json.loads(data)
                        if parsed.get("stage") == "complete":
                            yield f"data: {json.dumps({'event': 'stream_end', 'message': 'Analysis complete'})}\n\n"
                            break
                    except json.JSONDecodeError:
                        pass
                        
        except RuntimeError as e:
            # Redis not initialized
            logger.warning(f"Redis not available for streaming: {e}")
            yield f"data: {json.dumps({'event': 'error', 'message': 'Streaming not available - Redis not connected'})}\n\n"
        except Exception as e:
            logger.error(f"Thought stream error: {e}")
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except:
                pass
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.patch(
    "/config",
    status_code=http_status.HTTP_200_OK,
    response_model=OrganizationResponse,
    summary="Update agent configuration",
    dependencies=[Depends(require_permission("org:update"))],
)
async def update_agent_config(
    user: CurrentUser,
    db: DbSession,
    disease_specializations: List[str],
):
    """Update which diseases the agents should monitor for this organization."""
    from fastapi import HTTPException
    
    result = await db.execute(
        select(Organization).where(
            Organization.id == user.organization_id
        )
    )
    organization = result.scalar_one_or_none()

    if not organization:
        raise HTTPException(
            status_code=404,
            detail="Organization not found",
        )
    
    organization.disease_specializations = disease_specializations
    db.add(organization)
    await db.commit()
    await db.refresh(organization)
    
    return organization


# ==============================================================================
# WebSocket Dashboard Notifications
# ==============================================================================

@router.websocket("/dashboard/ws")
async def websocket_dashboard(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None),
):
    """
    WebSocket endpoint for real-time dashboard notifications.
    
    Clinicians connect and receive instant updates when:
    - New agent actions are created
    - New alerts are generated
    - Actions are resolved
    - Morning rounds start/complete
    
    Usage (JavaScript):
        const ws = new WebSocket('ws://localhost:8000/api/v1/agents/dashboard/ws?token=JWT_TOKEN');
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log('Dashboard update:', data);
        };
    
    Message format:
        {
            "type": "new_action" | "new_alert" | "action_resolved" | "cycle_started" | "cycle_completed",
            "timestamp": "2026-01-30T15:00:00Z",
            "organization_id": "uuid",
            "data": { ... }
        }
    """
    # Validate JWT token
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return
    
    try:
        from app.core.security import decode_token
        from app.core.config import settings
        
        payload = decode_token(token, settings.SECRET_KEY)
        organization_id = UUID(payload.get("org_id"))
        user_id = payload.get("sub")
        
        logger.info(f"WebSocket dashboard connection from user {user_id} for org {organization_id}")
        
    except Exception as e:
        logger.warning(f"WebSocket auth failed: {e}")
        await websocket.close(code=4003, reason="Invalid token")
        return
    
    await websocket.accept()
    
    # Subscribe to Redis channel for this organization
    from app.core.redis import RedisManager
    
    channel = f"dashboard:{organization_id}"
    
    try:
        redis = RedisManager.get_client()
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        
        # Send connection confirmation
        await websocket.send_json({
            "type": "connected",
            "timestamp": datetime.now().isoformat(),
            "channel": channel,
            "message": "Connected to dashboard notifications"
        })
        
        # Listen for messages
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            
            if message and message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                await websocket.send_text(data)
            
            # Also check for WebSocket disconnect
            try:
                # Non-blocking check for client messages (like ping/pong)
                await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=0.01
                )
            except asyncio.TimeoutError:
                pass  # No message, continue
            except WebSocketDisconnect:
                break
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket dashboard disconnected for org {organization_id}")
    except Exception as e:
        logger.error(f"WebSocket dashboard error: {e}")
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
        except:
            pass
        
        try:
            await websocket.close()
        except:
            pass