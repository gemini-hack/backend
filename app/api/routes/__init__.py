from app.api.routes.agents import router as agents_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.appointments import router as appointments_router
from app.api.routes.auth import router as auth_router
from app.api.routes.calls import router as calls_router
from app.api.routes.caseload import router as caseload_router
from app.api.routes.ehr import router as ehr_router
from app.api.routes.integrations import router as integrations_router
from app.api.routes.livekit_webhooks import router as livekit_webhooks_router
from app.api.routes.onboarding import router as onboarding_router
from app.api.routes.patients import router as patients_router
from app.api.routes.reminders import router as reminders_router
from app.api.routes.settings import router as settings_router
from app.api.routes.teams import router as teams_router
from app.api.routes.twilio_webhooks import router as twilio_webhooks_router
from app.api.routes.voice import router as voice_router
from app.api.routes.workers import router as workers_router
from app.api.routes.observability import router as observability_router

__all__ = [
    "agents_router",
    "analytics_router",
    "appointments_router",
    "auth_router",
    "calls_router",
    "caseload_router",
    "ehr_router",
    "integrations_router",
    "livekit_webhooks_router",
    "onboarding_router",
    "patients_router",
    "reminders_router",
    "settings_router",
    "teams_router",
    "twilio_webhooks_router",
    "voice_router",
    "workers_router",
    "observability_router",
]
