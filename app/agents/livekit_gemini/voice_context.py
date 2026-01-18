from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from app.core.permissions import ROLE_PERMISSIONS
from app.models.user import UserRole

__all__ = [
    "VoiceAgentUserContext",
    "get_current_voice_context",
    "set_current_voice_context",
    "clear_voice_context",
]


@dataclass
class VoiceAgentUserContext:
    """User context for voice agent sessions."""

    user_id: UUID
    organization_id: UUID
    role: UserRole
    full_name: str

    def has_permission(self, permission: str) -> bool:
        """Check if the user has a specific permission.

        Args:
            permission: Permission string in format "resource:action"

        Returns:
            True if user has the permission, False otherwise
        """
        user_permissions = ROLE_PERMISSIONS.get(self.role, [])

        # Superuser wildcard grants all permissions
        if "*" in user_permissions:
            return True

        # Exact match
        if permission in user_permissions:
            return True

        # Resource wildcard (e.g., "patients:*" matches "patients:read")
        if ":" in permission:
            resource = permission.split(":")[0]
            if f"{resource}:*" in user_permissions:
                return True

        return False

    @property
    def permissions(self) -> list[str]:
        """Get all permissions for this user's role."""
        return ROLE_PERMISSIONS.get(self.role, [])


# Context variable for the current voice session user
_current_context: ContextVar[Optional[VoiceAgentUserContext]] = ContextVar(
    "voice_agent_user_context",
    default=None,
)


def get_current_voice_context() -> Optional[VoiceAgentUserContext]:
    """Get the current voice agent user context."""
    return _current_context.get()


def set_current_voice_context(ctx: VoiceAgentUserContext) -> None:
    """Set the current voice agent user context."""
    _current_context.set(ctx)


def clear_voice_context() -> None:
    """Clear the current voice agent user context."""
    _current_context.set(None)
