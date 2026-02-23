from typing import Any, Dict, Optional
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
import httpx
import time
import threading

from app.core.config import settings
from app.utils.logger import logger
from app.api.dependencies import CurrentUser
from app.core.observability import get_trace_context

router = APIRouter(prefix="/observability", tags=["Observability"])


def _get_jaeger_api_base() -> str:
    """
    Resolve the Jaeger Query API base URL from OTEL endpoint.
    Port 4317 is OTLP gRPC submission; 16686 is the UI / Query API.
    """
    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
    parsed = urlparse(endpoint)
    host = parsed.hostname or "localhost"
    scheme = parsed.scheme or "http"
    return f"{scheme}://{host}:16686/api"


JAEGER_API_BASE = _get_jaeger_api_base()


# =============================================================================
# Thread-safe metrics counters for Prometheus endpoint
# =============================================================================

class MetricsCollector:
    """Thread-safe metrics collector for Prometheus-style scraping."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._request_count: Dict[str, int] = {}  # key: "method:path:status"
        self._request_duration_sum: Dict[str, float] = {}
        self._request_duration_count: Dict[str, int] = {}
        self._error_count = 0
        self._total_requests = 0
    
    def record_request(self, method: str, path: str, status_code: int, duration: float):
        """Record an HTTP request."""
        with self._lock:
            self._total_requests += 1
            
            key = f"{method}:{path}:{status_code}"
            self._request_count[key] = self._request_count.get(key, 0) + 1
            self._request_duration_sum[key] = self._request_duration_sum.get(key, 0) + duration
            self._request_duration_count[key] = self._request_duration_count.get(key, 0) + 1
            
            if status_code >= 400:
                self._error_count += 1
    
    def get_prometheus_metrics(self) -> str:
        """Generate Prometheus-format metrics."""
        with self._lock:
            uptime = time.time() - self._start_time
            
            lines = [
                "# HELP mira_ai_uptime_seconds Time since application started",
                "# TYPE mira_ai_uptime_seconds gauge",
                f'mira_ai_uptime_seconds{{service="{settings.OTEL_SERVICE_NAME}"}} {uptime:.2f}',
                "",
                "# HELP mira_ai_info Application information",
                "# TYPE mira_ai_info gauge",
                f'mira_ai_info{{service="{settings.OTEL_SERVICE_NAME}",version="{settings.APP_VERSION}",otel_enabled="{str(settings.OTEL_ENABLED).lower()}"}} 1',
                "",
                "# HELP http_requests_total Total HTTP requests",
                "# TYPE http_requests_total counter",
            ]
            
            # Add per-route request counts
            for key, count in self._request_count.items():
                method, path, status = key.split(":", 2)
                lines.append(f'http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}')
            
            # Add total requests
            lines.append(f'http_requests_total{{method="all",path="all",status="all"}} {self._total_requests}')
            
            lines.extend([
                "",
                "# HELP http_errors_total Total HTTP errors (4xx and 5xx)",
                "# TYPE http_errors_total counter",
                f'http_errors_total{{service="{settings.OTEL_SERVICE_NAME}"}} {self._error_count}',
                "",
                "# HELP http_request_duration_seconds HTTP request duration",
                "# TYPE http_request_duration_seconds histogram",
            ])
            
            # Add duration metrics
            for key, total_duration in self._request_duration_sum.items():
                method, path, status = key.split(":", 2)
                count = self._request_duration_count.get(key, 1)
                avg_duration = total_duration / count if count > 0 else 0
                lines.append(f'http_request_duration_seconds_sum{{method="{method}",path="{path}",status="{status}"}} {total_duration:.4f}')
                lines.append(f'http_request_duration_seconds_count{{method="{method}",path="{path}",status="{status}"}} {count}')
            
            return "\n".join(lines)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary as dict."""
        with self._lock:
            return {
                "uptime_seconds": time.time() - self._start_time,
                "total_requests": self._total_requests,
                "total_errors": self._error_count,
                "error_rate": self._error_count / self._total_requests if self._total_requests > 0 else 0,
                "routes": len(self._request_count),
            }


# Global metrics collector instance
metrics_collector = MetricsCollector()


# =============================================================================
# Prometheus Metrics Endpoint
# =============================================================================

@router.get("/metrics", response_class=PlainTextResponse)
async def get_metrics():
    """
    Expose metrics in Prometheus text format.
    This endpoint can be scraped by Prometheus.
    """
    return metrics_collector.get_prometheus_metrics()


# =============================================================================
# Status Endpoint
# =============================================================================

