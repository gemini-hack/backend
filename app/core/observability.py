"""
Comprehensive Observability Module for Mira AI Backend.

This module provides:
- Distributed Tracing (OpenTelemetry -> Jaeger)
- Metrics (Prometheus format via OTLP)
- Log correlation with trace context
"""

import asyncio
import functools
import inspect
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Optional

from opentelemetry import trace, metrics
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter
from opentelemetry.trace import get_current_span
from opentelemetry.trace.status import Status, StatusCode

from app.core.config import settings
from app.utils.logger import logger

# Global instances
_tracer: Optional[trace.Tracer] = None
_meter: Optional[metrics.Meter] = None
_initialized = False

# Metrics collectors
_request_counter = None
_request_duration = None
_error_counter = None
_active_requests = None
_db_query_duration = None
_external_call_duration = None


def get_tracer() -> trace.Tracer:
    """Get the global tracer instance."""
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer(settings.OTEL_SERVICE_NAME, settings.APP_VERSION)
    return _tracer


def get_meter() -> metrics.Meter:
    """Get the global meter instance for metrics."""
    global _meter
    if _meter is None:
        _meter = metrics.get_meter(settings.OTEL_SERVICE_NAME, settings.APP_VERSION)
    return _meter


def _create_resource() -> Resource:
    """Create OpenTelemetry resource with service metadata."""
    return Resource.create({
        SERVICE_NAME: settings.OTEL_SERVICE_NAME,
        "service.version": settings.APP_VERSION,
        "service.namespace": "mira-ai",
        "deployment.environment": "production" if not settings.DEBUG else "development",
    })


def _setup_tracing(resource: Resource) -> None:
    """Initialize OpenTelemetry tracing."""
    provider = TracerProvider(resource=resource)
    
    # OTLP exporter for Jaeger/collector
    otlp_exporter = OTLPSpanExporter(
        endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        insecure=True,
    )
    provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    
    # Console exporter for debugging
    if settings.DEBUG:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    
    trace.set_tracer_provider(provider)
    logger.info(f"Tracing initialized -> {settings.OTEL_EXPORTER_OTLP_ENDPOINT}")


def _setup_metrics(resource: Resource) -> None:
    """Initialize OpenTelemetry metrics."""
    global _request_counter, _request_duration, _error_counter
    global _active_requests, _db_query_duration, _external_call_duration
    
    # OTLP metric exporter
    otlp_metric_exporter = OTLPMetricExporter(
        endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        insecure=True,
    )
    
    readers = [PeriodicExportingMetricReader(otlp_metric_exporter, export_interval_millis=30000)]
    
    # Console exporter for debugging
    if settings.DEBUG:
        readers.append(PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=60000))
    
    provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(provider)
    
    # Create standard metrics
    meter = get_meter()
    
    # HTTP request metrics
    _request_counter = meter.create_counter(
        name="http_requests_total",
        description="Total number of HTTP requests",
        unit="1",
    )
    
    _request_duration = meter.create_histogram(
        name="http_request_duration_seconds",
        description="HTTP request duration in seconds",
        unit="s",
    )
    
    _error_counter = meter.create_counter(
        name="http_errors_total",
        description="Total number of HTTP errors",
        unit="1",
    )
    
    _active_requests = meter.create_up_down_counter(
        name="http_requests_active",
        description="Number of active HTTP requests",
        unit="1",
    )
    
    # Database metrics
    _db_query_duration = meter.create_histogram(
        name="db_query_duration_seconds",
        description="Database query duration in seconds",
        unit="s",
    )
    
    # External call metrics
    _external_call_duration = meter.create_histogram(
        name="external_call_duration_seconds",
        description="External API call duration in seconds",
        unit="s",
    )
    
    logger.info("Metrics initialized")


def setup_observability() -> None:
    """Initialize all observability components (tracing, metrics, logging)."""
    global _initialized
    
    if _initialized:
        return
    
    if not settings.OTEL_ENABLED:
        logger.info("OpenTelemetry observability is disabled.")
        return
    
    try:
        resource = _create_resource()
        _setup_tracing(resource)
        
        # Only setup metrics if explicitly enabled (requires a collector)
        if settings.OTEL_METRICS_ENABLED:
            _setup_metrics(resource)
        else:
            logger.info("OpenTelemetry metrics disabled (OTEL_METRICS_ENABLED=false)")
        
        _initialized = True
        logger.info(f"Observability initialized for '{settings.OTEL_SERVICE_NAME}'")
    except Exception as e:
        logger.error(f"Failed to initialize observability: {e}")


# Alias for backwards compatibility
setup_tracing = setup_observability


