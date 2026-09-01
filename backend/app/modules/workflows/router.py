"""Workflow automation endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import (
    WorkflowActionType,
    WorkflowExecutionStatus,
    WorkflowTrigger,
)
from app.core.exceptions import ResourceNotFound, ValidationError
from app.core.permissions import Perm
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.workflow import Workflow, WorkflowExecution, WorkflowStep
from app.modules.workflows.conditions import (
    ConditionError,
    describe_field_registry,
    validate_conditions,
)
from app.modules.workflows.engine import (
    HUMAN_ONLY_STATUSES,
    WorkflowEngine,
    WorkflowValidationError,
    validate_steps,
)
from app.schemas.common import DeleteResponse, ORMModel, PaginationParams, pagination

router = APIRouter(prefix="/workflows", tags=["Workflows"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

ManageWorkflows = Depends(require_permission(Perm.WORKFLOW_MANAGE))
ReadWorkflows = Depends(require_permission(Perm.WORKFLOW_READ, Perm.WORKFLOW_MANAGE))


class StepInput(BaseModel):
    action_type: WorkflowActionType
    config: dict = Field(default_factory=dict)
    conditions: dict = Field(default_factory=dict)
    delay_minutes: int = Field(default=0, ge=0, le=60 * 24 * 30)
    continue_on_error: bool = True
    is_enabled: bool = True


class StepOut(ORMModel):
    id: uuid.UUID
    step_order: int
    action_type: WorkflowActionType
    config: dict = Field(default_factory=dict)
    conditions: dict = Field(default_factory=dict)
    delay_minutes: int
    continue_on_error: bool
    is_enabled: bool


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    trigger: WorkflowTrigger
    conditions: dict = Field(default_factory=dict)
    steps: list[StepInput] = Field(min_length=1, max_length=20)
    job_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    is_enabled: bool = True
    requires_human_approval: bool = Field(
        default=False,
        description=(
            "Hold the workflow's actions until a person approves. Required for any "
            "workflow that moves an application to REJECTED, HIRED or OFFER."
        ),
    )
    priority: int = Field(default=100, ge=1, le=1000)


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    conditions: dict | None = None
    steps: list[StepInput] | None = None
    job_ids: list[uuid.UUID] | None = None
    is_enabled: bool | None = None
    requires_human_approval: bool | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)


class WorkflowOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    trigger: WorkflowTrigger
    conditions: dict = Field(default_factory=dict)
    job_ids: list = Field(default_factory=list)
    is_enabled: bool
    requires_human_approval: bool
    priority: int
    execution_count: int
    last_executed_at: datetime | None = None
    steps: list[StepOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ExecutionOut(ORMModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str | None = None
    entity_type: str
    entity_id: uuid.UUID
    status: WorkflowExecutionStatus
    #: Populated when a run was skipped, explaining exactly which condition failed.
    skip_reason: str | None = None
    trigger_context: dict = Field(default_factory=dict)
    step_results: list = Field(default_factory=list)
    awaiting_approval: bool
    approved_by_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    created_at: datetime


def _validate(payload_conditions: dict | None, steps: list[StepInput], approval: bool) -> None:
    try:
        validate_conditions(payload_conditions)
    except ConditionError as exc:
        raise ValidationError(str(exc), code="INVALID_CONDITIONS") from exc
    try:
        validate_steps([s.model_dump() for s in steps], requires_human_approval=approval)
    except WorkflowValidationError as exc:
        raise ValidationError(str(exc), code="INVALID_WORKFLOW_STEPS") from exc


@router.get(
    "/schema",
    response_model=SuccessResponse[dict],
    summary="Workflow builder metadata",
    description=(
        "The fields, operators, triggers and actions the workflow builder may use. "
        "Conditions can only reference fields listed here."
    ),
    dependencies=[ReadWorkflows],
)
async def workflow_schema() -> SuccessResponse[dict]:
    return SuccessResponse(
        data={
            "triggers": [
                {"value": t.value, "label": t.value.replace("_", " ").title()}
                for t in WorkflowTrigger
            ],
            "actions": [
                {"value": a.value, "label": a.value.replace("_", " ").title()}
                for a in WorkflowActionType
            ],
            "fields": describe_field_registry(),
            "group_operators": ["AND", "OR"],
            "governance": {
                "human_only_statuses": sorted(s.value for s in HUMAN_ONLY_STATUSES),
                "note": (
                    "A workflow may advance candidates automatically, but moving one to "
                    "REJECTED, HIRED or OFFER requires 'requires_human_approval' so a "
                    "person confirms the decision."
                ),
            },
        }
    )


@router.get(
    "",
    response_model=SuccessResponse[list[WorkflowOut]],
    summary="List workflows",
    dependencies=[ReadWorkflows],
)
async def list_workflows(
    company_id: CompanyScope,
    session: DbSession,
    trigger: WorkflowTrigger | None = None,
    enabled_only: bool = False,
) -> SuccessResponse[list[WorkflowOut]]:
    stmt = (
        select(Workflow)
        .where(Workflow.company_id == company_id)
        .options(selectinload(Workflow.steps))
        .order_by(Workflow.priority, Workflow.name)
    )
    if trigger:
        stmt = stmt.where(Workflow.trigger == trigger)
    if enabled_only:
        stmt = stmt.where(Workflow.is_enabled.is_(True))

    workflows = (await session.execute(stmt)).unique().scalars().all()
    return SuccessResponse(data=[WorkflowOut.model_validate(w) for w in workflows])


@router.post(
    "",
    response_model=SuccessResponse[WorkflowOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a workflow",
    dependencies=[ManageWorkflows],
)
async def create_workflow(
    payload: WorkflowCreate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[WorkflowOut]:
    _validate(payload.conditions, payload.steps, payload.requires_human_approval)

    workflow = Workflow(
        company_id=company_id,
        name=payload.name,
        description=payload.description,
        trigger=payload.trigger,
        conditions=payload.conditions,
        job_ids=[str(j) for j in payload.job_ids],
        is_enabled=payload.is_enabled,
        requires_human_approval=payload.requires_human_approval,
        priority=payload.priority,
        created_by_id=principal.id,
    )
    session.add(workflow)
    await session.flush()

    for index, step in enumerate(payload.steps):
        session.add(
            WorkflowStep(workflow_id=workflow.id, step_order=index, **step.model_dump())
        )
    await session.flush()
    await session.refresh(workflow, ["steps"])

    return SuccessResponse(
        data=WorkflowOut.model_validate(workflow), message="Workflow created"
    )


@router.get(
    "/{workflow_id}",
    response_model=SuccessResponse[WorkflowOut],
    summary="Get a workflow",
    dependencies=[ReadWorkflows],
)
async def get_workflow(
    workflow_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[WorkflowOut]:
    workflow = await _load(session, company_id, workflow_id)
    return SuccessResponse(data=WorkflowOut.model_validate(workflow))


async def _load(session: AsyncSession, company_id: uuid.UUID, workflow_id: uuid.UUID) -> Workflow:
    workflow = (
        (
            await session.execute(
                select(Workflow)
                .where(Workflow.id == workflow_id, Workflow.company_id == company_id)
                .options(selectinload(Workflow.steps))
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if workflow is None:
        raise ResourceNotFound("Workflow", workflow_id)
    return workflow


@router.patch(
    "/{workflow_id}",
    response_model=SuccessResponse[WorkflowOut],
    summary="Update a workflow",
    dependencies=[ManageWorkflows],
)
async def update_workflow(
    workflow_id: uuid.UUID,
    payload: WorkflowUpdate,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[WorkflowOut]:
    workflow = await _load(session, company_id, workflow_id)

    approval = (
        payload.requires_human_approval
        if payload.requires_human_approval is not None
        else workflow.requires_human_approval
    )
    steps = payload.steps
    if steps is not None or payload.conditions is not None:
        _validate(
            payload.conditions if payload.conditions is not None else workflow.conditions,
            steps
            or [
                StepInput(
                    action_type=s.action_type,
                    config=s.config,
                    conditions=s.conditions,
                    delay_minutes=s.delay_minutes,
                    continue_on_error=s.continue_on_error,
                    is_enabled=s.is_enabled,
                )
                for s in workflow.steps
            ],
            approval,
        )

    for field in (
        "name",
        "description",
        "conditions",
        "is_enabled",
        "requires_human_approval",
        "priority",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(workflow, field, value)
    if payload.job_ids is not None:
        workflow.job_ids = [str(j) for j in payload.job_ids]

    if steps is not None:
        workflow.steps.clear()
        await session.flush()
        for index, step in enumerate(steps):
            session.add(
                WorkflowStep(workflow_id=workflow.id, step_order=index, **step.model_dump())
            )
    await session.flush()

    workflow = await _load(session, company_id, workflow_id)
    return SuccessResponse(
        data=WorkflowOut.model_validate(workflow), message="Workflow updated"
    )


@router.post(
    "/{workflow_id}/toggle",
    response_model=SuccessResponse[WorkflowOut],
    summary="Enable or disable a workflow",
    dependencies=[ManageWorkflows],
)
async def toggle_workflow(
    workflow_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[WorkflowOut]:
    workflow = await _load(session, company_id, workflow_id)
    workflow.is_enabled = not workflow.is_enabled
    await session.flush()
    return SuccessResponse(
        data=WorkflowOut.model_validate(workflow),
        message=f"Workflow {'enabled' if workflow.is_enabled else 'disabled'}",
    )


@router.delete(
    "/{workflow_id}",
    response_model=SuccessResponse[DeleteResponse],
    summary="Delete a workflow",
    dependencies=[ManageWorkflows],
)
async def delete_workflow(
    workflow_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[DeleteResponse]:
    workflow = await _load(session, company_id, workflow_id)
    await session.delete(workflow)
    await session.flush()
    return SuccessResponse(
        data=DeleteResponse(id=workflow_id, message="Workflow deleted"),
        message="Workflow deleted",
    )


# ------------------------------------------------------------------ runs
@router.get(
    "/executions/list",
    response_model=SuccessResponse[Page[ExecutionOut]],
    summary="Workflow execution history",
    description=(
        "Every run, including skipped ones with the exact condition that failed. This is "
        "the audit trail for automation."
    ),
    dependencies=[ReadWorkflows],
)
async def list_executions(
    company_id: CompanyScope,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    workflow_id: uuid.UUID | None = None,
    execution_status: Annotated[
        WorkflowExecutionStatus | None, Query(alias="status")
    ] = None,
    awaiting_approval: bool | None = None,
) -> SuccessResponse[Page[ExecutionOut]]:
    stmt = select(WorkflowExecution).where(WorkflowExecution.company_id == company_id)
    if workflow_id:
        stmt = stmt.where(WorkflowExecution.workflow_id == workflow_id)
    if execution_status:
        stmt = stmt.where(WorkflowExecution.status == execution_status)
    if awaiting_approval is not None:
        stmt = stmt.where(WorkflowExecution.awaiting_approval.is_(awaiting_approval))

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(WorkflowExecution.created_at.desc())
                .limit(page_params.page_size)
                .offset(page_params.offset)
            )
        )
        .scalars()
        .all()
    )

    names = dict(
        (
            await session.execute(
                select(Workflow.id, Workflow.name).where(Workflow.company_id == company_id)
            )
        ).all()
    )
    items = []
    for execution in rows:
        payload = ExecutionOut.model_validate(execution)
        payload.workflow_name = names.get(execution.workflow_id)
        items.append(payload)

    return SuccessResponse(
        data=Page.build(
            items, page=page_params.page, page_size=page_params.page_size, total=total
        )
    )


@router.post(
    "/executions/{execution_id}/approve",
    response_model=SuccessResponse[ExecutionOut],
    summary="Approve a held workflow run",
    description=(
        "Applies the actions a workflow proposed. This is the human-in-the-loop gate for "
        "consequential automated decisions."
    ),
    dependencies=[ManageWorkflows],
)
async def approve_execution(
    execution_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[ExecutionOut]:
    execution = await session.scalar(
        select(WorkflowExecution).where(
            WorkflowExecution.id == execution_id,
            WorkflowExecution.company_id == company_id,
        )
    )
    if execution is None:
        raise ResourceNotFound("Workflow execution", execution_id)

    engine = WorkflowEngine(session, company_id)
    await engine.approve(execution, approved_by_id=principal.id)
    await session.commit()

    return SuccessResponse(
        data=ExecutionOut.model_validate(execution), message="Workflow actions applied"
    )


@router.post(
    "/executions/{execution_id}/reject",
    response_model=SuccessResponse[ExecutionOut],
    summary="Reject a held workflow run",
    description="Discards the proposed actions without applying them.",
    dependencies=[ManageWorkflows],
)
async def reject_execution(
    execution_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[ExecutionOut]:
    execution = await session.scalar(
        select(WorkflowExecution).where(
            WorkflowExecution.id == execution_id,
            WorkflowExecution.company_id == company_id,
        )
    )
    if execution is None:
        raise ResourceNotFound("Workflow execution", execution_id)
    if not execution.awaiting_approval:
        raise ValidationError("This run is not awaiting approval")

    execution.awaiting_approval = False
    execution.status = WorkflowExecutionStatus.SKIPPED
    execution.skip_reason = f"Rejected by a reviewer ({principal.full_name})"
    execution.approved_by_id = principal.id
    execution.approved_at = datetime.now(tz=execution.created_at.tzinfo)
    await session.flush()

    return SuccessResponse(
        data=ExecutionOut.model_validate(execution), message="Proposed actions discarded"
    )
