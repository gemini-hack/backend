import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
import uuid as uuid_lib

import redis.asyncio as aioredis

from app.core.config import settings
from app.utils.logger import logger


class RedisManager:
    """Singleton Redis connection manager."""
    
    _redis: Optional[aioredis.Redis] = None
    
    @classmethod
    async def connect(cls):
        """Connect to Redis with retries to handle startup delays."""
        if cls._redis is not None:
            return

        max_retries = 5
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                # Use 127.0.0.1 explicitly to avoid IPv6 issues on Windows
                redis_url = settings.REDIS_URL.replace("localhost", "127.0.0.1")
                cls._redis = aioredis.from_url(
                    redis_url, 
                    encoding="utf-8", 
                    decode_responses=True,
                    max_connections=10,
                    socket_connect_timeout=10,
                    socket_timeout=10,
                )
                await cls._redis.ping()
                logger.info(f"Successfully connected to Redis (attempt {attempt + 1})")
                return
            except Exception as e:
                cls._redis = None
                if attempt < max_retries - 1:
                    logger.warning(f"Redis connection attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s...")
                    import asyncio
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"Failed to connect to Redis after {max_retries} attempts: {e}")
                
    @classmethod
    async def close(cls):
        if cls._redis:
            await cls._redis.close()
            cls._redis = None
            logger.info("Closed Redis connection")
            
    @classmethod
    def get_client(cls) -> aioredis.Redis:
        if cls._redis is None:
            raise RuntimeError("Redis client is not initialized")
        return cls._redis


class SessionStore:
    """Centralized session storage with consistent key patterns."""
    
    KEY_PREFIX = "session"
    
    @classmethod
    def _make_key(cls, user_id: str | UUID, session_id: str | UUID) -> str:
        return f"{cls.KEY_PREFIX}:{user_id}:{session_id}"
    
    @classmethod
    def _make_pattern(cls, user_id: str | UUID) -> str:
        return f"{cls.KEY_PREFIX}:{user_id}:*"
    
    @classmethod
    def generate_session_id(cls) -> UUID:
        return uuid_lib.uuid4()
    
    @classmethod
    async def create(
        cls,
        user_id: str | UUID,
        org_id: str | UUID,
        session_id: UUID,
        token_hash: str,
        device_info: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        session_data = {
            "token_hash": token_hash,
            "user_id": str(user_id),
            "org_id": str(org_id),
            "device_info": device_info or "",
            "ip_address": ip_address,
            "created_at": now,
            "last_used_at": now,
        }
        
        redis = RedisManager.get_client()
        key = cls._make_key(user_id, session_id)
        await redis.setex(
            key,
            timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            json.dumps(session_data)
        )
    
    @classmethod
    async def get(cls, user_id: str | UUID, session_id: str | UUID) -> Optional[dict]:
        redis = RedisManager.get_client()
        key = cls._make_key(user_id, session_id)
        session_json = await redis.get(key)
        
        if not session_json:
            return None
            
        try:
            return json.loads(session_json)
        except json.JSONDecodeError:
            return None
    
    @classmethod
    async def update(
        cls,
        user_id: str | UUID,
        session_id: str | UUID,
        token_hash: str,
        ip_address: Optional[str] = None,
    ) -> None:
        """Update session with new token hash and extend TTL (token rotation)."""
        session_data = await cls.get(user_id, session_id)
        if not session_data:
            return
            
        session_data["token_hash"] = token_hash
        session_data["last_used_at"] = datetime.now(timezone.utc).isoformat()
        if ip_address:
            session_data["ip_address"] = ip_address
        
        redis = RedisManager.get_client()
        key = cls._make_key(user_id, session_id)
        await redis.setex(
            key,
            timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            json.dumps(session_data)
        )
    
    @classmethod
    async def delete(cls, user_id: str | UUID, session_id: str | UUID) -> bool:
        redis = RedisManager.get_client()
        key = cls._make_key(user_id, session_id)
        deleted = await redis.delete(key)
        return deleted > 0
    
    @classmethod
    async def delete_all(cls, user_id: str | UUID) -> int:
        redis = RedisManager.get_client()
        pattern = cls._make_pattern(user_id)
        
        keys = []
        async for key in redis.scan_iter(match=pattern):
            keys.append(key)
        
        if keys:
            return await redis.delete(*keys)
        return 0
    
    @classmethod
    async def list_all(cls, user_id: str | UUID) -> list[tuple[UUID, dict]]:
        redis = RedisManager.get_client()
        pattern = cls._make_pattern(user_id)
        
        sessions = []
        async for key in redis.scan_iter(match=pattern):
            try:
                session_json = await redis.get(key)
                if not session_json:
                    continue
                    
                data = json.loads(session_json)
                session_id_str = key.split(":")[-1]
                sessions.append((UUID(session_id_str), data))
            except (json.JSONDecodeError, ValueError):
                continue
        
        return sessions


class AgentSettingsCache:
    """Cache for agent settings per organization."""
    
    KEY_PREFIX = "agent_settings"
    TTL_SECONDS = 3600  # 1 hour
    
    @classmethod
    def _make_key(cls, org_id: str | UUID) -> str:
        return f"{cls.KEY_PREFIX}:{org_id}"
    
    @classmethod
    async def get(cls, org_id: str | UUID) -> Optional[dict]:
        """Get cached agent settings for an organization."""
        try:
            redis = RedisManager.get_client()
            key = cls._make_key(org_id)
            data = await redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning(f"AgentSettingsCache get failed: {e}")
            return None
    
    @classmethod
    async def set(cls, org_id: str | UUID, settings: dict) -> None:
        """Cache agent settings for an organization."""
        try:
            redis = RedisManager.get_client()
            key = cls._make_key(org_id)
            await redis.setex(key, cls.TTL_SECONDS, json.dumps(settings))
        except Exception as e:
            logger.warning(f"AgentSettingsCache set failed: {e}")
    
    @classmethod
    async def invalidate(cls, org_id: str | UUID) -> None:
        """Invalidate cached agent settings for an organization."""
        try:
            redis = RedisManager.get_client()
            key = cls._make_key(org_id)
            await redis.delete(key)
        except Exception as e:
            logger.warning(f"AgentSettingsCache invalidate failed: {e}")
