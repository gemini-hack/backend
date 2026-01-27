import uuid
import enum
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_model import BaseModel
from app.utils.security import encrypt_token, decrypt_token, is_token_encrypted

if TYPE_CHECKING:
    from app.models.user import User


class CalendarProvider(str, enum.Enum):
    """Supported calendar providers."""
    GOOGLE = "google"
    OUTLOOK = "outlook"


class IntegrationStatus(str, enum.Enum):
    """Status of a calendar integration."""
    ACTIVE = "active"
    NEEDS_REAUTH = "needs_reauth"
    DISABLED = "disabled"


class CalendarIntegration(BaseModel):
    """
    Stores OAuth tokens for syncing external calendars.
    
    Security: Tokens are encrypted at rest using Fernet symmetric encryption.
    The encryption key is derived from the application's JWT secret.
    """
    __tablename__ = "calendar_integrations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    
    provider: Mapped[CalendarProvider] = mapped_column(SAEnum(CalendarProvider))
    status: Mapped[IntegrationStatus] = mapped_column(
        SAEnum(IntegrationStatus), 
        default=IntegrationStatus.ACTIVE
    )
    
    # Internal encrypted storage
    _access_token: Mapped[str] = mapped_column("access_token", Text)
    _refresh_token: Mapped[str | None] = mapped_column("refresh_token", Text)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    @property
    def access_token(self) -> str:
        """Decrypt access token on access."""
        if is_token_encrypted(self._access_token):
            return decrypt_token(self._access_token)
        return self._access_token

    @access_token.setter
    def access_token(self, value: str):
        """Encrypt access token before storing."""
        self._access_token = encrypt_token(value)

    @property
    def refresh_token(self) -> Optional[str]:
        """Decrypt refresh token on access."""
        if self._refresh_token is None:
            return None
        if is_token_encrypted(self._refresh_token):
            return decrypt_token(self._refresh_token)
        return self._refresh_token

    @refresh_token.setter
    def refresh_token(self, value: Optional[str]):
        """Encrypt refresh token before storing."""
        if value is None:
            self._refresh_token = None
            return
        self._refresh_token = encrypt_token(value)

    # Sync State
    sync_token: Mapped[str | None] = mapped_column(String(255))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Calendar Info
    email: Mapped[str | None] = mapped_column(String(255)) 
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="calendar_integrations")
    
    def is_active(self) -> bool:
        """Check if integration is active and usable."""
        return self.status == IntegrationStatus.ACTIVE
    
    def needs_reauth(self) -> bool:
        """Check if integration needs re-authentication."""
        return self.status == IntegrationStatus.NEEDS_REAUTH
    
    def mark_needs_reauth(self) -> None:
        """Mark integration as needing re-authentication."""
        self.status = IntegrationStatus.NEEDS_REAUTH
    
    def mark_active(self) -> None:
        """Mark integration as active."""
        self.status = IntegrationStatus.ACTIVE