@router.get("/status")
async def get_observability_status():
    """
    Get comprehensive observability status including all components.
    Does not require authentication.
    """
    summary = metrics_collector.get_summary()
    status = {
        "service": {
            "name": settings.OTEL_SERVICE_NAME,
            "version": settings.APP_VERSION,
            "uptime_seconds": summary["uptime_seconds"],
        },
        "metrics": summary,
        "observability": {
            "enabled": settings.OTEL_ENABLED,
            "endpoint": settings.OTEL_EXPORTER_OTLP_ENDPOINT if settings.OTEL_ENABLED else None,
        },
        "components": {
            "tracing": {"enabled": settings.OTEL_ENABLED, "backend": "jaeger", "healthy": False},
            "metrics": {"enabled": True, "format": "prometheus", "endpoint": "/api/v1/observability/metrics"},
            "logging": {"enabled": True, "level": settings.LOG_LEVEL},
        },
        "current_trace": get_trace_context() or None,
    }
    
    # Check Jaeger health
    if settings.OTEL_ENABLED:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(f"{JAEGER_API_BASE}/services", timeout=5.0)
                status["components"]["tracing"]["healthy"] = response.status_code == 200
            except httpx.RequestError:
                status["components"]["tracing"]["healthy"] = False
    
    return status


# =============================================================================
# Jaeger Trace Endpoints
# =============================================================================

@router.get("/traces")
async def get_traces(
    current_user: CurrentUser,
    service: str = settings.OTEL_SERVICE_NAME,
    operation: Optional[str] = None,
    limit: int = 20,
    tags: Optional[str] = None,
    lookback: str = "1h",
):
    """
    Fetch recent traces from the Jaeger Query API.
    
    Args:
        service: Service name to filter traces
        operation: Operation name to filter
        limit: Maximum number of traces to return
        tags: Tag filter in format key:value
        lookback: Time range to look back (e.g., "1h", "2d")
    """
    params = {
        "service": service,
        "limit": limit,
        "lookback": lookback,
    }
    if operation:
        params["operation"] = operation
    if tags:
        params["tags"] = tags

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{JAEGER_API_BASE}/traces", params=params, timeout=10.0)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Failed to connect to Jaeger at {JAEGER_API_BASE}: {e}")
            raise HTTPException(status_code=502, detail="Jaeger Query service unavailable")
        except httpx.HTTPStatusError as e:
            logger.error(f"Jaeger returned error: {e.response.status_code}")
            raise HTTPException(status_code=e.response.status_code, detail="Jaeger Query error")


@router.get("/traces/{trace_id}")
async def get_trace_detail(
    trace_id: str,
    current_user: CurrentUser,
):
    """
    Get detailed span information for a specific trace ID.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{JAEGER_API_BASE}/traces/{trace_id}", timeout=10.0)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Failed to connect to Jaeger: {e}")
            raise HTTPException(status_code=502, detail="Jaeger Query service unavailable")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(status_code=404, detail="Trace not found")
            logger.error(f"Failed to fetch trace {trace_id}: {e}")
            raise HTTPException(status_code=e.response.status_code, detail="Jaeger Query error")


@router.get("/services")
async def get_services(current_user: CurrentUser):
    """
    List all services currently logging to Jaeger.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{JAEGER_API_BASE}/services", timeout=10.0)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Failed to connect to Jaeger: {e}")
            raise HTTPException(status_code=502, detail="Jaeger Query service unavailable")
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch services: {e}")
            raise HTTPException(status_code=e.response.status_code, detail="Jaeger Query error")


@router.get("/operations/{service}")
async def get_operations(
    service: str,
    current_user: CurrentUser,
):
    """
    List all operations for a specific service.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{JAEGER_API_BASE}/services/{service}/operations", timeout=10.0)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Failed to connect to Jaeger: {e}")
            raise HTTPException(status_code=502, detail="Jaeger Query service unavailable")
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch operations: {e}")
            raise HTTPException(status_code=e.response.status_code, detail="Jaeger Query error")


# =============================================================================
# Health Check (Legacy - kept for backwards compatibility)
# =============================================================================

@router.get("/health")
async def observability_health():
    """
    Check if observability (tracing) is enabled and the Jaeger service is reachable.
    Does not require authentication.
    """
    health_status = {
        "otel_enabled": settings.OTEL_ENABLED,
        "service_name": settings.OTEL_SERVICE_NAME,
        "jaeger_reachable": False,
    }
    
    if settings.OTEL_ENABLED:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(f"{JAEGER_API_BASE}/services", timeout=5.0)
                health_status["jaeger_reachable"] = response.status_code == 200
            except httpx.RequestError:
                health_status["jaeger_reachable"] = False
    
    return health_status
