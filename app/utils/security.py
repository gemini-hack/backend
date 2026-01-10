from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from jose import jwt, JWTError
from fastapi import HTTPException
import secrets
import bcrypt
import hashlib
import hmac
from user_agents import parse

from app.core.config import settings


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hashed password."""
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def get_token_hash(token: str) -> str:
    """
    Create a secure hash of the token for database storage.
    SHA-256 HMAC using the secret key.
    """
    key = settings.JWT_SECRET_KEY.encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def create_access_token(
    user_id: str,
    organization_id: str,
    role: str,
    session_id: Optional[str] = None,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    payload = {
        "sub": user_id,
        "org_id": organization_id,
        "role": role,
        "sid": session_id,
        "type": "access",
        "exp": expire
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    user_id: str,
    organization_id: str,
    role: str,
    session_id: Optional[str] = None
) -> str:
    """Create a JWT refresh token with user context."""
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    user_data = {
        "user_id": user_id,
        "org_id": organization_id,
        "role": role,
        "sid": session_id
    }
    
    payload = {
        "user": user_data,
        "type": "refresh",
        "iat": datetime.now(timezone.utc),
        "exp": expire,
        "sub": user_id
    }
    if session_id:
        payload["sid"] = session_id
        
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def generate_refresh_token(subject: Optional[str] = None, role: str = "user") -> str:
    """Compatibility wrapper for older code."""
    user_id = str(subject) if subject is not None else ""
    return create_refresh_token(user_id, "", role)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT token."""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def verify_refresh_token(token: str) -> dict[str, Any]:
    """Verify and decode a refresh token. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=str(e))


def verify_reset_password_token(token: str) -> dict[str, Any]:
    """Verify and decode a password reset token. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "password_reset":
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=str(e))


def create_password_reset_token(user_id: str) -> str:
    """Create a JWT token for password reset."""
    expire = datetime.now(timezone.utc) + timedelta(hours=1)
    payload = {
        "sub": user_id,
        "type": "password_reset",
        "iat": datetime.now(timezone.utc),
        "exp": expire
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_email_verification_token(user_id: str) -> str:
    """Create a JWT token for email verification."""
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    payload = {
        "sub": user_id,
        "type": "email_verification",
        "iat": datetime.now(timezone.utc),
        "exp": expire
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_email_verification_token(token: str) -> dict[str, Any]:
    """Verify and decode an email verification token. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "email_verification":
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=str(e))


def get_device_info(user_agent_str: str) -> dict[str, Any]:
    """Parse user agent string and extract device information."""
    user_agent = parse(user_agent_str)
    
    return {
        "browser": user_agent.browser.family,
        "browser_version": user_agent.browser.version_string,
        "os": user_agent.os.family,
        "os_version": user_agent.os.version_string,
        "device": user_agent.device.family,
        "is_mobile": user_agent.is_mobile,
        "is_tablet": user_agent.is_tablet,
        "is_pc": user_agent.is_pc,
        "is_bot": user_agent.is_bot,
    }


def generate_token(length: int = 32) -> str:
    """Generate a secure random token."""
    return secrets.token_urlsafe(length)