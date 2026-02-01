import json
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, field, asdict

from app.core.redis import RedisManager
from app.utils.logger import logger


@dataclass
class ActionEntry:
    """A logged agent action."""
    action_type: str
    action_data: dict
    result: str  # "success", "failed", "pending"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# Thread-local storage for current room context
_current_room: Optional[str] = None


def set_current_room(room_name: str) -> None:
    """Set the current room context for action logging."""
    global _current_room
    _current_room = room_name
    logger.debug(f"[ACTION_LOGGER] Set current room to {room_name}")


def get_current_room() -> Optional[str]:
    """Get the current room context."""
    return _current_room


def clear_current_room() -> None:
    """Clear the current room context."""
    global _current_room
    _current_room = None


async def log_call_action(
    action_type: str,
    action_data: dict,
    result: str = "success",
    room_name: Optional[str] = None
) -> None:
    """
    Log an agent action during a call.
    
    Args:
        action_type: Type of action (e.g., "reschedule_appointment", "lookup_patient")
        action_data: Dict with action parameters
        result: Result status ("success", "failed", "pending")
        room_name: Optional room name override (uses current room if not provided)
    """
    room = room_name or _current_room
    if not room:
        logger.warning(f"[ACTION_LOGGER] No room context for action: {action_type}")
        return
    
    try:
        redis = RedisManager.get_client()
        actions_key = f"actions:{room}"
        
        entry = ActionEntry(
            action_type=action_type,
            action_data=action_data,
            result=result
        )
        
        await redis.rpush(actions_key, json.dumps(asdict(entry)))
        await redis.expire(actions_key, 86400)  # 24 hour expiry
        
        logger.info(f"[ACTION_LOGGER] Logged {action_type} ({result}) for room {room}")
    except Exception as e:
        logger.error(f"[ACTION_LOGGER] Failed to log action: {e}")


async def get_actions(room_name: str) -> list[ActionEntry]:
    """Get all logged actions for a room."""
    try:
        redis = RedisManager.get_client()
        actions_key = f"actions:{room_name}"
        raw_entries = await redis.lrange(actions_key, 0, -1)
        
        entries = []
        for raw in raw_entries:
            data = json.loads(raw)
            entries.append(ActionEntry(**data))
        return entries
    except Exception as e:
        logger.error(f"[ACTION_LOGGER] Failed to get actions: {e}")
        return []
