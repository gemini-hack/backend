"""
Rate limiter configuration using slowapi.

Backed by Redis for persistence across workers.
"""
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.utils.logger import logger

# Initialize limiter
# By default, use remote IP address as key
# Storage URL is pulled from settings.REDIS_URL
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
    default_limits=["1000/hour"], # High default limit to catch runaway scripts
    enabled=not settings.DEBUG,
)

def init_rate_limiter(app):
    """
    Initialize rate limiter on the FastAPI app.
    
    1. Attach limiter to app state
    2. Add exception handler for 429 errors
    3. Add middleware
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    logger.info("Rate limiter initialized")
