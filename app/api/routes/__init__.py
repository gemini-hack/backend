from app.api.routes.auth import router as auth_router
from app.api.routes.workers import router as workers_router
from app.api.routes.patients import router as patients_router
from app.api.routes.agents import router as agents_router
from app.api.routes.caseload import router as caseload_router
from app.api.routes.voice import router as voice_router

__all__ = [
    "auth_router",
    "workers_router",
    "patients_router",
    "agents_router",
    "caseload_router",
    "voice_router",
]
