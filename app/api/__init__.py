from fastapi import APIRouter

from app.api.routes import (
    auth_router, 
    workers_router, 
    patients_router, 
    agents_router, 
    caseload_router, 
    voice_router,
    calls_router,
    livekit_webhooks_router,
    twilio_webhooks_router,
    appointments_router,
    reminders_router,
    onboarding_router,
    settings_router,
)

# Main API router
api_router = APIRouter()

# --- Authentication and User Management ---
api_router.include_router(auth_router)
api_router.include_router(workers_router)
api_router.include_router(patients_router)
api_router.include_router(agents_router)
api_router.include_router(caseload_router)
api_router.include_router(voice_router)
api_router.include_router(calls_router)

# --- Appointments and Reminders ---
api_router.include_router(appointments_router)
api_router.include_router(reminders_router)

# --- Onboarding and Settings ---
api_router.include_router(onboarding_router)
api_router.include_router(settings_router)

# --- Webhooks ---
api_router.include_router(livekit_webhooks_router)
api_router.include_router(twilio_webhooks_router)
