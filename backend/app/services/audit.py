"""Audit logging service.

Insert-only. Values are redacted with the same rules as the logging pipeline so
passwords and tokens can never be captured in a change record.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AuditAction
from app.core.logging import SENSITIVE_KEYS, request_id_ctx
from app.models.audit import AiDecisionLog, AuditLog
from app.utils.text import truncate

REDACTED = "[redacted]"
#: Fields that are noise in an audit diff.
_IGNORED_FIELDS = frozenset({"updated_at", "created_at", "stage_position"})


def _sanitise(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (REDACTED if k.lower() in SENSITIVE_KEYS else _sanitise(v)) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitise(v) for v in value][:50]
    if isinstance(value, uuid.UUID):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return truncate(value, 500) if isinstance(value, str) else value
    return truncate(str(value), 500)


def diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    """Field-level change record, keeping only fields that actually moved."""
    before, after = before or {}, after or {}
    changes: dict[str, Any] = {}
    for key in set(before) | set(after):
        if key in _IGNORED_FIELDS or key.lower() in SENSITIVE_KEYS:
            continue
        old, new = before.get(key), after.get(key)
        if old != new:
            changes[key] = {"from": _sanitise(old), "to": _sanitise(new)}
    return changes


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        action: AuditAction,
        entity_type: str,
        summary: str,
        entity_id: uuid.UUID | None = None,
        company_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        actor_email: str | None = None,
        actor_roles: list[str] | None = None,
        changes: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=truncate(summary, 500),
            company_id=company_id,
            actor_id=actor_id,
            actor_email=actor_email,
            actor_roles=actor_roles or [],
            changes=_sanitise(changes or {}),
            meta=_sanitise(meta or {}),
            ip_address=ip_address,
            user_agent=truncate(user_agent, 512) if user_agent else None,
            request_id=request_id_ctx.get(),
        )
        self.session.add(entry)
        return entry

    async def record_for(
        self,
        principal: Any,
        *,
        action: AuditAction,
        entity_type: str,
        summary: str,
        entity_id: uuid.UUID | None = None,
        changes: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        """Convenience overload that pulls actor details off an authenticated principal."""
        return await self.record(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
            company_id=getattr(principal, "company_id", None),
            actor_id=getattr(principal, "id", None),
            actor_email=getattr(principal, "email", None),
            actor_roles=sorted(getattr(principal, "roles", []) or []),
            changes=changes,
            meta=meta,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def record_ai(
        self,
        *,
        feature: str,
        engine: str,
        company_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        model: str | None = None,
        input_digest: dict | None = None,
        output_summary: dict | None = None,
        confidence: float | None = None,
        latency_ms: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error: str | None = None,
    ) -> AiDecisionLog:
        """Log an AI-assisted output.

        ``input_digest`` must be a short structured summary - never a full prompt, which
        would put resume text into the audit trail.
        """
        entry = AiDecisionLog(
            feature=feature,
            engine=engine,
            model=model,
            company_id=company_id,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            input_digest=_sanitise(input_digest or {}),
            output_summary=_sanitise(output_summary or {}),
            confidence=confidence,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error=truncate(error, 500) if error else None,
        )
        self.session.add(entry)
        return entry
