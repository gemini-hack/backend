import json
from datetime import datetime, timezone
from typing import List, Literal
from dataclasses import dataclass, field, asdict

from app.core.redis import RedisManager
from app.utils.logger import logger


@dataclass
class TranscriptEntry:
    """A single transcript entry."""
    role: Literal["user", "agent"]
    text: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TranscriptBuffer:
    """
    Buffers transcript entries during a call, persisted to Redis.
    
    Uses Redis LIST to store entries, with automatic expiry after 24 hours.
    """
    
    EXPIRY_SECONDS = 86400
    
    def __init__(self, room_name: str):
        self.room_name = room_name
        self.transcript_key = f"transcript:{room_name}"
        self.actions_key = f"actions:{room_name}"
    
    async def add_entry(self, role: str, text: str) -> None:
        """Add a transcript entry to the buffer."""
        try:
            redis = RedisManager.get_client()
            entry = TranscriptEntry(role=role, text=text)
            await redis.rpush(self.transcript_key, json.dumps(asdict(entry)))
            await redis.expire(self.transcript_key, self.EXPIRY_SECONDS)
            logger.debug(f"[TRANSCRIPT] Added {role} entry for {self.room_name}")
        except Exception as e:
            logger.error(f"[TRANSCRIPT] Failed to add entry: {e}")
    
    async def get_entries(self) -> List[TranscriptEntry]:
        """Get all transcript entries."""
        try:
            redis = RedisManager.get_client()
            raw_entries = await redis.lrange(self.transcript_key, 0, -1)
            entries = []
            for raw in raw_entries:
                data = json.loads(raw)
                entries.append(TranscriptEntry(**data))
            return entries
        except Exception as e:
            logger.error(f"[TRANSCRIPT] Failed to get entries: {e}")
            return []
    
    async def get_full_transcript(self) -> str:
        """Return formatted transcript as a string."""
        entries = await self.get_entries()
        if not entries:
            return ""
        
        lines = []
        for entry in entries:
            role_label = "Patient" if entry.role == "user" else "MIRA"
            lines.append(f"[{role_label}]: {entry.text}")
        
        return "\n".join(lines)
    
    async def clear(self) -> None:
        """Clear the buffer after persistence."""
        try:
            redis = RedisManager.get_client()
            await redis.delete(self.transcript_key)
            await redis.delete(self.actions_key)
            logger.info(f"[TRANSCRIPT] Cleared buffer for {self.room_name}")
        except Exception as e:
            logger.error(f"[TRANSCRIPT] Failed to clear buffer: {e}")


# Global buffer registry (room_name -> buffer instance)
_buffers: dict[str, TranscriptBuffer] = {}


def get_buffer(room_name: str) -> TranscriptBuffer:
    """Get or create a buffer for a room."""
    if room_name not in _buffers:
        _buffers[room_name] = TranscriptBuffer(room_name)
    return _buffers[room_name]


def clear_buffer_reference(room_name: str) -> None:
    """Remove buffer from registry (after persistence)."""
    _buffers.pop(room_name, None)
