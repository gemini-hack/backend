import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.utils.logger import set_correlation_id, clear_correlation_id


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    
    Middleware to extract or generate correlation IDs for request tracing.
    """
    
    def __init__(self, app, correlation_id_header: str = "X-Correlation-ID"):

        super().__init__(app)
        self.correlation_id_header = correlation_id_header
    
    async def dispatch(self, request: Request, call_next):
        # Extract correlation ID from request headers
        correlation_id = (
            request.headers.get(self.correlation_id_header) or
            request.headers.get(self.correlation_id_header.lower())
        )
        
        # Generate new correlation ID if not provided
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
        
        # Set in logging context
        set_correlation_id(correlation_id)
        
        try:
            # Process the request
            response = await call_next(request)
            
            # Add correlation ID to response headers for client tracking
            response.headers[self.correlation_id_header] = correlation_id
            
            return response
        finally:
            # Context cleanup after request completes
            clear_correlation_id()
