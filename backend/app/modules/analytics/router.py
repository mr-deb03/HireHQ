"""Analytics and dashboard endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import InterviewStatus
from app.core.permissions import Perm
from app.core.responses import SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.application import Application
from app.models.interview import Interview
from app.modules.analytics.service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadAnalytics = Depends(require_permission(Perm.ANALYTICS_READ))


@router.get(
    "/dashboard",
    response_model=SuccessResponse[dict],
    summary="Recruiter dashboard",
    description=(
        "Everything the command centre needs in one call: KPIs, the attention list and "
        "today's interviews."
    ),
    dependencies=[ReadAnalytics],
)
async def dashboard(
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
    mine_only: Annotated[bool, Query(description="Restrict to applications assigned to me")] = False,
) -> SuccessResponse[dict]:
    service = AnalyticsService(session, company_id)
    kpis = await service.dashboard_kpis(recruiter_id=principal.id if mine_only else None)
    attention = await service.attention_required()
    funnel = await service.funnel()

    now = datetime.now(UTC)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    todays = (
        (
            await session.execute(
                select(Interview)
                .where(
                    Interview.company_id == company_id,
                    Interview.scheduled_start >= start_of_day,
                    Interview.scheduled_start < start_of_day.replace(hour=23, minute=59),
                    Interview.status.in_(
                        [InterviewStatus.SCHEDULED, InterviewStatus.CONFIRMED]
                    ),
                )
                .options(
                    selectinload(Interview.application).selectinload(Application.candidate)
                )
                .order_by(Interview.scheduled_start)
                .limit(20)
            )
        )
        .unique()
        .scalars()
        .all()
    )

    greeting_hour = now.hour
    greeting = (
        "Good morning"
        if greeting_hour < 12
        else ("Good afternoon" if greeting_hour < 17 else "Good evening")
    )

    return SuccessResponse(
        data={
            "greeting": f"{greeting}, {principal.user.first_name}",
            "kpis": kpis,
            "attention_required": attention,
            "funnel": funnel["stages"],
            "todays_interviews": [
                {
                    "id": str(i.id),
                    "time": i.scheduled_start.strftime("%H:%M"),
                    "scheduled_start": i.scheduled_start.isoformat(),
                    "title": i.title,
                    "interview_type": i.interview_type.value,
                    "candidate_name": (
                        i.application.candidate.full_name if i.application else None
                    ),
                    "candidate_id": str(i.candidate_id),
                    "meeting_link": i.meeting_link,
                }
                for i in todays
            ],
        }
    )


@router.get(
    "/funnel",
    response_model=SuccessResponse[dict],
    summary="Recruitment funnel",
    description="Cumulative stage counts with stage-to-stage conversion percentages.",
    dependencies=[ReadAnalytics],
)
async def funnel(
    company_id: CompanyScope,
    session: DbSession,
    job_id: uuid.UUID | None = None,
    since: date | None = None,
    until: date | None = None,
) -> SuccessResponse[dict]:
    service = AnalyticsService(session, company_id)
    return SuccessResponse(data=await service.funnel(job_id=job_id, since=since, until=until))


@router.get(
    "/sources",
    response_model=SuccessResponse[list[dict]],
    summary="Source performance",
    description="Applications, shortlists, interviews and hires for each traffic source.",
    dependencies=[ReadAnalytics],
)
async def sources(
    company_id: CompanyScope,
    session: DbSession,
    since: date | None = None,
    until: date | None = None,
) -> SuccessResponse[list[dict]]:
    service = AnalyticsService(session, company_id)
    return SuccessResponse(data=await service.source_performance(since=since, until=until))


@router.get(
    "/ats-distribution",
    response_model=SuccessResponse[list[dict]],
    summary="ATS score distribution",
    dependencies=[ReadAnalytics],
)
async def ats_distribution(
    company_id: CompanyScope, session: DbSession, job_id: uuid.UUID | None = None
) -> SuccessResponse[list[dict]]:
    service = AnalyticsService(session, company_id)
    return SuccessResponse(data=await service.ats_distribution(job_id=job_id))


@router.get(
    "/time-to-hire",
    response_model=SuccessResponse[dict],
    summary="Time to hire and time in each stage",
    dependencies=[ReadAnalytics],
)
async def time_to_hire(
    company_id: CompanyScope, session: DbSession, job_id: uuid.UUID | None = None
) -> SuccessResponse[dict]:
    service = AnalyticsService(session, company_id)
    return SuccessResponse(data=await service.time_to_hire(job_id=job_id))


@router.get(
    "/jobs",
    response_model=SuccessResponse[dict],
    summary="Job performance comparison",
    description="Highest and lowest volume jobs, and the best interview conversion rates.",
    dependencies=[ReadAnalytics],
)
async def job_performance(
    company_id: CompanyScope,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SuccessResponse[dict]:
    service = AnalyticsService(session, company_id)
    return SuccessResponse(data=await service.job_performance(limit=limit))


@router.get(
    "/recruiters",
    response_model=SuccessResponse[list[dict]],
    summary="Applications and hires per recruiter",
    dependencies=[ReadAnalytics],
)
async def recruiter_performance(
    company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[dict]]:
    service = AnalyticsService(session, company_id)
    return SuccessResponse(data=await service.recruiter_performance())


@router.get(
    "/drop-off",
    response_model=SuccessResponse[list[dict]],
    summary="Where candidates leave the process",
    dependencies=[ReadAnalytics],
)
async def drop_off(
    company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[dict]]:
    service = AnalyticsService(session, company_id)
    return SuccessResponse(data=await service.drop_off())


@router.get(
    "/applications-over-time",
    response_model=SuccessResponse[list[dict]],
    summary="Daily application volume",
    dependencies=[ReadAnalytics],
)
async def applications_over_time(
    company_id: CompanyScope,
    session: DbSession,
    days: Annotated[int, Query(ge=7, le=365)] = 30,
) -> SuccessResponse[list[dict]]:
    service = AnalyticsService(session, company_id)
    return SuccessResponse(data=await service.applications_over_time(days=days))
