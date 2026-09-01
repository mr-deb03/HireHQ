"""Exception handlers producing the standard error envelope.

Every path out of the API - domain error, validation failure, HTTP exception, database
error or an unexpected crash - lands in one of these, so clients only ever parse one
shape. Unexpected errors log the traceback server-side and return an opaque message
rather than leaking internals.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.exceptions import HireHQError, RateLimitExceeded
from app.core.logging import get_logger, request_id_ctx
from app.core.responses import error

logger = get_logger("errors")

#: Starlette status code -> stable machine code, so clients never switch on prose.
_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "AUTHENTICATION_FAILED",
    403: "PERMISSION_DENIED",
    404: "RESOURCE_NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMIT_EXCEEDED",
    500: "INTERNAL_SERVER_ERROR",
    502: "EXTERNAL_SERVICE_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def _envelope(
    status_code: int, code: str, message: str, details: dict | None = None, headers: dict | None = None
) -> JSONResponse:
    payload = error(code, message, details)
    payload["request_id"] = request_id_ctx.get()
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HireHQError)
    async def handle_domain_error(_request: Request, exc: HireHQError) -> JSONResponse:
        headers = None
        if isinstance(exc, RateLimitExceeded):
            headers = {"Retry-After": str(exc.retry_after)}
        # 5xx domain errors are real incidents; 4xx are ordinary client outcomes.
        log = logger.warning if exc.status_code < 500 else logger.error
        log("domain_error", code=exc.code, status_code=exc.status_code, detail=exc.message)
        return _envelope(exc.status_code, exc.code, exc.message, exc.details or None, headers)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = []
        for err in exc.errors():
            location = [str(p) for p in err["loc"] if p not in ("body", "query", "path")]
            fields.append(
                {
                    "field": ".".join(location) or err["loc"][-1],
                    "message": err["msg"],
                    "type": err["type"],
                }
            )
        return _envelope(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_ERROR",
            "The submitted data is invalid",
            {"fields": fields},
        )

    @app.exception_handler(PydanticValidationError)
    async def handle_pydantic_validation(
        _request: Request, exc: PydanticValidationError
    ) -> JSONResponse:
        # A response model failing validation is our bug, not the caller's.
        logger.error("response_validation_failed", errors=exc.error_count())
        return _envelope(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_SERVER_ERROR",
            "The server produced an invalid response",
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return _envelope(
            exc.status_code, code, detail, headers=getattr(exc, "headers", None)
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
        # The DB constraint name is useful to us but must not be echoed to a client.
        logger.warning("integrity_error", detail=str(exc.orig)[:300])
        return _envelope(
            status.HTTP_409_CONFLICT,
            "DUPLICATE_RESOURCE",
            "This operation conflicts with existing data",
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_db_error(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("database_error", error=str(exc)[:500], exc_info=True)
        return _envelope(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "DATABASE_UNAVAILABLE",
            "The database is temporarily unavailable, please retry",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", error=str(exc), exc_info=True)
        message = "An unexpected error occurred"
        details = None
        if settings.DEBUG:
            details = {"exception": type(exc).__name__, "detail": str(exc)[:500]}
        return _envelope(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_SERVER_ERROR", message, details
        )
