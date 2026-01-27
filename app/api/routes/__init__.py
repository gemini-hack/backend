# Auth & Onboarding
from app.api.routes.auth import router as auth_router
from app.api.routes.onboarding import router as onboarding_router

# Organization & Management
from app.api.routes.teams import router as teams_router
from app.api.routes.workers import router as workers_router
from app.api.routes.settings import router as settings_router

# Core Healthcare Logic
from app.api.routes.patients import router as patients_router
from app.api.routes.appointments import router as appointments_router
from app.api.routes.caseload import router as caseload_router
from app.api.routes.reminders import router as reminders_router

# Voice & AI Features
from app.api.routes.agents import router as agents_router
from app.api.routes.voice import router as voice_router
from app.api.routes.calls import router as calls_router

# External Integrations
from .integrations import router as integrations_router

# Webhooks & System
from app.api.routes.livekit_webhooks import router as livekit_webhooks_router
from app.api.routes.twilio_webhooks import router as twilio_webhooks_router
from app.api.routes.appointments import router as appointments_router
from app.api.routes.reminders import router as reminders_router
from app.api.routes.onboarding import router as onboarding_router
from app.api.routes.settings import router as settings_router
from app.api.routes.teams import router as teams_router
from app.api.routes.analytics import router as analytics_router

__all__ = [
    "auth_router",
    "onboarding_router",
    "teams_router",
    "workers_router",
    "settings_router",
    "patients_router",
    "appointments_router",
    "caseload_router",
    "reminders_router",
    "agents_router",
    "voice_router",
    "calls_router",
    "integrations_router",
    "livekit_webhooks_router",
    "twilio_webhooks_router",
    "appointments_router",
    "reminders_router",
    "onboarding_router",
    "settings_router",
    "teams_router",
    "analytics_router",
]
