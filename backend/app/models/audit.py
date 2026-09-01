"""Audit log and the AI-assistance decision log.

Both tables are append-only from the application's point of view: no service exposes an
update or delete path, and the API layer has no route that mutates them. Tamper
resistance in production additionally relies on a database role for the app user that
holds INSERT/SELECT but not UPDATE/DELETE on these tables (see ``docs/security.md``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AuditAction
from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType


class AuditLog(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_company_created", "company_id", "created_at"),
        Index("ix_audit_logs_actor_created", "actor_id", "created_at"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_action", "action"),
    )

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    #: Denormalised so the log stays readable after a user is deleted.
    actor_email: Mapped[str | None] = mapped_column(String(320))
    actor_roles: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)

    action: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, native_enum=False, length=30), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    #: Short human sentence, e.g. "Shortlisted Rahul Sharma for Senior React Developer".
    summary: Mapped[str] = mapped_column(String(500), nullable=False)

    #: Field-level before/after. Values are filtered through the same redaction rules as
    #: logging, so passwords/tokens never land here.
    changes: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)

    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)


class AiDecisionLog(Base, UUIDMixin, TimestampMixin):
    """Every AI-assisted output that touched a hiring decision (AI governance, s63).

    Records what was asked, which engine answered, what it produced, and - crucially -
    whether a human accepted, edited or overrode it.
    """

    __tablename__ = "ai_decision_logs"
    __table_args__ = (
        Index("ix_ai_decision_logs_company_created", "company_id", "created_at"),
        Index("ix_ai_decision_logs_entity", "entity_type", "entity_id"),
    )

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    #: JD_ANALYSIS | RESUME_PARSE | ATS_SEMANTIC | CANDIDATE_SUMMARY |
    #: FEEDBACK_SUMMARY | ASSISTANT_QUERY | TALENT_MATCH
    feature: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID())

    #: ``heuristic-v1`` or ``anthropic:claude-opus-5`` - so an audit can tell which
    #: outputs came from a real model and which from the deterministic fallback.
    engine: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str | None] = mapped_column(String(60))
    #: Never the full prompt (it can contain resume text); a short structured digest.
    input_digest: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    output_summary: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    confidence: Mapped[float | None] = mapped_column()

    #: PENDING | ACCEPTED | EDITED | OVERRIDDEN | REJECTED
    human_review_status: Mapped[str] = mapped_column(
        String(20), default="PENDING", nullable=False, index=True
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    review_note: Mapped[str | None] = mapped_column(Text)

    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(500))
