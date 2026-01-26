from fastapi import HTTPException, status


class BaseAPIException(HTTPException):
    """Base exception for API errors."""
    
    def __init__(
        self,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail: str = "An error occurred",
    ):
        super().__init__(status_code=status_code, detail=detail)


# ============== Authentication Exceptions ==============

class InvalidCredentialsException(BaseAPIException):
    """Invalid email or password."""
    
    def __init__(self, detail: str = "Invalid email or password"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )


class AccountLockedException(BaseAPIException):
    """Account is locked due to too many failed login attempts."""
    
    def __init__(self, detail: str = "Account is locked due to too many failed login attempts. Please try again later."):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


class AccountInactiveException(BaseAPIException):
    """Account is not active."""
    
    def __init__(self, detail: str = "Account is not active"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


class EmailNotVerifiedException(BaseAPIException):
    """Email address is not verified."""
    
    def __init__(self, detail: str = "Email address is not verified. Please check your email for verification link."):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


# ============== Token Exceptions ==============

class TokenExpiredException(BaseAPIException):
    """Token has expired."""
    
    def __init__(self, detail: str = "Token has expired"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )


class TokenInvalidException(BaseAPIException):
    """Token is invalid."""
    
    def __init__(self, detail: str = "Invalid token"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )


# ============== User/Organization Exceptions ==============

class UserAlreadyExistsException(BaseAPIException):
    """User with this email already exists."""
    
    def __init__(self, detail: str = "A user with this email already exists"):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )


class OrganizationAlreadyExistsException(BaseAPIException):
    """Organization with this email already exists."""
    
    def __init__(self, detail: str = "An organization with this email already exists"):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )


# ============== Invitation Exceptions ==============

class InvitationExpiredException(BaseAPIException):
    """Invitation has expired."""
    
    def __init__(self, detail: str = "Invitation has expired"):
        super().__init__(
            status_code=status.HTTP_410_GONE,
            detail=detail,
        )


class InvitationAlreadyUsedException(BaseAPIException):
    """Invitation has already been used."""
    
    def __init__(self, detail: str = "Invitation has already been used"):
        super().__init__(
            status_code=status.HTTP_410_GONE,
            detail=detail,
        )


class InvitationNotFoundException(BaseAPIException):
    """Invitation not found."""
    
    def __init__(self, detail: str = "Invitation not found"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
        )


# ============== Permission Exceptions ==============

class PermissionDeniedException(BaseAPIException):
    """Permission denied."""
    
    def __init__(self, detail: str = "Permission denied"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


# ============== General Exceptions ==============

class NotFoundException(BaseAPIException):
    """Resource not found."""
    
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
        )


class BadRequestException(BaseAPIException):
    """Bad request."""
    
    def __init__(self, detail: str = "Bad request"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )


# ============== Service Exceptions ==============

class EmailDeliveryError(Exception):
    """Raised when email delivery fails."""
    
    def __init__(self, message: str, to_email: str = None, original_error: Exception = None):
        self.to_email = to_email
        self.original_error = original_error
        super().__init__(message)


# ============== Calendar Integration Exceptions ==============

class CalendarServiceError(Exception):
    """Base exception for calendar service errors."""
    
    def __init__(self, message: str = "Calendar service error", details: dict | None = None):
        self.message = message
        self.details = details or {}
        self.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        super().__init__(self.message)


class CalendarAuthError(CalendarServiceError):
    """Authentication/authorization errors (invalid credentials, revoked access)."""
    
    def __init__(self, message: str = "Calendar authentication failed", details: dict | None = None):
        super().__init__(message, details)
        self.status_code = status.HTTP_401_UNAUTHORIZED


class CalendarTokenExpiredError(CalendarAuthError):
    """Token has expired and cannot be refreshed."""
    
    def __init__(self, message: str = "Calendar token expired", details: dict | None = None):
        super().__init__(message, details)
        self.status_code = status.HTTP_401_UNAUTHORIZED


class CalendarAPIError(CalendarServiceError):
    """External API errors from the calendar provider."""
    
    def __init__(self, message: str = "Calendar API error", status_code: int | None = None, details: dict | None = None):
        super().__init__(message, details)
        self.status_code = status_code or status.HTTP_502_BAD_GATEWAY


class CalendarRateLimitError(CalendarAPIError):
    """Rate limit exceeded on calendar API."""
    
    def __init__(self, message: str = "Rate limit exceeded", retry_after: int | None = None):
        super().__init__(message, status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        self.retry_after = retry_after
