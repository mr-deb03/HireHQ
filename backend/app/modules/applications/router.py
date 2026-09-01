"""Application pipeline endpoints: list, detail, status, Kanban and bulk actions."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import ApplicationSource, ApplicationStatus, EmailTemplateKey
from app.core.exceptions import ResourceNotFound, ValidationError
from app.core.permissions import Perm
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.interview import Interview, InterviewFeedback
from app.modules.applications.schemas import (
    ApplicationDetail,
    ApplicationSummary,
    BulkAssignRequest,
    BulkEmailRequest,
    BulkStatusRequest,
    BulkTagRequest,
    BulkTalentPoolRequest,
    KanbanBoard,
    KanbanCard,
    KanbanColumn,
    MoveCardRequest,
    StatusChangeRequest,
    TimelineEventOut,
)
from app.modules.applications.service import ApplicationPipelineService
from app.modules.applications.state_machine import (
    PIPELINE_ORDER,
    allowed_transitions,
)
from app.schemas.common import BulkResult, PaginationParams, pagination

router = APIRouter(prefix="/applications", tags=["Applications"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

ReadApplications = Depends(require_permission(Perm.APPLICATION_READ))
UpdateStatus = Depends(require_permission(Perm.APPLICATION_UPDATE_STATUS))
BulkAction = Depends(require_permission(Perm.APPLICATION_BULK_ACTION))


def _base_query(company_id: uuid.UUID):
    return (
        select(Application)
        .where(Application.company_id == company_id)
        .options(
            selectinload(Application.job),
            selectinload(Application.candidate).selectinload(Candidate.skills),
        )
    )


async def _load(session: AsyncSession, company_id: uuid.UUID, application_id: uuid.UUID) -> Application:
    application = (
        (
            await session.execute(
                _base_query(company_id)
                .where(Application.id == application_id)
                .options(selectinload(Application.screening_answers))
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if application is None:
        raise ResourceNotFound("Application", application_id)
    return application


@router.get(
    "",
    response_model=SuccessResponse[Page[ApplicationSummary]],
    summary="List and filter applications",
    dependencies=[ReadApplications],
)
async def list_applications(
    company_id: CompanyScope,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    job_id: uuid.UUID | None = None,
    application_status: Annotated[list[ApplicationStatus] | None, Query(alias="status")] = None,
    source: Annotated[list[ApplicationSource] | None, Query()] = None,
    min_ats_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_ats_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    assigned_recruiter_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(description="Candidate name, email or reference")] = None,
    sort: Annotated[str, Query(description="-ats_score, -created_at, ats_rank")] = "-created_at",
) -> SuccessResponse[Page[ApplicationSummary]]:
    stmt = _base_query(company_id)

    if job_id:
        stmt = stmt.where(Application.job_id == job_id)
    if application_status:
        stmt = stmt.where(Application.status.in_(application_status))
    if source:
        stmt = stmt.where(Application.source.in_(source))
    if min_ats_score is not None:
        stmt = stmt.where(Application.ats_score >= min_ats_score)
    if max_ats_score is not None:
        stmt = stmt.where(Application.ats_score <= max_ats_score)
    if assigned_recruiter_id:
        stmt = stmt.where(Application.assigned_recruiter_id == assigned_recruiter_id)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.join(Candidate, Candidate.id == Application.candidate_id).where(
            or_(
                Candidate.first_name.ilike(pattern),
                Candidate.last_name.ilike(pattern),
                Candidate.email.ilike(pattern),
                Application.reference_code.ilike(pattern),
            )
        )

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()

    stmt = stmt.order_by(*_sort(sort))
    rows = (
        (
            await session.execute(
                stmt.limit(page_params.page_size).offset(page_params.offset)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=Page.build(
            [ApplicationSummary.model_validate(a) for a in rows],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


def _sort(sort: str):
    descending = sort.startswith("-")
    field = sort.lstrip("-")
    column = {
        "created_at": Application.created_at,
        "ats_score": Application.ats_score,
        "ats_rank": Application.ats_rank,
        "status_changed_at": Application.status_changed_at,
        "screening_score": Application.screening_score,
    }.get(field, Application.created_at)
    return (
        (column.desc().nullslast(), Application.id)
        if descending
        else (column.asc().nullslast(), Application.id)
    )


@router.get(
    "/{application_id}",
    response_model=SuccessResponse[ApplicationDetail],
    summary="Get an application",
    dependencies=[ReadApplications],
)
async def get_application(
    application_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[ApplicationDetail]:
    application = await _load(session, company_id, application_id)
    payload = ApplicationDetail.model_validate(application)
    payload.allowed_transitions = [s.value for s in allowed_transitions(application.status)]
    return SuccessResponse(data=payload)


@router.get(
    "/{application_id}/timeline",
    response_model=SuccessResponse[list[TimelineEventOut]],
    summary="Get the application timeline",
    description="The immutable history of everything that happened to this application.",
    dependencies=[ReadApplications],
)
async def get_timeline(
    application_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[TimelineEventOut]]:
    await _load(session, company_id, application_id)
    service = ApplicationPipelineService(session, company_id)
    events = await service.get_timeline(application_id)
    return SuccessResponse(data=[TimelineEventOut.model_validate(e) for e in events])


@router.post(
    "/{application_id}/status",
    response_model=SuccessResponse[ApplicationDetail],
    summary="Change application status",
    description=(
        "Moves an application through the pipeline. Invalid transitions are rejected "
        "with the list of statuses that are reachable from the current one."
    ),
    dependencies=[UpdateStatus],
)
async def change_status(
    application_id: uuid.UUID,
    payload: StatusChangeRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[ApplicationDetail]:
    application = await _load(session, company_id, application_id)
    service = ApplicationPipelineService(session, company_id)
    await service.change_status(
        application,
        new_status=payload.status,
        actor_id=principal.id,
        reason=payload.reason,
        send_email=payload.send_email,
        custom_message=payload.custom_message,
    )
    await session.commit()
    await service.events.flush()

    application = await _load(session, company_id, application_id)
    result = ApplicationDetail.model_validate(application)
    result.allowed_transitions = [s.value for s in allowed_transitions(application.status)]
    return SuccessResponse(
        data=result, message=f"Moved to {payload.status.value.replace('_', ' ').title()}"
    )


# --------------------------------------------------------------------- Kanban
@router.get(
    "/board/kanban",
    response_model=SuccessResponse[KanbanBoard],
    summary="Kanban pipeline board",
    description=(
        "Applications grouped into pipeline columns. Pass `job_id` for one job's board, "
        "or omit it for the whole company."
    ),
    dependencies=[ReadApplications],
)
async def kanban_board(
    company_id: CompanyScope,
    session: DbSession,
    job_id: uuid.UUID | None = None,
    limit_per_column: Annotated[int, Query(ge=5, le=100)] = 50,
) -> SuccessResponse[KanbanBoard]:
    base = (
        select(Application)
        .where(Application.company_id == company_id)
        .options(selectinload(Application.candidate))
    )
    if job_id:
        base = base.where(Application.job_id == job_id)

    # Which applications are waiting on interview feedback - shown as a badge on the card.
    pending_feedback = set(
        (
            await session.execute(
                select(Interview.application_id)
                .outerjoin(
                    InterviewFeedback, InterviewFeedback.interview_id == Interview.id
                )
                .where(
                    Interview.company_id == company_id,
                    Interview.status == "COMPLETED",
                    InterviewFeedback.id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )

    columns: list[KanbanColumn] = []
    total = 0
    for pipeline_status in PIPELINE_ORDER:
        count = (
            await session.execute(
                select(func.count())
                .select_from(Application)
                .where(
                    Application.company_id == company_id,
                    Application.status == pipeline_status,
                    *([Application.job_id == job_id] if job_id else []),
                )
            )
        ).scalar_one()
        total += count

        rows = (
            (
                await session.execute(
                    base.where(Application.status == pipeline_status)
                    .order_by(
                        Application.stage_position.asc(),
                        Application.ats_score.desc().nullslast(),
                        Application.created_at.desc(),
                    )
                    .limit(limit_per_column)
                )
            )
            .unique()
            .scalars()
            .all()
        )

        columns.append(
            KanbanColumn(
                status=pipeline_status,
                label=pipeline_status.value.replace("_", " ").title(),
                count=count,
                cards=[
                    KanbanCard(
                        id=a.id,
                        reference_code=a.reference_code,
                        candidate_id=a.candidate_id,
                        candidate_name=a.candidate.full_name,
                        candidate_photo_url=a.candidate.photo_url,
                        current_designation=a.candidate.current_designation,
                        ats_score=float(a.ats_score) if a.ats_score is not None else None,
                        ats_rank=a.ats_rank,
                        total_experience_years=float(a.candidate.total_experience_years or 0),
                        notice_period_days=a.candidate.notice_period_days,
                        tags=a.tags,
                        stage_position=a.stage_position,
                        has_pending_feedback=a.id in pending_feedback,
                        applied_at=a.created_at,
                    )
                    for a in rows
                ],
            )
        )

    return SuccessResponse(data=KanbanBoard(job_id=job_id, columns=columns, total=total))


@router.post(
    "/{application_id}/move",
    response_model=SuccessResponse[ApplicationDetail],
    summary="Move a Kanban card",
    description="Changes status and ordering in one call, for drag-and-drop.",
    dependencies=[UpdateStatus],
)
async def move_card(
    application_id: uuid.UUID,
    payload: MoveCardRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[ApplicationDetail]:
    application = await _load(session, company_id, application_id)
    service = ApplicationPipelineService(session, company_id)

    if application.status != payload.status:
        await service.change_status(
            application,
            new_status=payload.status,
            actor_id=principal.id,
            send_email=payload.send_email,
        )
    application.stage_position = payload.position
    await session.commit()
    await service.events.flush()

    application = await _load(session, company_id, application_id)
    result = ApplicationDetail.model_validate(application)
    result.allowed_transitions = [s.value for s in allowed_transitions(application.status)]
    return SuccessResponse(data=result, message="Card moved")


# ----------------------------------------------------------------- bulk actions
@router.post(
    "/bulk/status",
    response_model=SuccessResponse[BulkResult],
    summary="Bulk change status",
    description=(
        "Applies a status change to many applications. Reports each failure "
        "individually rather than failing the whole batch."
    ),
    dependencies=[BulkAction],
)
async def bulk_status(
    payload: BulkStatusRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[BulkResult]:
    service = ApplicationPipelineService(session, company_id)
    result = await service.bulk_change_status(
        payload.application_ids,
        new_status=payload.status,
        actor_id=principal.id,
        reason=payload.reason,
        send_email=payload.send_email,
    )
    await session.commit()
    await service.events.flush()
    return SuccessResponse(
        data=BulkResult(**result),
        message=f"{len(result['succeeded'])} of {result['requested']} updated",
    )


@router.post(
    "/bulk/assign",
    response_model=SuccessResponse[BulkResult],
    summary="Bulk assign a recruiter",
    dependencies=[BulkAction],
)
async def bulk_assign(
    payload: BulkAssignRequest, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[BulkResult]:
    from app.models.user import User

    recruiter = await session.get(User, payload.recruiter_id)
    if recruiter is None or recruiter.company_id != company_id:
        raise ResourceNotFound("Recruiter", payload.recruiter_id)

    rows = (
        (
            await session.execute(
                select(Application).where(
                    Application.id.in_(payload.application_ids),
                    Application.company_id == company_id,
                )
            )
        )
        .scalars()
        .all()
    )
    for application in rows:
        application.assigned_recruiter_id = payload.recruiter_id
    await session.flush()

    found = {str(a.id) for a in rows}
    return SuccessResponse(
        data=BulkResult(
            requested=len(payload.application_ids),
            succeeded=sorted(found),
            failed=[
                {"id": str(i), "reason": "Not found"}
                for i in payload.application_ids
                if str(i) not in found
            ],
        ),
        message=f"Assigned {len(found)} application(s) to {recruiter.full_name}",
    )


@router.post(
    "/bulk/tags",
    response_model=SuccessResponse[BulkResult],
    summary="Bulk add, remove or replace tags",
    dependencies=[BulkAction],
)
async def bulk_tags(
    payload: BulkTagRequest, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[BulkResult]:
    rows = (
        (
            await session.execute(
                select(Application).where(
                    Application.id.in_(payload.application_ids),
                    Application.company_id == company_id,
                )
            )
        )
        .scalars()
        .all()
    )
    tags = [t.strip()[:50] for t in payload.tags if t.strip()]
    for application in rows:
        current = list(application.tags or [])
        if payload.mode == "add":
            application.tags = list(dict.fromkeys([*current, *tags]))
        elif payload.mode == "remove":
            application.tags = [t for t in current if t not in tags]
        else:
            application.tags = tags
    await session.flush()

    found = {str(a.id) for a in rows}
    return SuccessResponse(
        data=BulkResult(
            requested=len(payload.application_ids),
            succeeded=sorted(found),
            failed=[
                {"id": str(i), "reason": "Not found"}
                for i in payload.application_ids
                if str(i) not in found
            ],
        ),
        message=f"Tags updated on {len(found)} application(s)",
    )


@router.post(
    "/bulk/email",
    response_model=SuccessResponse[BulkResult],
    summary="Bulk email candidates",
    description=(
        "Sends one templated email per application. Each result reports its true "
        "delivery outcome - messages are not claimed as sent when no provider is "
        "configured."
    ),
    dependencies=[Depends(require_permission(Perm.EMAIL_SEND))],
)
async def bulk_email(
    payload: BulkEmailRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[BulkResult]:
    from app.models.company import Company
    from app.modules.emails.service import EmailService

    try:
        template_key = EmailTemplateKey(payload.template_key)
    except ValueError as exc:
        raise ValidationError(f"Unknown email template '{payload.template_key}'") from exc

    rows = (
        (
            await session.execute(
                _base_query(company_id).where(
                    Application.id.in_(payload.application_ids)
                )
            )
        )
        .unique()
        .scalars()
        .all()
    )
    company = await session.get(Company, company_id)
    service = EmailService(session, company_id)

    succeeded: list[str] = []
    failed: list[dict] = []
    for application in rows:
        variables = EmailService.build_variables(
            candidate=application.candidate,
            job=application.job,
            application=application,
            company=company,
            recruiter=principal.user,
            extra={"custom_message": payload.custom_message or ""},
        )
        message = await service.send_templated(
            key=template_key,
            to=[application.candidate.email],
            variables=variables,
            application_id=application.id,
            candidate_id=application.candidate_id,
            job_id=application.job_id,
            sent_by_id=principal.id,
        )
        if message.delivery_status.value == "SENT":
            succeeded.append(str(application.id))
        else:
            failed.append(
                {
                    "id": str(application.id),
                    "reason": message.failure_reason or message.delivery_status.value,
                }
            )

    delivered = len(succeeded)
    note = (
        f"{delivered} email(s) delivered"
        if delivered
        else "No emails were transmitted - check the email provider configuration"
    )
    return SuccessResponse(
        data=BulkResult(requested=len(payload.application_ids), succeeded=succeeded, failed=failed),
        message=note,
    )


@router.post(
    "/bulk/talent-pool",
    response_model=SuccessResponse[BulkResult],
    summary="Bulk add candidates to a talent pool",
    dependencies=[Depends(require_permission(Perm.TALENT_POOL_MANAGE))],
)
async def bulk_talent_pool(
    payload: BulkTalentPoolRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[BulkResult]:
    from app.modules.talent_pool.service import TalentPoolService

    service = TalentPoolService(session, company_id)
    pool = await service.get_or_create(pool_id=payload.pool_id, name=payload.pool_name or "")

    rows = (
        (
            await session.execute(
                select(Application).where(
                    Application.id.in_(payload.application_ids),
                    Application.company_id == company_id,
                )
            )
        )
        .scalars()
        .all()
    )
    succeeded: list[str] = []
    for application in rows:
        await service.add_candidate(
            pool, application.candidate_id, added_by_id=principal.id
        )
        succeeded.append(str(application.id))
    await session.flush()

    return SuccessResponse(
        data=BulkResult(
            requested=len(payload.application_ids),
            succeeded=succeeded,
            failed=[
                {"id": str(i), "reason": "Not found"}
                for i in payload.application_ids
                if str(i) not in set(succeeded)
            ],
        ),
        message=f"Added {len(succeeded)} candidate(s) to '{pool.name}'",
    )
