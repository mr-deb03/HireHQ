"""Workflow automation: definitions, steps and execution records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    WorkflowActionType,
    WorkflowExecutionStatus,
    WorkflowTrigger,
)
from app.db.base import Base, TenantMixin, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType, UTCDateTime


class Workflow(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """An automation: a trigger, optional conditions, and an ordered list of steps."""

    __tablename__ = "workflows"
    __table_args__ = (
        Index("ix_workflows_company_trigger_enabled", "company_id", "trigger", "is_enabled"),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    trigger: Mapped[WorkflowTrigger] = mapped_column(
        SAEnum(WorkflowTrigger, native_enum=False, length=40), nullable=False, index=True
    )
    #: Restrict to specific jobs; empty means every job in the company.
    job_ids: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)

    #: Root condition group evaluated before any step runs. Shape:
    #: ``{"op": "AND", "rules": [{"field": "ats_score", "operator": "gte", "value": 80}]}``
    #: Fields come from a fixed allow-list in ``app.modules.workflows.conditions`` -
    #: workflows can never read arbitrary attributes off a model.
    conditions: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    #: When true, the workflow only *proposes* its actions and records them for a human
    #: to approve. This is how "AI recommendation -> human review" (s19) is enforced for
    #: consequential actions.
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    execution_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )

    steps: Mapped[list[WorkflowStep]] = relationship(
        back_populates="workflow",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="WorkflowStep.step_order",
    )


class WorkflowStep(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "workflow_steps"
    __table_args__ = (Index("ix_workflow_steps_workflow_order", "workflow_id", "step_order"),)

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    action_type: Mapped[WorkflowActionType] = mapped_column(
        SAEnum(WorkflowActionType, native_enum=False, length=40), nullable=False
    )
    #: Action parameters, validated per action type by the executor's registry, e.g.
    #: ``{"status": "SHORTLISTED"}`` or ``{"template_key": "SHORTLISTED"}``.
    config: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    #: Optional per-step gate, same grammar as ``Workflow.conditions``.
    conditions: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    #: For DELAY steps.
    delay_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: When false, a failing step aborts the run; when true the run continues.
    continue_on_error: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    workflow: Mapped[Workflow] = relationship(back_populates="steps", lazy="noload")


class WorkflowExecution(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """One run of one workflow against one entity. The audit trail for automation."""

    __tablename__ = "workflow_executions"
    __table_args__ = (
        Index("ix_workflow_executions_workflow_created", "workflow_id", "created_at"),
        Index("ix_workflow_executions_entity", "entity_type", "entity_id"),
        # A given workflow runs at most once per (entity, trigger occurrence). The
        # idempotency key makes retries and duplicate events safe.
        Index("ix_workflow_executions_idempotency", "idempotency_key", unique=True),
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)

    status: Mapped[WorkflowExecutionStatus] = mapped_column(
        SAEnum(WorkflowExecutionStatus, native_enum=False, length=20),
        default=WorkflowExecutionStatus.PENDING,
        nullable=False,
        index=True,
    )
    #: Why a run was skipped, e.g. "conditions not met: ats_score 62 < 80". Surfaced in
    #: the UI so recruiters can see exactly why automation did or did not fire.
    skip_reason: Mapped[str | None] = mapped_column(String(500))
    trigger_context: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    #: Per-step outcome: ``[{"step": 0, "action": "...", "status": "...", "detail": "..."}]``
    step_results: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error: Mapped[str | None] = mapped_column(Text)

    #: Set when ``requires_human_approval`` is on and the run is waiting for a decision.
    awaiting_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    workflow: Mapped[Workflow] = relationship(lazy="noload")
