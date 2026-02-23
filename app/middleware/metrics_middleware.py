import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.observability import record_request, track_active_request


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to collect HTTP request metrics."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get request info
        method = request.method
        path = self._get_route_path(request)
        
        # Track request timing and active requests
        start_time = time.perf_counter()
        status_code = 500  # Default to error in case of exception
        
        with track_active_request():
            try:
                response = await call_next(request)
                status_code = response.status_code
                return response
            except Exception:
                # Re-raise the exception after recording metrics
                raise
            finally:
                duration = time.perf_counter() - start_time
                
                # Record in OTEL (if enabled)
                record_request(method, path, status_code, duration)
                
                # Record in Prometheus collector (always)
                try:
                    from app.api.routes.observability import metrics_collector
                    metrics_collector.record_request(method, path, status_code, duration)
                except ImportError:
                    pass
    
    def _get_route_path(self, request: Request) -> str:
        """
        Get the route path template instead of the actual path.
        This prevents high cardinality in metrics (e.g., /users/123 -> /users/{id}).
        """
        # Try to get the matched route
        if hasattr(request, "scope") and "route" in request.scope:
            route = request.scope.get("route")
            if route and hasattr(route, "path"):
                return route.path
        
        # Fall back to the actual path (with some normalization)
        path = request.url.path
        
        # Normalize common patterns to reduce cardinality
        # Remove trailing slashes
        path = path.rstrip("/") or "/"
        
        return path
