from fastapi import APIRouter

from app.api.routes import (
    agents_router,
    analytics_router,
    appointments_router,
    auth_router,
    calls_router,
    caseload_router,
    ehr_router,
    integrations_router,
    livekit_webhooks_router,
    onboarding_router,
    patients_router,
    reminders_router,
    settings_router,
    teams_router,
    twilio_webhooks_router,
    voice_router,
    workers_router,
    observability_router,
)

# Main API router
api_router = APIRouter()

# --- Alphabetical API Routers ---
api_router.include_router(agents_router)
api_router.include_router(analytics_router)
api_router.include_router(appointments_router)
api_router.include_router(auth_router)
api_router.include_router(calls_router)
api_router.include_router(caseload_router)
api_router.include_router(ehr_router)
api_router.include_router(integrations_router)
api_router.include_router(onboarding_router)
api_router.include_router(patients_router)
api_router.include_router(reminders_router)
api_router.include_router(settings_router)
api_router.include_router(teams_router)
api_router.include_router(twilio_webhooks_router)
api_router.include_router(voice_router)
api_router.include_router(livekit_webhooks_router)  # Tag: Webhooks
api_router.include_router(workers_router)
api_router.include_router(observability_router)
