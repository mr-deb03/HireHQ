"""Structured logging with request-scoped context and secret redaction.

Request id / user id / company id are carried in ``contextvars`` so every log line
emitted anywhere during a request is automatically correlated, without threading a
logger through the call stack.
"""

from __future__ import annotations

import logging
import re
import sys
from contextvars import ContextVar
from typing import Any

import structlog

from app.core.config import settings

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)
company_id_ctx: ContextVar[str | None] = ContextVar("company_id", default=None)
job_id_ctx: ContextVar[str | None] = ContextVar("background_job_id", default=None)

#: Keys whose values are replaced wholesale before a log record is emitted.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "current_password",
        "new_password",
        "confirm_password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "ai_api_key",
        "secret",
        "jwt_secret",
        "client_secret",
        "smtp_password",
        "storage_secret_key",
        "resume_text",
        "raw_text",
        "cookie",
        "set-cookie",
    }
)

REDACTED = "[redacted]"

_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]*(@[A-Za-z0-9.\-]+)")


def _mask_email(match: re.Match[str]) -> str:
    return f"{match.group(1)}***{match.group(2)}"


def redact_processor(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Drop or mask anything that must never reach a log sink."""
    for key in list(event_dict.keys()):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = REDACTED
        elif isinstance(event_dict[key], str):
            value = _BEARER_RE.sub(rf"\1{REDACTED}", event_dict[key])
            event_dict[key] = value
    # Candidate email addresses are personal data; keep them diagnosable but not plain.
    if isinstance(event_dict.get("email"), str):
        event_dict["email"] = _EMAIL_RE.sub(_mask_email, event_dict["email"])
    return event_dict


def context_processor(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    if rid := request_id_ctx.get():
        event_dict.setdefault("request_id", rid)
    if uid := user_id_ctx.get():
        event_dict.setdefault("user_id", uid)
    if cid := company_id_ctx.get():
        event_dict.setdefault("company_id", cid)
    if jid := job_id_ctx.get():
        event_dict.setdefault("background_job_id", jid)
    return event_dict


def configure_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine", "aiosqlite"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))

    renderer = (
        structlog.processors.JSONRenderer()
        if settings.LOG_JSON
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            context_processor,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
