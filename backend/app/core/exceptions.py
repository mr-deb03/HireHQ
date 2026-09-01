"""Domain exceptions and their HTTP mapping.

Every error the API returns is one of these (or an unexpected 500), so the response
envelope in ``app.core.responses`` always has a stable, documented ``error.code``.
"""

from __future__ import annotations

from typing import Any


class HireHQError(Exception):
    """Base class for all expected, user-facing failures."""

    status_code: int = 400
    code: str = "BAD_REQUEST"
    message: str = "Request could not be processed"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.__class__.message
        self.code = code or self.__class__.code
        self.details = details or {}
        super().__init__(self.message)


# ------------------------------------------------------------------ 400 / 422
class ValidationError(HireHQError):
    status_code = 422
    code = "VALIDATION_ERROR"
    message = "The submitted data is invalid"


class BusinessRuleError(HireHQError):
    status_code = 409
    code = "BUSINESS_RULE_VIOLATION"
    message = "This operation is not allowed in the current state"


class InvalidStateTransition(BusinessRuleError):
    code = "INVALID_STATE_TRANSITION"
    message = "That status change is not permitted from the current status"


class DuplicateResource(HireHQError):
    status_code = 409
    code = "DUPLICATE_RESOURCE"
    message = "A resource with these details already exists"


# ------------------------------------------------------------------- 401 / 403
class AuthenticationError(HireHQError):
    status_code = 401
    code = "AUTHENTICATION_FAILED"
    message = "Authentication is required"


class InvalidCredentials(AuthenticationError):
    code = "INVALID_CREDENTIALS"
    message = "Incorrect email or password"


class TokenExpired(AuthenticationError):
    code = "TOKEN_EXPIRED"
    message = "Your session has expired, please sign in again"


class InvalidToken(AuthenticationError):
    code = "INVALID_TOKEN"
    message = "The provided token is invalid"


class AccountInactive(AuthenticationError):
    status_code = 403
    code = "ACCOUNT_INACTIVE"
    message = "This account is not active"


class EmailNotVerified(AuthenticationError):
    status_code = 403
    code = "EMAIL_NOT_VERIFIED"
    message = "Please verify your email address to continue"


class PermissionDenied(HireHQError):
    status_code = 403
    code = "PERMISSION_DENIED"
    message = "You do not have permission to perform this action"


class TenantIsolationViolation(PermissionDenied):
    # Deliberately indistinguishable from a 404 in the message so cross-tenant probing
    # cannot be used to confirm that a resource exists in another company.
    code = "RESOURCE_NOT_FOUND"
    status_code = 404
    message = "Resource not found"


# ------------------------------------------------------------------------- 404
class ResourceNotFound(HireHQError):
    status_code = 404
    code = "RESOURCE_NOT_FOUND"
    message = "Resource not found"

    def __init__(self, resource: str = "Resource", identifier: Any = None) -> None:
        code = f"{resource.upper().replace(' ', '_')}_NOT_FOUND"
        message = f"{resource} not found"
        super().__init__(message, code=code, details={"identifier": str(identifier)} if identifier else None)


# ------------------------------------------------------------------------- 413
class FileTooLarge(HireHQError):
    status_code = 413
    code = "FILE_TOO_LARGE"
    message = "The uploaded file exceeds the maximum allowed size"


class UnsupportedFileType(HireHQError):
    status_code = 415
    code = "UNSUPPORTED_FILE_TYPE"
    message = "This file type is not supported"


class MalwareDetected(HireHQError):
    status_code = 422
    code = "MALWARE_DETECTED"
    message = "The uploaded file failed the security scan and was rejected"


# ------------------------------------------------------------------------- 429
class RateLimitExceeded(HireHQError):
    status_code = 429
    code = "RATE_LIMIT_EXCEEDED"
    message = "Too many requests, please slow down"

    def __init__(self, retry_after: int = 60) -> None:
        super().__init__(details={"retry_after_seconds": retry_after})
        self.retry_after = retry_after


# ------------------------------------------------------------------------- 5xx
class ExternalServiceError(HireHQError):
    status_code = 502
    code = "EXTERNAL_SERVICE_ERROR"
    message = "An external service failed to respond correctly"


class ProviderNotConfigured(HireHQError):
    """Raised when an integration is invoked but no real provider has credentials.

    The API surfaces this honestly rather than pretending the action succeeded.
    """

    status_code = 503
    code = "PROVIDER_NOT_CONFIGURED"
    message = "This integration is not configured on the server"

    def __init__(self, provider: str, hint: str | None = None) -> None:
        super().__init__(
            f"The {provider} integration is not configured on this server",
            details={"provider": provider, "hint": hint} if hint else {"provider": provider},
        )
