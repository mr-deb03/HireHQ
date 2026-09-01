"""Interview scheduling and feedback endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import InterviewStatus
from app.core.exceptions import ResourceNotFound
from app.core.permissions import Perm
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.calendar import CalendarEvent
from app.models.interview import Interview, InterviewFeedback
from app.modules.interviews.schemas import (
    CalendarSyncOut,
    ConflictCheckRequest,
    ConflictCheckResponse,
    ConflictOut,
    FeedbackCreate,
    FeedbackOut,
    FeedbackSummaryResponse,
    InterviewCancel,
    InterviewCreate,
    InterviewDetail,
    InterviewReschedule,
    InterviewSummary,
)
from app.modules.interviews.service import InterviewService
from app.schemas.common import PaginationParams, pagination

router = APIRouter(prefix="/interviews", tags=["Interviews"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _to_summary(interview: Interview) -> InterviewSummary:
    payload = InterviewSummary.model_validate(interview)
    if interview.application is not None:
        payload.candidate_name = interview.application.candidate.full_name
        payload.job_title = interview.application.job.title
    payload.feedback_count = len([f for f in interview.feedback if not f.is_draft])
    return payload


async def _to_detail(
    session: AsyncSession, interview: Interview, principal
) -> InterviewDetail:
    payload = InterviewDetail.model_validate(interview)
    if interview.application is not None:
        payload.candidate_name = interview.application.candidate.full_name
        payload.job_title = interview.application.job.title
    payload.feedback_count = len([f for f in interview.feedback if not f.is_draft])

    # Internal notes are for staff who can manage interviews, not every participant.
    if not principal.has(Perm.INTERVIEW_UPDATE):
        payload.internal_notes = None

    if interview.calendar_event_id:
        event = await session.get(CalendarEvent, interview.calendar_event_id)
        if event is not None:
            payload.calendar_sync = CalendarSyncOut(
                status=event.sync_status,
                provider=event.provider.value if event.provider else None,
                external_event_id=event.external_event_id,
                detail=(
                    event.sync_error
                    or (
                        "No external calendar is connected, so no invitation was sent "
                        "to anyone's calendar. Candidates and interviewers were emailed "
                        "by HireHQ."
                        if event.sync_status == "PENDING_NO_PROVIDER"
                        else None
                    )
                ),
            )
    return payload


@router.get(
    "",
    response_model=SuccessResponse[Page[InterviewSummary]],
    summary="List interviews",
    description=(
        "Interviewers see only the interviews they are participating in; recruiters see "
        "everything in their company."
    ),
    dependencies=[
        Depends(require_permission(Perm.INTERVIEW_READ, Perm.INTERVIEW_READ_ASSIGNED))
    ],
)
async def list_interviews(
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    job_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    interview_status: Annotated[list[InterviewStatus] | None, Query(alias="status")] = None,
    start_after: datetime | None = None,
    start_before: datetime | None = None,
    upcoming: Annotated[bool, Query(description="Only future, non-cancelled interviews")] = False,
) -> SuccessResponse[Page[InterviewSummary]]:
    service = InterviewService(session, company_id)

    assigned_only = not principal.has(Perm.INTERVIEW_READ)
    if upcoming:
        start_after = start_after or datetime.now(UTC)
        interview_status = interview_status or [
            InterviewStatus.SCHEDULED,
            InterviewStatus.CONFIRMED,
            InterviewStatus.RESCHEDULED,
        ]

    interviews, total = await service.list(
        job_id=job_id,
        candidate_id=candidate_id,
        application_id=application_id,
        interviewer_id=principal.id if assigned_only else None,
        statuses=interview_status,
        start_after=start_after,
        start_before=start_before,
        page=page_params.page,
        page_size=page_params.page_size,
    )
    return SuccessResponse(
        data=Page.build(
            [_to_summary(i) for i in interviews],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


@router.post(
    "",
    response_model=SuccessResponse[InterviewDetail],
    status_code=status.HTTP_201_CREATED,
    summary="Schedule an interview",
    description=(
        "Checks interviewer availability, creates the interview and its calendar event, "
        "moves the application to INTERVIEW and emails the candidate. The response "
        "reports whether an external calendar invitation was actually created."
    ),
    dependencies=[Depends(require_permission(Perm.INTERVIEW_CREATE))],
)
async def schedule_interview(
    payload: InterviewCreate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[InterviewDetail]:
    service = InterviewService(session, company_id)
    interview = await service.schedule(
        organiser_id=principal.id, **payload.model_dump()
    )
    await session.commit()
    await service.events.flush()

    interview = await service.get(interview.id)
    detail = await _to_detail(session, interview, principal)

    message = "Interview scheduled"
    if detail.calendar_sync and detail.calendar_sync.status == "PENDING_NO_PROVIDER":
        message = (
            "Interview scheduled. No calendar provider is connected, so no external "
            "calendar invitation was created - the candidate was emailed by HireHQ."
        )
    return SuccessResponse(data=detail, message=message)


@router.post(
    "/check-conflicts",
    response_model=SuccessResponse[ConflictCheckResponse],
    summary="Check interviewer availability",
    description="Call before scheduling to show conflicts in the UI instead of an error.",
    dependencies=[Depends(require_permission(Perm.INTERVIEW_CREATE))],
)
async def check_conflicts(
    payload: ConflictCheckRequest, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[ConflictCheckResponse]:
    service = InterviewService(session, company_id)
    end = payload.scheduled_start + timedelta(minutes=payload.duration_minutes)
    conflicts = await service.find_conflicts(
        payload.interviewer_ids,
        payload.scheduled_start,
        end,
        exclude_interview_id=payload.exclude_interview_id,
    )
    return SuccessResponse(
        data=ConflictCheckResponse(
            has_conflicts=bool(conflicts),
            conflicts=[ConflictOut(**c) for c in conflicts],
        )
    )


@router.get(
    "/pending-feedback",
    response_model=SuccessResponse[list[InterviewSummary]],
    summary="Interviews awaiting feedback",
    dependencies=[
        Depends(require_permission(Perm.FEEDBACK_READ, Perm.FEEDBACK_SUBMIT))
    ],
)
async def pending_feedback(
    principal: CurrentUser, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[InterviewSummary]]:
    service = InterviewService(session, company_id)
    mine_only = not principal.has(Perm.FEEDBACK_READ)
    interviews = await service.pending_feedback(
        interviewer_id=principal.id if mine_only else None
    )
    return SuccessResponse(data=[_to_summary(i) for i in interviews])


@router.get(
    "/{interview_id}",
    response_model=SuccessResponse[InterviewDetail],
    summary="Get an interview",
    dependencies=[
        Depends(require_permission(Perm.INTERVIEW_READ, Perm.INTERVIEW_READ_ASSIGNED))
    ],
)
async def get_interview(
    interview_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[InterviewDetail]:
    service = InterviewService(session, company_id)
    interview = await service.get(interview_id)
    if not await service.can_view(interview, principal):
        raise ResourceNotFound("Interview", interview_id)
    return SuccessResponse(data=await _to_detail(session, interview, principal))


@router.post(
    "/{interview_id}/reschedule",
    response_model=SuccessResponse[InterviewDetail],
    summary="Reschedule an interview",
    dependencies=[Depends(require_permission(Perm.INTERVIEW_UPDATE))],
)
async def reschedule_interview(
    interview_id: uuid.UUID,
    payload: InterviewReschedule,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[InterviewDetail]:
    service = InterviewService(session, company_id)
    interview = await service.get(interview_id)
    await service.reschedule(
        interview,
        scheduled_start=payload.scheduled_start,
        duration_minutes=payload.duration_minutes,
        actor_id=principal.id,
        reason=payload.reason,
        notify=payload.notify,
    )
    await session.commit()
    await service.events.flush()

    interview = await service.get(interview_id)
    return SuccessResponse(
        data=await _to_detail(session, interview, principal), message="Interview rescheduled"
    )


@router.post(
    "/{interview_id}/cancel",
    response_model=SuccessResponse[InterviewDetail],
    summary="Cancel an interview",
    dependencies=[Depends(require_permission(Perm.INTERVIEW_CANCEL))],
)
async def cancel_interview(
    interview_id: uuid.UUID,
    payload: InterviewCancel,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[InterviewDetail]:
    service = InterviewService(session, company_id)
    interview = await service.get(interview_id)
    await service.cancel(interview, actor_id=principal.id, reason=payload.reason)
    await session.commit()

    interview = await service.get(interview_id)
    return SuccessResponse(
        data=await _to_detail(session, interview, principal), message="Interview cancelled"
    )


@router.post(
    "/{interview_id}/complete",
    response_model=SuccessResponse[InterviewDetail],
    summary="Mark an interview complete",
    dependencies=[Depends(require_permission(Perm.INTERVIEW_UPDATE))],
)
async def complete_interview(
    interview_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[InterviewDetail]:
    service = InterviewService(session, company_id)
    interview = await service.get(interview_id)
    await service.mark_completed(interview, actor_id=principal.id)
    await session.commit()
    await service.events.flush()

    interview = await service.get(interview_id)
    return SuccessResponse(
        data=await _to_detail(session, interview, principal),
        message="Interview marked complete - feedback is now due",
    )


# ------------------------------------------------------------------ feedback
@router.post(
    "/{interview_id}/feedback",
    response_model=SuccessResponse[FeedbackOut],
    status_code=status.HTTP_201_CREATED,
    summary="Submit interview feedback",
    description=(
        "Only participants may submit. `private_remarks` are visible to you and company "
        "admins only, and are never shown to the candidate or fed into AI summaries."
    ),
    dependencies=[Depends(require_permission(Perm.FEEDBACK_SUBMIT))],
)
async def submit_feedback(
    interview_id: uuid.UUID,
    payload: FeedbackCreate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[FeedbackOut]:
    service = InterviewService(session, company_id)
    interview = await service.get(interview_id)
    feedback = await service.submit_feedback(
        interview, interviewer_id=principal.id, **payload.model_dump()
    )
    await session.commit()
    await service.events.flush()

    return SuccessResponse(
        data=FeedbackOut.model_validate(feedback),
        message="Feedback saved as a draft" if payload.is_draft else "Feedback submitted",
    )


@router.get(
    "/{interview_id}/feedback",
    response_model=SuccessResponse[list[FeedbackOut]],
    summary="List feedback for an interview",
    dependencies=[Depends(require_permission(Perm.FEEDBACK_READ))],
)
async def list_feedback(
    interview_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[list[FeedbackOut]]:
    service = InterviewService(session, company_id)
    interview = await service.get(interview_id)

    items: list[FeedbackOut] = []
    for feedback in interview.feedback:
        payload = FeedbackOut.model_validate(feedback)
        # Private remarks belong to their author unless the caller is an admin.
        if not principal.has(Perm.FEEDBACK_READ_PRIVATE) and (
            feedback.interviewer_id != principal.id
        ):
            payload.private_remarks = None
        items.append(payload)
    return SuccessResponse(data=items)


@router.post(
    "/applications/{application_id}/summarize-feedback",
    response_model=SuccessResponse[FeedbackSummaryResponse],
    summary="AI-summarise all feedback for an application",
    description=(
        "Digests every submitted feedback form into strengths, weaknesses and whether "
        "interviewers agree. Private remarks are excluded. Advisory only."
    ),
    dependencies=[Depends(require_permission(Perm.AI_GENERATE))],
)
async def summarize_feedback(
    application_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[FeedbackSummaryResponse]:
    service = InterviewService(session, company_id)
    summary, strengths, weaknesses, consensus, engine = await service.summarise_feedback(
        application_id, actor_id=principal.id
    )
    count = (
        await session.execute(
            select(func.count())
            .select_from(InterviewFeedback)
            .where(
                InterviewFeedback.application_id == application_id,
                InterviewFeedback.is_draft.is_(False),
            )
        )
    ).scalar_one()

    return SuccessResponse(
        data=FeedbackSummaryResponse(
            summary=summary,
            strengths=strengths,
            weaknesses=weaknesses,
            consensus=consensus,
            engine=engine,
            feedback_count=count,
        )
    )