# =============================================================================
# Metrics Recording Helpers
# =============================================================================

def record_request(method: str, path: str, status_code: int, duration: float) -> None:
    """Record HTTP request metrics."""
    if not settings.OTEL_ENABLED or _request_counter is None:
        return
    
    attributes = {
        "http.method": method,
        "http.route": path,
        "http.status_code": status_code,
    }
    
    _request_counter.add(1, attributes)
    _request_duration.record(duration, attributes)
    
    if status_code >= 400:
        _error_counter.add(1, attributes)


def record_db_query(operation: str, table: str, duration: float, success: bool = True) -> None:
    """Record database query metrics."""
    if not settings.OTEL_ENABLED or _db_query_duration is None:
        return
    
    attributes = {
        "db.operation": operation,
        "db.table": table,
        "db.success": str(success).lower(),
    }
    _db_query_duration.record(duration, attributes)


def record_external_call(service: str, operation: str, duration: float, success: bool = True) -> None:
    """Record external API call metrics."""
    if not settings.OTEL_ENABLED or _external_call_duration is None:
        return
    
    attributes = {
        "external.service": service,
        "external.operation": operation,
        "external.success": str(success).lower(),
    }
    _external_call_duration.record(duration, attributes)


@contextmanager
def track_active_request():
    """Context manager to track active requests."""
    if settings.OTEL_ENABLED and _active_requests is not None:
        _active_requests.add(1)
        try:
            yield
        finally:
            _active_requests.add(-1)
    else:
        yield


# =============================================================================
# Custom Metrics Creation
# =============================================================================

def create_counter(name: str, description: str, unit: str = "1"):
    """Create a custom counter metric."""
    if not settings.OTEL_ENABLED:
        return None
    return get_meter().create_counter(name=name, description=description, unit=unit)


def create_histogram(name: str, description: str, unit: str = "1"):
    """Create a custom histogram metric."""
    if not settings.OTEL_ENABLED:
        return None
    return get_meter().create_histogram(name=name, description=description, unit=unit)


def create_gauge(name: str, description: str, unit: str = "1"):
    """Create a custom gauge metric (using UpDownCounter)."""
    if not settings.OTEL_ENABLED:
        return None
    return get_meter().create_up_down_counter(name=name, description=description, unit=unit)


# =============================================================================
# Trace Context for Logging
# =============================================================================

def get_trace_context() -> Dict[str, str]:
    """Get current trace context for log correlation."""
    span = get_current_span()
    if span and span.get_span_context().is_valid:
        ctx = span.get_span_context()
        return {
            "trace_id": format(ctx.trace_id, "032x"),
            "span_id": format(ctx.span_id, "016x"),
        }
    return {}


def inject_trace_context(log_record: Dict[str, Any]) -> Dict[str, Any]:
    """Inject trace context into a log record for correlation."""
    trace_ctx = get_trace_context()
    if trace_ctx:
        log_record.update(trace_ctx)
    return log_record


# =============================================================================
# Decorators
# =============================================================================

def trace_method(name: Optional[str] = None, attributes: Optional[Dict[str, str]] = None):
    """
    Decorator to trace a method call with OpenTelemetry.
    
    Args:
        name: Custom span name (defaults to function name)
        attributes: Additional span attributes
    """
    def decorator(func: Callable):
        span_name = name or func.__name__
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not settings.OTEL_ENABLED:
                return await func(*args, **kwargs)
            
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                try:
                    result = await func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not settings.OTEL_ENABLED:
                return func(*args, **kwargs)
            
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                try:
                    result = func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    raise

        return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper
    return decorator


def timed_operation(metric_name: str, operation: str):
    """
    Decorator to measure and record operation duration.
    
    Args:
        metric_name: Name of the histogram metric
        operation: Operation name for attributes
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            success = True
            try:
                return await func(*args, **kwargs)
            except Exception:
                success = False
                raise
            finally:
                duration = time.perf_counter() - start_time
                if settings.OTEL_ENABLED:
                    histogram = get_meter().create_histogram(
                        name=metric_name,
                        description=f"Duration of {operation}",
                        unit="s"
                    )
                    histogram.record(duration, {"operation": operation, "success": str(success).lower()})

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            success = True
            try:
                return func(*args, **kwargs)
            except Exception:
                success = False
                raise
            finally:
                duration = time.perf_counter() - start_time
                if settings.OTEL_ENABLED:
                    histogram = get_meter().create_histogram(
                        name=metric_name,
                        description=f"Duration of {operation}",
                        unit="s"
                    )
                    histogram.record(duration, {"operation": operation, "success": str(success).lower()})

        return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper
    return decorator
