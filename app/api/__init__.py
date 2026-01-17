"""
Main API router aggregating all route modules.
"""

from fastapi import APIRouter

from app.api.routes import auth_router, workers_router, patients_router, agents_router, caseload_router

# Main API router
api_router = APIRouter()

# --- Authentication and User Management ---
api_router.include_router(auth_router)
api_router.include_router(workers_router)
api_router.include_router(patients_router)
api_router.include_router(agents_router)
api_router.include_router(caseload_router)
