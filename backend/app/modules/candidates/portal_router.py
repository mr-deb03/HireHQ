"""Candidate self-service portal.

Everything here is scoped to the signed-in candidate's *own* records, across every
company they have applied to. Internal data - ATS scores, recruiter notes, interview
feedback - is never exposed on these routes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import (
    ApplicationStatus,
    AssessmentAttemptStatus,
    InterviewStatus,
    OfferStatus,
)
from app.core.exceptions import BusinessRuleError, ResourceNotFound
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CurrentUser
from app.models.application import Application
from app.models.assessment import AssessmentAttempt
from app.models.candidate import Candidate
from app.models.company import Company
from app.models.interview import Interview
from app.models.offer import Offer, Onboarding
from app.modules.applications.service import ApplicationPipelineService
from app.modules.applications.state_machine import candidate_label
from app.schemas.common import PaginationParams, pagination

router = APIRouter(prefix="/me", tags=["Candidates"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _my_candidate_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Every candidate record belonging to this login, across all companies."""
    return list(
        (
            await session.execute(
                select(Candidate.id).where(
                    Candidate.user_id == user_id, Candidate.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )


class MyApplicationOut(BaseModel):
    id: uuid.UUID
    reference_code: str
    status_label: str
    job_title: str
    company_name: str | None = None
    location: str | None = None
    applied_at: datetime
    last_updated: datetime
    can_withdraw: bool


class MyApplicationDetail(MyApplicationOut):
    cover_letter: str | None = None
    timeline: list[dict] = Field(default_factory=list)
    upcoming_interviews: list[dict] = Field(default_factory=list)
    pending_assessments: list[dict] = Field(default_factory=list)
    offer: dict | None = None


class WithdrawRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


@router.get(
    "/applications",
    response_model=SuccessResponse[Page[MyApplicationOut]],
    summary="Your applications",
    description="Every application you have submitted, across all companies.",
)
async def my_applications(
    principal: CurrentUser,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    active_only: Annotated[bool, Query()] = False,
) -> SuccessResponse[Page[MyApplicationOut]]:
    candidate_ids = await _my_candidate_ids(session, principal.id)
    if not candidate_ids:
        return SuccessResponse(
            data=Page.build([], page=page_params.page, page_size=page_params.page_size, total=0)
        )

    stmt = (
        select(Application)
        .where(Application.candidate_id.in_(candidate_ids))
        .options(selectinload(Application.job))
    )
    if active_only:
        stmt = stmt.where(
            Application.status.not_in(
                [
                    ApplicationStatus.REJECTED,
                    ApplicationStatus.WITHDRAWN,
                    ApplicationStatus.OFFER_REJECTED,
                ]
            )
        )

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(Application.created_at.desc())
                .limit(page_params.page_size)
                .offset(page_params.offset)
            )
        )
        .unique()
        .scalars()
        .all()
    )

    companies = {
        c.id: c.name
        for c in (
            (
                await session.execute(
                    select(Company).where(
                        Company.id.in_({a.company_id for a in rows} or {uuid.uuid4()})
                    )
                )
            )
            .scalars()
            .all()
        )
    }

    return SuccessResponse(
        data=Page.build(
            [
                MyApplicationOut(
                    id=a.id,
                    reference_code=a.reference_code,
                    status_label=candidate_label(a.status),
                    job_title=a.job.title if a.job else "",
                    company_name=companies.get(a.company_id),
                    location=a.job.location_text if a.job else None,
                    applied_at=a.created_at,
                    last_updated=a.status_changed_at or a.updated_at,
                    can_withdraw=a.status
                    not in (
                        ApplicationStatus.HIRED,
                        ApplicationStatus.REJECTED,
                        ApplicationStatus.WITHDRAWN,
                    ),
                )
                for a in rows
            ],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


async def _load_my_application(
    session: AsyncSession, user_id: uuid.UUID, application_id: uuid.UUID
) -> Application:
    candidate_ids = await _my_candidate_ids(session, user_id)
    application = (
        (
            await session.execute(
                select(Application)
                .where(
                    Application.id == application_id,
                    Application.candidate_id.in_(candidate_ids or [uuid.uuid4()]),
                )
                .options(selectinload(Application.job))
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if application is None:
        raise ResourceNotFound("Application", application_id)
    return application


@router.get(
    "/applications/{application_id}",
    response_model=SuccessResponse[MyApplicationDetail],
    summary="Track one of your applications",
    description=(
        "Shows your progress, upcoming interviews, pending assessments and any offer. "
        "Internal scores, notes and interview feedback are never included."
    ),
)
async def my_application_detail(
    application_id: uuid.UUID, principal: CurrentUser, session: DbSession
) -> SuccessResponse[MyApplicationDetail]:
    application = await _load_my_application(session, principal.id, application_id)
    company = await session.get(Company, application.company_id)

    pipeline = ApplicationPipelineService(session, application.company_id)
    timeline = await pipeline.get_timeline(application.id, candidate_view=True)

    interviews = (
        (
            await session.execute(
                select(Interview)
                .where(
                    Interview.application_id == application.id,
                    Interview.scheduled_start >= datetime.now(UTC),
                    Interview.status.in_(
                        [InterviewStatus.SCHEDULED, InterviewStatus.CONFIRMED, InterviewStatus.RESCHEDULED]
                    ),
                )
                .order_by(Interview.scheduled_start)
            )
        )
        .unique()
        .scalars()
        .all()
    )

    attempts = (
        (
            await session.execute(
                select(AssessmentAttempt)
                .where(
                    AssessmentAttempt.application_id == application.id,
                    AssessmentAttempt.status.in_(
                        [
                            AssessmentAttemptStatus.NOT_STARTED,
                            AssessmentAttemptStatus.IN_PROGRESS,
                        ]
                    ),
                )
                .options(selectinload(AssessmentAttempt.answers))
            )
        )
        .unique()
        .scalars()
        .all()
    )

    offer = await session.scalar(
        select(Offer)
        .where(
            Offer.application_id == application.id,
            Offer.status.in_(
                [
                    OfferStatus.SENT,
                    OfferStatus.VIEWED,
                    OfferStatus.ACCEPTED,
                    OfferStatus.REJECTED,
                ]
            ),
        )
        .order_by(Offer.created_at.desc())
        .limit(1)
    )

    return SuccessResponse(
        data=MyApplicationDetail(
            id=application.id,
            reference_code=application.reference_code,
            status_label=candidate_label(application.status),
            job_title=application.job.title if application.job else "",
            company_name=company.name if company else None,
            location=application.job.location_text if application.job else None,
            applied_at=application.created_at,
            last_updated=application.status_changed_at or application.updated_at,
            can_withdraw=application.status
            not in (
                ApplicationStatus.HIRED,
                ApplicationStatus.REJECTED,
                ApplicationStatus.WITHDRAWN,
            ),
            cover_letter=application.cover_letter,
            timeline=[
                {
                    "title": e.title,
                    "description": e.description,
                    "at": e.created_at.isoformat(),
                }
                for e in timeline
            ],
            upcoming_interviews=[
                {
                    "id": str(i.id),
                    "title": i.title,
                    "round": i.round_name or f"Round {i.round_number}",
                    "type": i.interview_type.value,
                    "scheduled_start": i.scheduled_start.isoformat(),
                    "duration_minutes": i.duration_minutes,
                    "timezone": i.timezone,
                    "meeting_link": i.meeting_link,
                    "location": i.location,
                    "instructions": i.candidate_instructions,
                }
                for i in interviews
            ],
            pending_assessments=[
                {
                    "attempt_id": str(a.id),
                    "assessment_id": str(a.assessment_id),
                    "status": a.status.value,
                    "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                }
                for a in attempts
            ],
            offer=(
                {
                    "id": str(offer.id),
                    "reference_code": offer.reference_code,
                    "position_title": offer.position_title,
                    "status": offer.status.value,
                    "joining_date": (
                        offer.joining_date.isoformat() if offer.joining_date else None
                    ),
                    "expires_at": offer.expires_at.isoformat() if offer.expires_at else None,
                }
                if offer
                else None
            ),
        )
    )


@router.post(
    "/applications/{application_id}/withdraw",
    response_model=SuccessResponse[dict],
    summary="Withdraw your application",
)
async def withdraw_application(
    application_id: uuid.UUID,
    payload: WithdrawRequest,
    principal: CurrentUser,
    session: DbSession,
) -> SuccessResponse[dict]:
    application = await _load_my_application(session, principal.id, application_id)
    if application.status in (
        ApplicationStatus.HIRED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    ):
        raise BusinessRuleError(
            f"This application is already {application.status.value.lower()} and cannot "
            "be withdrawn"
        )

    pipeline = ApplicationPipelineService(session, application.company_id)
    await pipeline.change_status(
        application,
        new_status=ApplicationStatus.WITHDRAWN,
        actor_id=principal.id,
        reason=payload.reason or "Withdrawn by the candidate",
    )
    await session.commit()
    await pipeline.events.flush()

    return SuccessResponse(
        data={"id": str(application_id), "status": ApplicationStatus.WITHDRAWN.value},
        message="Your application has been withdrawn",
    )


@router.get(
    "/interviews",
    response_model=SuccessResponse[list[dict]],
    summary="Your upcoming interviews",
)
async def my_interviews(
    principal: CurrentUser, session: DbSession
) -> SuccessResponse[list[dict]]:
    candidate_ids = await _my_candidate_ids(session, principal.id)
    if not candidate_ids:
        return SuccessResponse(data=[])

    rows = (
        (
            await session.execute(
                select(Interview)
                .where(
                    Interview.candidate_id.in_(candidate_ids),
                    Interview.status.not_in(
                        [InterviewStatus.CANCELLED, InterviewStatus.COMPLETED]
                    ),
                )
                .options(selectinload(Interview.application).selectinload(Application.job))
                .order_by(Interview.scheduled_start)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=[
            {
                "id": str(i.id),
                "title": i.title,
                "job_title": i.application.job.title if i.application and i.application.job else None,
                "round": i.round_name or f"Round {i.round_number}",
                "type": i.interview_type.value,
                "scheduled_start": i.scheduled_start.isoformat(),
                "duration_minutes": i.duration_minutes,
                "timezone": i.timezone,
                "meeting_link": i.meeting_link,
                "location": i.location,
                "instructions": i.candidate_instructions,
                "status": i.status.value,
            }
            for i in rows
        ]
    )


@router.post(
    "/interviews/{interview_id}/confirm",
    response_model=SuccessResponse[dict],
    summary="Confirm you will attend an interview",
)
async def confirm_interview(
    interview_id: uuid.UUID, principal: CurrentUser, session: DbSession
) -> SuccessResponse[dict]:
    candidate_ids = await _my_candidate_ids(session, principal.id)
    interview = await session.scalar(
        select(Interview).where(
            Interview.id == interview_id,
            Interview.candidate_id.in_(candidate_ids or [uuid.uuid4()]),
        )
    )
    if interview is None:
        raise ResourceNotFound("Interview", interview_id)
    if interview.status == InterviewStatus.CANCELLED:
        raise BusinessRuleError("This interview has been cancelled")

    interview.candidate_confirmed_at = datetime.now(UTC)
    interview.status = InterviewStatus.CONFIRMED
    await session.flush()
    return SuccessResponse(
        data={"id": str(interview_id), "confirmed": True}, message="Attendance confirmed"
    )


@router.get(
    "/offers",
    response_model=SuccessResponse[list[dict]],
    summary="Your offers",
)
async def my_offers(
    principal: CurrentUser, session: DbSession
) -> SuccessResponse[list[dict]]:
    candidate_ids = await _my_candidate_ids(session, principal.id)
    if not candidate_ids:
        return SuccessResponse(data=[])

    rows = (
        (
            await session.execute(
                select(Offer)
                .where(
                    Offer.candidate_id.in_(candidate_ids),
                    Offer.status.not_in([OfferStatus.DRAFT, OfferStatus.WITHDRAWN]),
                )
                .order_by(Offer.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    companies = {
        c.id: c.name
        for c in (
            (
                await session.execute(
                    select(Company).where(
                        Company.id.in_({o.company_id for o in rows} or {uuid.uuid4()})
                    )
                )
            )
            .scalars()
            .all()
        )
    }
    return SuccessResponse(
        data=[
            {
                "id": str(o.id),
                "reference_code": o.reference_code,
                "company_name": companies.get(o.company_id),
                "position_title": o.position_title,
                "base_salary": float(o.base_salary),
                "total_compensation": o.total_compensation,
                "currency": o.currency,
                "salary_period": o.salary_period,
                "benefits": o.benefits,
                "joining_date": o.joining_date.isoformat() if o.joining_date else None,
                "status": o.status.value,
                "expires_at": o.expires_at.isoformat() if o.expires_at else None,
                "can_respond": o.status in (OfferStatus.SENT, OfferStatus.VIEWED),
            }
            for o in rows
        ]
    )


@router.get(
    "/onboarding",
    response_model=SuccessResponse[list[dict]],
    summary="Your onboarding checklist",
)
async def my_onboarding(
    principal: CurrentUser, session: DbSession
) -> SuccessResponse[list[dict]]:
    candidate_ids = await _my_candidate_ids(session, principal.id)
    if not candidate_ids:
        return SuccessResponse(data=[])

    rows = (
        (
            await session.execute(
                select(Onboarding)
                .where(Onboarding.candidate_id.in_(candidate_ids))
                .options(selectinload(Onboarding.tasks))
            )
        )
        .unique()
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=[
            {
                "id": str(o.id),
                "status": o.status.value,
                "expected_joining_date": (
                    o.expected_joining_date.isoformat() if o.expected_joining_date else None
                ),
                "completion_percentage": o.completion_percentage,
                # Only tasks the candidate has to act on.
                "tasks": [
                    {
                        "id": str(t.id),
                        "title": t.title,
                        "description": t.description,
                        "category": t.category,
                        "is_required": t.is_required,
                        "due_date": t.due_date.isoformat() if t.due_date else None,
                        "completed": t.completed_at is not None,
                    }
                    for t in o.tasks
                    if t.owner_type == "CANDIDATE"
                ],
            }
            for o in rows
        ]
    )


@router.get(
    "/dashboard",
    response_model=SuccessResponse[dict],
    summary="Candidate dashboard summary",
)
async def candidate_dashboard(
    principal: CurrentUser, session: DbSession
) -> SuccessResponse[dict]:
    candidate_ids = await _my_candidate_ids(session, principal.id)
    if not candidate_ids:
        return SuccessResponse(
            data={
                "applications": 0,
                "in_progress": 0,
                "upcoming_interviews": 0,
                "pending_offers": 0,
                "profile_completeness": 0,
            }
        )

    async def count(stmt) -> int:
        return (await session.execute(stmt)).scalar_one()

    applications = await count(
        select(func.count())
        .select_from(Application)
        .where(Application.candidate_id.in_(candidate_ids))
    )
    in_progress = await count(
        select(func.count())
        .select_from(Application)
        .where(
            Application.candidate_id.in_(candidate_ids),
            Application.status.not_in(
                [
                    ApplicationStatus.REJECTED,
                    ApplicationStatus.WITHDRAWN,
                    ApplicationStatus.HIRED,
                    ApplicationStatus.OFFER_REJECTED,
                ]
            ),
        )
    )
    upcoming = await count(
        select(func.count())
        .select_from(Interview)
        .where(
            Interview.candidate_id.in_(candidate_ids),
            Interview.scheduled_start >= datetime.now(UTC),
            Interview.status.in_([InterviewStatus.SCHEDULED, InterviewStatus.CONFIRMED]),
        )
    )
    offers = await count(
        select(func.count())
        .select_from(Offer)
        .where(
            Offer.candidate_id.in_(candidate_ids),
            Offer.status.in_([OfferStatus.SENT, OfferStatus.VIEWED]),
        )
    )

    candidate = (
        (
            await session.execute(
                select(Candidate)
                .where(Candidate.id.in_(candidate_ids))
                .options(
                    selectinload(Candidate.skills),
                    selectinload(Candidate.experience),
                    selectinload(Candidate.education),
                )
                .order_by(Candidate.updated_at.desc())
                .limit(1)
            )
        )
        .unique()
        .scalar_one_or_none()
    )

    completeness = 0
    if candidate is not None:
        checks = [
            bool(candidate.phone),
            bool(candidate.location),
            bool(candidate.current_designation),
            bool(candidate.skills),
            bool(candidate.experience),
            bool(candidate.education),
            bool(candidate.linkedin_url or candidate.github_url or candidate.portfolio_url),
            bool(candidate.summary),
        ]
        completeness = round(sum(checks) / len(checks) * 100)

    return SuccessResponse(
        data={
            "applications": applications,
            "in_progress": in_progress,
            "upcoming_interviews": upcoming,
            "pending_offers": offers,
            "profile_completeness": completeness,
        }
    )
