import json
import logging
import re
from datetime import datetime
from functools import wraps
from typing import Any, Callable

from app.utils.logger import logger

from .voice_context import get_current_voice_context

__all__ = [
    "validate_input",
    "sanitize_query_input",
    "audit_log",
    "require_permission",
]

# Sensitive fields to redact from logs
_SENSITIVE_FIELDS = frozenset({"password", "token", "secret", "api_key"})

# Patterns indicating potential injection attacks
_FORBIDDEN_PATTERNS = [
    re.compile(r"--", re.IGNORECASE),  # SQL comment
    re.compile(r";.*(?:DROP|DELETE|UPDATE|INSERT|TRUNCATE)", re.IGNORECASE),
    re.compile(r"<script", re.IGNORECASE),  # XSS
    re.compile(r"{{.*}}"),  # Template injection
    re.compile(r"\$\{.*\}"),  # Expression injection
]


def validate_input(
    value: str,
    *,
    max_length: int = 200,
    allow_empty: bool = False,
    field_name: str = "input",
) -> tuple[bool, str | None]:
    """Validate user input for security concerns.

    Args:
        value: The input value to validate
        max_length: Maximum allowed length
        allow_empty: Whether empty strings are allowed
        field_name: Name of the field for error messages

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Handle None
    if value is None:
        return (True, None) if allow_empty else (False, f"{field_name} cannot be empty.")

    # Type check
    if not isinstance(value, str):
        return False, f"{field_name} must be a string."

    # Empty check
    if not value.strip() and not allow_empty:
        return False, f"{field_name} cannot be empty."

    # Length check
    if len(value) > max_length:
        logger.warning("[SECURITY] Input too long: %d > %d", len(value), max_length)
        return False, f"{field_name} is too long (max {max_length} characters)."

    # Pattern check
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(value):
            logger.warning("[SECURITY] Blocked suspicious pattern: %.50s...", value)
            return False, f"Invalid characters detected in {field_name}."

    return True, None


def sanitize_query_input(value: str) -> str:
    """Sanitize input for use in database queries.

    Removes potentially dangerous characters while preserving semantic meaning.

    Args:
        value: The input to sanitize

    Returns:
        Sanitized string safe for queries
    """
    if not value:
        return value

    # Strip whitespace and null bytes
    value = value.strip().replace("\x00", "")

    # Remove control characters except common whitespace
    return "".join(c for c in value if c.isprintable() or c in "\n\r\t")


def audit_log(
    tool_name: str,
    input_data: dict[str, Any],
    result_summary: str,
    *,
    user_id: str | None = None,
    org_id: str | None = None,
    success: bool = True,
) -> None:
    """Log a tool invocation for security auditing.

    Args:
        tool_name: Name of the tool being called
        input_data: Dictionary of input parameters
        result_summary: Brief summary of the result
        user_id: ID of the user making the request
        org_id: ID of the organization
        success: Whether the tool execution was successful
    """
    # Truncate long results
    if len(result_summary) > 100:
        result_summary = f"{result_summary[:97]}..."

    # Redact sensitive fields
    safe_input = {
        k: "[REDACTED]" if k in _SENSITIVE_FIELDS else v
        for k, v in input_data.items()
    }

    log_entry = {
        "event": "tool_invocation",
        "tool": tool_name,
        "input": safe_input,
        "result_preview": result_summary,
        "user_id": user_id,
        "org_id": org_id,
        "success": success,
        "timestamp": f"{datetime.utcnow().isoformat()}Z",
    }

    level = logging.INFO if success else logging.WARNING
    logger.log(level, "[AUDIT] %s", json.dumps(log_entry))


def require_permission(permission: str) -> Callable:
    """Decorator to require a specific permission for a tool.

    Uses the voice agent context to check if the current user has the
    required permission based on their role.

    Usage:
        @require_permission("patients:read")
        @function_tool
        async def get_patient_info(...):
            ...

    Args:
        permission: Permission string in format "resource:action"

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            ctx = get_current_voice_context()

            if ctx is None:
                # No context - log warning but allow in development
                logger.warning(
                    "[SECURITY] No voice context for permission check: %s",
                    permission,
                )
                return await func(*args, **kwargs)

            if not ctx.has_permission(permission):
                logger.warning(
                    "[SECURITY] Permission denied: user=%s role=%s permission=%s",
                    ctx.user_id,
                    ctx.role,
                    permission,
                )
                audit_log(
                    func.__name__,
                    {"permission": permission},
                    f"Permission denied: {permission}",
                    user_id=str(ctx.user_id),
                    org_id=str(ctx.organization_id),
                    success=False,
                )
                return "You don't have permission to perform this action."

            return await func(*args, **kwargs)

        return wrapper

    return decorator
