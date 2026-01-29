from fastapi import APIRouter

from app.api.routes import (
    # Auth & Onboarding
    auth_router,
    onboarding_router,
    
    # Organization & Management
    teams_router,
    workers_router,
    settings_router,
    
    # Core Healthcare Logic
    patients_router,
    appointments_router,
    caseload_router,
    reminders_router,
    
    # Voice & AI Features
    agents_router,
    voice_router,
    calls_router,
    
    # External Integrations
    integrations_router,
    ehr_router,
    
    # Webhooks
    livekit_webhooks_router,
    twilio_webhooks_router,
    appointments_router,
    reminders_router,
    onboarding_router,
    settings_router,
    teams_router,
    analytics_router,
)

# Main API router
api_router = APIRouter()

# --- 1. Authentication and Onboarding ---
api_router.include_router(auth_router)
api_router.include_router(onboarding_router)

# --- 2. Organization and Management ---
api_router.include_router(teams_router)
api_router.include_router(workers_router)
api_router.include_router(settings_router)

# --- 3. Core Healthcare Logic ---
api_router.include_router(patients_router)
api_router.include_router(appointments_router)
api_router.include_router(caseload_router)
api_router.include_router(reminders_router)

# --- 4. Voice and AI Features ---
api_router.include_router(agents_router)
api_router.include_router(voice_router)
api_router.include_router(calls_router)

# --- 5. External Integrations ---
api_router.include_router(integrations_router)
api_router.include_router(ehr_router)

# --- 6. Event Webhooks ---
api_router.include_router(livekit_webhooks_router)
api_router.include_router(twilio_webhooks_router)

# --- Analytics ---
api_router.include_router(analytics_router)

