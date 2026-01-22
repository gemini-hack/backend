from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.redis import AgentSettingsCache
from app.models.user import Organization
from app.schemas.agent_settings import (
    AgentSettingsRequest,
    DEFAULT_AGENT_NAME,
    DEFAULT_VOICE_STYLE,
    DEFAULT_LANGUAGE,
    DEFAULT_GREETING,
    VOICE_STYLE_TO_GEMINI,
)
from app.utils.logger import logger


# Default settings dict
DEFAULT_AGENT_SETTINGS = {
    "enabled": True,
    "agent_name": DEFAULT_AGENT_NAME,
    "greeting": DEFAULT_GREETING,
    "voice_style": DEFAULT_VOICE_STYLE,
    "language": DEFAULT_LANGUAGE,
    "custom_instructions": None,
}


class AgentSettingsService:
    """Service for AI agent configuration management."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_organization(self, org_id: UUID) -> Organization:
        """Get organization by ID."""
        result = await self.db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = result.scalar_one_or_none()
        if not org:
            raise ValueError("Organization not found")
        return org
    
    async def get_settings(self, org_id: UUID) -> dict:
        """Get current agent settings for organization."""
        org = await self.get_organization(org_id)
        settings = org.agent_settings or {}
        
        # Merge with defaults for any missing keys
        return {
            "enabled": settings.get("enabled", DEFAULT_AGENT_SETTINGS["enabled"]),
            "agent_name": settings.get("agent_name", DEFAULT_AGENT_SETTINGS["agent_name"]),
            "greeting": settings.get("greeting", DEFAULT_AGENT_SETTINGS["greeting"]),
            "voice_style": settings.get("voice_style", DEFAULT_AGENT_SETTINGS["voice_style"]),
            "language": settings.get("language", DEFAULT_AGENT_SETTINGS["language"]),
            "custom_instructions": settings.get("custom_instructions"),
        }
    
    async def get_settings_cached(self, org_id: UUID) -> dict:
        """Get agent settings with Redis caching (for agent calls)."""
        # Try cache first
        cached = await AgentSettingsCache.get(org_id)
        if cached:
            logger.debug(f"Agent settings cache hit for {org_id}")
            return cached
        
        # Cache miss - fetch from DB
        logger.debug(f"Agent settings cache miss for {org_id}")
        settings = await self.get_settings(org_id)
        
        # Store in cache
        await AgentSettingsCache.set(org_id, settings)
        
        return settings
    
    def get_gemini_voice(self, voice_style: str) -> str:
        """Convert voice style to Gemini voice name."""
        return VOICE_STYLE_TO_GEMINI.get(voice_style, "Charon")
    
    async def update_settings(self, org_id: UUID, request: AgentSettingsRequest) -> dict:
        """Update agent settings for organization.
        
        Only provided fields are updated; others keep their current values.
        """
        org = await self.get_organization(org_id)
        settings = org.agent_settings.copy() if org.agent_settings else DEFAULT_AGENT_SETTINGS.copy()
        
        # Update only provided fields
        if request.enabled is not None:
            settings["enabled"] = request.enabled
        if request.agent_name is not None:
            settings["agent_name"] = request.agent_name
        if request.greeting is not None:
            settings["greeting"] = request.greeting
        if request.voice_style is not None:
            settings["voice_style"] = request.voice_style
        if request.language is not None:
            settings["language"] = request.language
        if request.custom_instructions is not None:
            settings["custom_instructions"] = request.custom_instructions
        
        org.agent_settings = settings
        flag_modified(org, "agent_settings")
        
        await self.db.commit()
        await self.db.refresh(org)
        
        # Invalidate cache
        await AgentSettingsCache.invalidate(org_id)
        
        logger.info(f"Agent settings updated: org={org_id}")
        
        return await self.get_settings(org_id)
    
    async def reset_to_defaults(self, org_id: UUID) -> dict:
        """Reset agent settings to defaults."""
        org = await self.get_organization(org_id)
        
        org.agent_settings = DEFAULT_AGENT_SETTINGS.copy()
        flag_modified(org, "agent_settings")
        
        await self.db.commit()
        await self.db.refresh(org)
        
        # Invalidate cache
        await AgentSettingsCache.invalidate(org_id)
        
        logger.info(f"Agent settings reset to defaults: org={org_id}")
        
        return await self.get_settings(org_id)
