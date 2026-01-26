"""Pydantic schemas for calendar integration endpoints."""

from datetime import datetime
from typing import Optional
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field


class CalendarProvider(str, Enum):
    """Supported calendar providers."""
    GOOGLE = "google"
    OUTLOOK = "outlook"


class IntegrationStatus(str, Enum):
    """Status of a calendar integration."""
    ACTIVE = "active"
    NEEDS_REAUTH = "needs_reauth"
    DISABLED = "disabled"


# Request Schemas

class InitiateAuthRequest(BaseModel):
    """Request to initiate OAuth flow (optional, for future use)."""
    provider: CalendarProvider = CalendarProvider.GOOGLE


# Response Schemas

class CalendarIntegrationResponse(BaseModel):
    """Response schema for calendar integration details."""
    id: UUID
    provider: CalendarProvider
    status: IntegrationStatus
    email: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    
    model_config = {"from_attributes": True}


class CalendarStatusResponse(BaseModel):
    """Response schema for calendar connection status check."""
    connected: bool
    status: Optional[IntegrationStatus] = None
    provider: Optional[CalendarProvider] = None
    email: Optional[str] = None
    last_synced_at: Optional[datetime] = None


class InitiateAuthResponse(BaseModel):
    """Response after initiating OAuth flow."""
    message: str
    provider: CalendarProvider


class DisconnectResponse(BaseModel):
    """Response after disconnecting calendar."""
    message: str
    provider: CalendarProvider


class CalendarListItem(BaseModel):
    """A calendar in the user's calendar list."""
    id: str
    summary: str
    description: Optional[str] = None
    primary: bool = False
    selected: bool = False  # Whether to check this calendar for availability


class CalendarListResponse(BaseModel):
    """Response containing user's calendars."""
    calendars: list[CalendarListItem]


class BusyPeriod(BaseModel):
    """A busy time slot from the calendar."""
    start: datetime
    end: datetime


class BusyPeriodsResponse(BaseModel):
    """Response containing busy periods."""
    busy_periods: list[BusyPeriod]
    calendar_ids: list[str] = Field(default_factory=lambda: ["primary"])
