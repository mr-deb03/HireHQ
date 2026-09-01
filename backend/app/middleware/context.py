"""Request-context, security-header and rate-limiting middleware."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.logging import (
    company_id_ctx,
    get_logger,
    request_id_ctx,
    user_id_ctx,
)
from app.core.responses import error

logger = get_logger("http")

RequestHandler = Callable[[Request], Awaitable[Response]]


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id, bind logging context and emit one structured access log."""

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        user_token = user_id_ctx.set(None)
        company_token = company_id_ctx.set(None)
        request.state.request_id = request_id

        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            # Health checks would otherwise dominate the log at 1/second.
            if request.url.path not in ("/health", "/health/live", "/metrics"):
                logger.info(
                    "request",
                    method=request.method,
                    path=request.url.path,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    client=request.client.host if request.client else None,
                )
            request_id_ctx.reset(token)
            user_id_ctx.reset(user_token)
            company_id_ctx.reset(company_token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Standard hardening headers.

    The CSP is strict because this API serves JSON plus the Swagger UI; the frontend is a
    separate origin with its own policy.
    """

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=(), payment=()"
        )
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        # Never let a signed file URL or a candidate's data sit in a shared cache.
        if request.url.path.startswith(settings.API_V1_PREFIX):
            headers.setdefault("Cache-Control", "no-store, private")

        if settings.APP_ENV in ("staging", "production"):
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        # The docs pages need to load Swagger's bundled assets from the CDN.
        if request.url.path in ("/docs", "/redoc"):
            headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
                "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                "worker-src 'self' blob:",
            )
        else:
            headers.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter.

    In-process by design: it is a safety net for a single instance, not a distributed
    quota system. With ``USE_REDIS_CACHE`` enabled a Redis-backed limiter should front
    it at the ingress; this one still protects each worker from a single hot client.
    """

    #: Path prefix -> requests per minute. Longest prefix wins.
    def __init__(self, app, **kwargs) -> None:
        super().__init__(app, **kwargs)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._last_sweep = time.monotonic()
        prefix = settings.API_V1_PREFIX
        self._limits: list[tuple[str, int]] = [
            (f"{prefix}/auth/login", settings.RATE_LIMIT_AUTH_PER_MINUTE),
            (f"{prefix}/auth/register", settings.RATE_LIMIT_AUTH_PER_MINUTE),
            (f"{prefix}/auth/forgot-password", settings.RATE_LIMIT_AUTH_PER_MINUTE),
            (f"{prefix}/auth/reset-password", settings.RATE_LIMIT_AUTH_PER_MINUTE),
            (f"{prefix}/public", settings.RATE_LIMIT_PUBLIC_PER_MINUTE),
            (prefix, settings.RATE_LIMIT_DEFAULT_PER_MINUTE),
        ]

    def _limit_for(self, path: str) -> tuple[str, int] | None:
        for prefix, limit in self._limits:
            if path.startswith(prefix):
                return prefix, limit
        return None

    @staticmethod
    def _client_key(request: Request) -> str:
        # Prefer the authenticated subject so one office NAT is not one bucket. Falls
        # back to the peer address; X-Forwarded-For is only trusted behind a proxy that
        # is configured to set it (uvicorn --proxy-headers).
        if principal := getattr(request.state, "principal", None):
            return f"user:{principal.id}"
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        return f"ip:{request.client.host if request.client else 'unknown'}"

    def _sweep(self, now: float) -> None:
        """Drop empty buckets so the dict cannot grow without bound."""
        if now - self._last_sweep < 60:
            return
        self._last_sweep = now
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > 120]:
            self._hits.pop(key, None)

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        if not settings.RATE_LIMIT_ENABLED or request.method == "OPTIONS":
            return await call_next(request)

        matched = self._limit_for(request.url.path)
        if matched is None:
            return await call_next(request)
        prefix, limit = matched

        now = time.monotonic()
        self._sweep(now)
        key = f"{self._client_key(request)}|{prefix}"
        bucket = self._hits[key]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()

        if len(bucket) >= limit:
            retry_after = max(1, int(60 - (now - bucket[0])))
            logger.warning("rate_limited", path=request.url.path, limit=limit)
            return JSONResponse(
                status_code=429,
                content=error(
                    "RATE_LIMIT_EXCEEDED",
                    "Too many requests, please slow down",
                    {"retry_after_seconds": retry_after},
                ),
                headers={"Retry-After": str(retry_after), "X-RateLimit-Limit": str(limit)},
            )

        bucket.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - len(bucket)))
        return response
