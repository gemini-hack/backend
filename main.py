from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError, HTTPException

from app.core.config import settings
from app.middleware.correlation_middleware import CorrelationIdMiddleware
from app.api import api_router
from app.utils.logger import logger
from app.db.database import engine
from app.core.redis import RedisManager
from app.utils.exceptions import BaseAPIException
from app.utils.exception_handlers import (
    base_api_exception_handler,
    request_validation_exception_handler,
    http_exception_handler,
    general_exception_handler,
)

# Configure basic logging for uvicorn integration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager - handles startup and shutdown."""
    # Startup
    logger.info(f"Starting {settings.APP_NAME}...")
    await RedisManager.connect()
    
    yield
    
    # Shutdown
    logger.info("Shutting down application...")
    await RedisManager.close()
    await engine.dispose()
    logger.info(f"{settings.APP_NAME} stopped.")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="API for Mira AI - Healthcare provider assistant for patient management",
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,

    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Rate Limiter
from app.core.rate_limiter import init_rate_limiter
init_rate_limiter(app)

# Add correlation ID middleware
app.add_middleware(CorrelationIdMiddleware)

# Register exception handlers
app.add_exception_handler(BaseAPIException, base_api_exception_handler)
app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Include API router
app.include_router(api_router, prefix="/api/v1")


# Health check endpoints
@app.get("/", tags=["Health"], include_in_schema=False)
async def root():
    return {
        "message": f"Welcome to {settings.APP_NAME} API",
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health", tags=["Health"], include_in_schema=False)
async def health_check():
    return {"status": "healthy"}
