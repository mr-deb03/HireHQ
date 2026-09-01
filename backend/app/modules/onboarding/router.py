"""Onboarding handoff: preboarding, document collection, verification and joining."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import AuditAction, OnboardingStatus
from app.core.exceptions import BusinessRuleError, ResourceNotFound
from app.core.permissions import Perm
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.offer import Onboarding, OnboardingTask
from app.schemas.common import ORMModel, PaginationParams, pagination
from app.services.audit import AuditService

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

ManageOnboarding = Depends(require_permission(Perm.ONBOARDING_MANAGE))

#: Allowed forward moves. Onboarding is a checklist, so it only advances (or cancels).
_TRANSITIONS: dict[OnboardingStatus, set[OnboardingStatus]] = {
    OnboardingStatus.PREBOARDING: {
        OnboardingStatus.DOCUMENT_COLLECTION,
        OnboardingStatus.CANCELLED,
    },
    OnboardingStatus.DOCUMENT_COLLECTION: {
        OnboardingStatus.VERIFICATION,
        OnboardingStatus.CANCELLED,
    },
    OnboardingStatus.VERIFICATION: {
        OnboardingStatus.READY_TO_JOIN,
        OnboardingStatus.DOCUMENT_COLLECTION,
        OnboardingStatus.CANCELLED,
    },
    OnboardingStatus.READY_TO_JOIN: {OnboardingStatus.JOINED, OnboardingStatus.CANCELLED},
    OnboardingStatus.JOINED: set(),
    OnboardingStatus.CANCELLED: set(),
}


class TaskOut(ORMModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    category: str
    owner_type: str
    assigned_to_id: uuid.UUID | None = None
    display_order: int
    is_required: bool
    due_date: date | None = None
    completed_at: datetime | None = None
    completed_by_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None


class OnboardingOut(ORMModel):
    id: uuid.UUID
    offer_id: uuid.UUID
    candidate_id: uuid.UUID
    application_id: uuid.UUID
    status: OnboardingStatus
    expected_joining_date: date | None = None
    actual_joining_date: date | None = None
    owner_id: uuid.UUID | None = None
    buddy_user_id: uuid.UUID | None = None
    employee_user_id: uuid.UUID | None = None
    notes: str | None = None
    completion_percentage: float
    tasks: list[TaskOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class StatusChangeRequest(BaseModel):
    status: OnboardingStatus
    actual_joining_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    category: str = Field(default="HR", max_length=30)
    owner_type: str = Field(default="CANDIDATE", pattern="^(CANDIDATE|COMPANY)$")
    assigned_to_id: uuid.UUID | None = None
    is_required: bool = True
    due_date: date | None = None


class TaskCompleteRequest(BaseModel):
    document_id: uuid.UUID | None = None


async def _load(session: AsyncSession, company_id: uuid.UUID, onboarding_id: uuid.UUID) -> Onboarding:
    record = (
        (
            await session.execute(
                select(Onboarding)
                .where(
                    Onboarding.id == onboarding_id, Onboarding.company_id == company_id
                )
                .options(selectinload(Onboarding.tasks))
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if record is None:
        raise ResourceNotFound("Onboarding record", onboarding_id)
    return record


@router.get(
    "",
    response_model=SuccessResponse[Page[OnboardingOut]],
    summary="List onboarding records",
    dependencies=[ManageOnboarding],
)
async def list_onboarding(
    company_id: CompanyScope,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    onboarding_status: Annotated[list[OnboardingStatus] | None, Query(alias="status")] = None,
    joining_before: date | None = None,
) -> SuccessResponse[Page[OnboardingOut]]:
    stmt = (
        select(Onboarding)
        .where(Onboarding.company_id == company_id)
        .options(selectinload(Onboarding.tasks))
    )
    if onboarding_status:
        stmt = stmt.where(Onboarding.status.in_(onboarding_status))
    if joining_before:
        stmt = stmt.where(Onboarding.expected_joining_date <= joining_before)

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(Onboarding.expected_joining_date.asc().nullslast())
                .limit(page_params.page_size)
                .offset(page_params.offset)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=Page.build(
            [OnboardingOut.model_validate(o) for o in rows],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


@router.get(
    "/{onboarding_id}",
    response_model=SuccessResponse[OnboardingOut],
    summary="Get an onboarding record",
    dependencies=[ManageOnboarding],
)
async def get_onboarding(
    onboarding_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[OnboardingOut]:
    record = await _load(session, company_id, onboarding_id)
    return SuccessResponse(data=OnboardingOut.model_validate(record))


@router.post(
    "/{onboarding_id}/status",
    response_model=SuccessResponse[OnboardingOut],
    summary="Advance onboarding status",
    description=(
        "Moving to JOINED requires every mandatory task to be complete - the checklist "
        "is the point, so the API will not let it be skipped silently."
    ),
    dependencies=[ManageOnboarding],
)
async def change_status(
    onboarding_id: uuid.UUID,
    payload: StatusChangeRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[OnboardingOut]:
    record = await _load(session, company_id, onboarding_id)
    previous = record.status

    if payload.status not in _TRANSITIONS.get(previous, set()):
        raise BusinessRuleError(
            f"Cannot move onboarding from {previous.value} to {payload.status.value}",
            details={
                "current_status": previous.value,
                "allowed": sorted(s.value for s in _TRANSITIONS.get(previous, set())),
            },
        )

    if payload.status == OnboardingStatus.JOINED:
        outstanding = [
            t.title for t in record.tasks if t.is_required and t.completed_at is None
        ]
        if outstanding:
            raise BusinessRuleError(
                "Some required onboarding tasks are still outstanding",
                code="ONBOARDING_TASKS_INCOMPLETE",
                details={"outstanding": outstanding},
            )
        record.actual_joining_date = payload.actual_joining_date or date.today()

    record.status = payload.status
    if payload.notes:
        record.notes = payload.notes
    await session.flush()

    await AuditService(session).record(
        action=AuditAction.STATUS_CHANGE,
        entity_type="Onboarding",
        entity_id=record.id,
        company_id=company_id,
        actor_id=principal.id,
        summary=f"Onboarding moved from {previous.value} to {payload.status.value}",
    )

    record = await _load(session, company_id, onboarding_id)
    return SuccessResponse(
        data=OnboardingOut.model_validate(record),
        message=f"Onboarding is now {payload.status.value.replace('_', ' ').lower()}",
    )


@router.post(
    "/{onboarding_id}/tasks",
    response_model=SuccessResponse[TaskOut],
    status_code=status.HTTP_201_CREATED,
    summary="Add an onboarding task",
    dependencies=[ManageOnboarding],
)
async def add_task(
    onboarding_id: uuid.UUID,
    payload: TaskCreate,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[TaskOut]:
    record = await _load(session, company_id, onboarding_id)
    task = OnboardingTask(
        onboarding_id=record.id,
        display_order=len(record.tasks),
        **payload.model_dump(),
    )
    session.add(task)
    await session.flush()
    return SuccessResponse(data=TaskOut.model_validate(task), message="Task added")


@router.post(
    "/tasks/{task_id}/complete",
    response_model=SuccessResponse[TaskOut],
    summary="Mark an onboarding task complete",
    dependencies=[ManageOnboarding],
)
async def complete_task(
    task_id: uuid.UUID,
    payload: TaskCompleteRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[TaskOut]:
    task = (
        (
            await session.execute(
                select(OnboardingTask)
                .join(Onboarding, Onboarding.id == OnboardingTask.onboarding_id)
                .where(
                    OnboardingTask.id == task_id, Onboarding.company_id == company_id
                )
            )
        )
        .scalar_one_or_none()
    )
    if task is None:
        raise ResourceNotFound("Onboarding task", task_id)

    task.completed_at = datetime.now(UTC)
    task.completed_by_id = principal.id
    if payload.document_id:
        task.document_id = payload.document_id
    await session.flush()

    return SuccessResponse(data=TaskOut.model_validate(task), message="Task completed")


@router.delete(
    "/tasks/{task_id}",
    response_model=SuccessResponse[dict],
    summary="Remove an onboarding task",
    dependencies=[ManageOnboarding],
)
async def delete_task(
    task_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[dict]:
    task = (
        (
            await session.execute(
                select(OnboardingTask)
                .join(Onboarding, Onboarding.id == OnboardingTask.onboarding_id)
                .where(
                    OnboardingTask.id == task_id, Onboarding.company_id == company_id
                )
            )
        )
        .scalar_one_or_none()
    )
    if task is None:
        raise ResourceNotFound("Onboarding task", task_id)
    await session.delete(task)
    await session.flush()
    return SuccessResponse(data={"id": str(task_id)}, message="Task removed")
