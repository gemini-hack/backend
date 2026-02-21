from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError, HTTPException

from app.utils.logger import logger
from app.utils.exceptions import BaseAPIException, CalendarServiceError


async def base_api_exception_handler(request: Request, exc: BaseAPIException):
    """Handle custom API exceptions and log them."""
    logger.error(
        f"{exc.__class__.__name__}: {exc.detail}",
        extra={
            "status_code": exc.status_code,
            "path": request.url.path,
            "method": request.method,
        }
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "failure",
            "status_code": exc.status_code,
            "message": exc.detail,
            "error": {}
        }
    )


async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors and log them."""
    logger.warning(
        f"Validation error on {request.method} {request.url.path}",
    )
    safe_errors = []
    for err in exc.errors():
        safe_err = {
            "loc": err.get("loc"),
            "msg": err.get("msg"),
            "type": err.get("type"),
        }
        safe_errors.append(safe_err)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "status": "failure",
            "status_code": 422,
            "message": "Validation error",
            "error": {"details": safe_errors}
        }
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTPException and log them."""
    logger.error(
        f"HTTP {exc.status_code}: {exc.detail}",
        extra={
            "path": request.url.path,
            "method": request.method,
        }
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "failure",
            "status_code": exc.status_code,
            "message": exc.detail,
            "error": {}
        }
    )


async def calendar_service_exception_handler(request: Request, exc: CalendarServiceError):
    """Handle calendar service exceptions with proper status codes."""
    logger.warning(
        f"Calendar error on {request.method} {request.url.path}: {exc.message}",
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "failure",
            "status_code": exc.status_code,
            "message": exc.message,
            "error": {}
        }
    )


async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions and log them."""
    logger.exception(
        f"Unhandled exception on {request.method} {request.url.path}: {str(exc)}",
        exc_info=exc
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "failure",
            "status_code": 500,
            "message": "An unexpected error occurred",
            "error": {}
        }
    )
