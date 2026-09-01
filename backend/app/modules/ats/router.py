"""ATS scoring, ranking and weight-configuration endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import AtsRecommendation
from app.core.exceptions import ResourceNotFound
from app.core.permissions import Perm
from app.core.responses import SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.application import Application
from app.modules.ats.service import AtsService
from app.schemas.common import ORMModel

router = APIRouter(prefix="/ats", tags=["ATS"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


# ------------------------------------------------------------------ schemas
class MatchOut(ORMModel):
    dimension: str
    requirement: str
    importance: str
    is_matched: bool
    match_strength: float
    evidence: str | None = None


class ComponentOut(BaseModel):
    score: float
    weight: float
    contribution: float
    explanation: str
    details: dict = Field(default_factory=dict)


class AtsScoreOut(ORMModel):
    id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    overall_score: float
    skills_score: float
    experience_score: float
    education_score: float
    responsibilities_score: float
    semantic_score: float
    recommendation: AtsRecommendation
    weights_used: dict = Field(default_factory=dict)
    #: Plain-language reasoning for every component - this is what makes the score
    #: auditable rather than an oracle.
    explanation: dict = Field(default_factory=dict)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    engine_version: str
    semantic_engine: str
    computed_ms: int | None = None
    matches: list[MatchOut] = Field(default_factory=list)
    created_at: datetime
    disclaimer: str = (
        "This score ranks applications against the requirements written on the job. It "
        "is a screening aid for recruiters, not a hiring decision."
    )


class WeightProfileOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    is_default: bool
    skills_weight: float
    experience_weight: float
    education_weight: float
    responsibilities_weight: float
    semantic_weight: float
    strong_match_threshold: float
    good_match_threshold: float
    partial_match_threshold: float
    created_at: datetime


class WeightProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    skills_weight: float = Field(default=0.40, ge=0, le=1)
    experience_weight: float = Field(default=0.25, ge=0, le=1)
    education_weight: float = Field(default=0.10, ge=0, le=1)
    responsibilities_weight: float = Field(default=0.15, ge=0, le=1)
    semantic_weight: float = Field(default=0.10, ge=0, le=1)
    strong_match_threshold: float = Field(default=85, ge=0, le=100)
    good_match_threshold: float = Field(default=70, ge=0, le=100)
    partial_match_threshold: float = Field(default=50, ge=0, le=100)
    is_default: bool = False

    @model_validator(mode="after")
    def _check(self) -> WeightProfileCreate:
        total = (
            self.skills_weight
            + self.experience_weight
            + self.education_weight
            + self.responsibilities_weight
            + self.semantic_weight
        )
        if total <= 0:
            raise ValueError("At least one weight must be greater than zero")
        if not (
            self.strong_match_threshold
            > self.good_match_threshold
            > self.partial_match_threshold
        ):
            raise ValueError(
                "Thresholds must decrease: strong > good > partial"
            )
        return self


class RankedCandidate(BaseModel):
    rank: int
    application_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_name: str
    current_designation: str | None = None
    total_experience_years: float
    ats_score: float
    recommendation: str | None = None
    status: str
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)


class RescoreResponse(BaseModel):
    total: int
    scored: int
    failed: int
    message: str


# ----------------------------------------------------------------- endpoints
@router.get(
    "/applications/{application_id}",
    response_model=SuccessResponse[AtsScoreOut],
    summary="Get the latest ATS analysis for an application",
    description=(
        "Returns the full explainable breakdown: per-component scores, the weights used, "
        "matched and missing requirements, and the reasoning behind each number."
    ),
    dependencies=[Depends(require_permission(Perm.ATS_READ))],
)
async def get_score(
    application_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[AtsScoreOut]:
    service = AtsService(session, company_id)
    score = await service.latest_for_application(application_id)
    if score is None:
        raise ResourceNotFound("ATS score", application_id)

    payload = AtsScoreOut.model_validate(score)
    payload.matched_skills = score.matched_skills
    payload.missing_skills = score.missing_skills
    return SuccessResponse(data=payload)


@router.get(
    "/applications/{application_id}/history",
    response_model=SuccessResponse[list[AtsScoreOut]],
    summary="ATS score history",
    description=(
        "Every scoring run for this application, newest first. Lets a recruiter see that "
        "a score changed because the job requirements were edited."
    ),
    dependencies=[Depends(require_permission(Perm.ATS_READ))],
)
async def score_history(
    application_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[AtsScoreOut]]:
    service = AtsService(session, company_id)
    scores = await service.history_for_application(application_id)
    return SuccessResponse(data=[AtsScoreOut.model_validate(s) for s in scores])


@router.post(
    "/applications/{application_id}/score",
    response_model=SuccessResponse[AtsScoreOut],
    summary="Re-score an application now",
    dependencies=[Depends(require_permission(Perm.ATS_RUN))],
)
async def score_application(
    application_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[AtsScoreOut]:
    service = AtsService(session, company_id)
    score = await service.score(application_id, actor_id=principal.id)
    await session.commit()
    await service.events.flush()

    fresh = await service.latest_for_application(application_id)
    payload = AtsScoreOut.model_validate(fresh or score)
    payload.matched_skills = (fresh or score).matched_skills
    payload.missing_skills = (fresh or score).missing_skills
    return SuccessResponse(data=payload, message="Application re-scored")


@router.post(
    "/jobs/{job_id}/rescore",
    response_model=SuccessResponse[RescoreResponse],
    summary="Re-score every application on a job",
    description="Use after editing a job's requirements so rankings reflect the new bar.",
    dependencies=[Depends(require_permission(Perm.ATS_RUN))],
)
async def rescore_job(
    job_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
    background: Annotated[bool, Query(description="Queue instead of running inline")] = True,
) -> SuccessResponse[RescoreResponse]:
    if background:
        from app.workers.queue import get_queue

        await get_queue().enqueue(
            "rescore_job",
            job_id=str(job_id),
            company_id=str(company_id),
            actor_id=str(principal.id),
        )
        return SuccessResponse(
            data=RescoreResponse(
                total=0, scored=0, failed=0, message="Re-scoring has been queued"
            ),
            message="Re-scoring queued - results will appear shortly",
        )

    service = AtsService(session, company_id)
    result = await service.rescore_job(job_id, actor_id=principal.id)
    await session.commit()
    return SuccessResponse(
        data=RescoreResponse(**result, message="Re-scoring complete"),
        message=f"{result['scored']} of {result['total']} applications re-scored",
    )


@router.get(
    "/jobs/{job_id}/ranking",
    response_model=SuccessResponse[list[RankedCandidate]],
    summary="Ranked candidates for a job",
    description="Applications ordered by ATS score, with matched and missing requirements.",
    dependencies=[Depends(require_permission(Perm.ATS_READ))],
)
async def job_ranking(
    job_id: uuid.UUID,
    company_id: CompanyScope,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
) -> SuccessResponse[list[RankedCandidate]]:
    stmt = (
        select(Application)
        .where(
            Application.job_id == job_id,
            Application.company_id == company_id,
            Application.ats_score.is_not(None),
        )
        .options(selectinload(Application.candidate))
        .order_by(Application.ats_score.desc(), Application.created_at.asc())
        .limit(limit)
    )
    if min_score is not None:
        stmt = stmt.where(Application.ats_score >= min_score)

    applications = (await session.execute(stmt)).unique().scalars().all()

    service = AtsService(session, company_id)
    results: list[RankedCandidate] = []
    for index, application in enumerate(applications, start=1):
        score = await service.latest_for_application(application.id)
        results.append(
            RankedCandidate(
                rank=application.ats_rank or index,
                application_id=application.id,
                candidate_id=application.candidate_id,
                candidate_name=application.candidate.full_name,
                current_designation=application.candidate.current_designation,
                total_experience_years=float(
                    application.candidate.total_experience_years or 0
                ),
                ats_score=float(application.ats_score),
                recommendation=score.recommendation.value if score else None,
                status=application.status.value,
                matched_skills=(score.matched_skills[:8] if score else []),
                missing_skills=(score.missing_skills[:8] if score else []),
            )
        )
    return SuccessResponse(data=results)


# ------------------------------------------------------------ weight profiles
@router.get(
    "/weight-profiles",
    response_model=SuccessResponse[list[WeightProfileOut]],
    summary="List ATS weight profiles",
    description=(
        "Weights are configurable per company and can be overridden per job. They are "
        "normalised at scoring time, so any set of positive numbers is valid."
    ),
    dependencies=[Depends(require_permission(Perm.ATS_READ))],
)
async def list_profiles(
    company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[WeightProfileOut]]:
    service = AtsService(session, company_id)
    await service.ensure_default_profile()
    await session.flush()
    profiles = await service.list_profiles()
    return SuccessResponse(data=[WeightProfileOut.model_validate(p) for p in profiles])


@router.post(
    "/weight-profiles",
    response_model=SuccessResponse[WeightProfileOut],
    summary="Create an ATS weight profile",
    dependencies=[Depends(require_permission(Perm.ATS_CONFIG_MANAGE))],
)
async def create_profile(
    payload: WeightProfileCreate, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[WeightProfileOut]:
    service = AtsService(session, company_id)
    profile = await service.create_profile(
        name=payload.name,
        description=payload.description,
        weights={
            "skills": payload.skills_weight,
            "experience": payload.experience_weight,
            "education": payload.education_weight,
            "responsibilities": payload.responsibilities_weight,
            "semantic": payload.semantic_weight,
        },
        thresholds={
            "strong": payload.strong_match_threshold,
            "good": payload.good_match_threshold,
            "partial": payload.partial_match_threshold,
        },
        is_default=payload.is_default,
    )
    return SuccessResponse(
        data=WeightProfileOut.model_validate(profile),
        message="Weight profile created. Re-score jobs to apply it to existing applications.",
    )


@router.get(
    "/explain",
    response_model=SuccessResponse[dict],
    summary="How ATS scoring works",
    description=(
        "Documents the scoring model for recruiters and for compliance review - what "
        "each dimension measures and how the weights combine."
    ),
)
async def explain_scoring() -> SuccessResponse[dict]:
    return SuccessResponse(
        data={
            "overview": (
                "Every application is scored on five independent dimensions, each "
                "producing a 0-100 sub-score. The overall score is their weighted "
                "average. Weights are configurable per company and per job."
            ),
            "dimensions": {
                "skills": (
                    "Weighted coverage of the job's required and preferred skills. "
                    "Matching is alias-aware ('ReactJS' satisfies 'React') and each "
                    "skill can carry its own 1-5 importance."
                ),
                "experience": (
                    "Years of experience against the job's band. Meeting the minimum "
                    "scores 100; falling short degrades proportionally rather than to "
                    "zero. Substantially exceeding the band is mildly reduced (never "
                    "below 80) as a level-fit prompt."
                ),
                "education": (
                    "Highest attained qualification against the highest the job asks "
                    "for. Meeting or exceeding it scores 100; one rung short scores 60."
                ),
                "responsibilities": (
                    "How much of the job's day-to-day work the candidate has "
                    "demonstrably done, compared against their own experience bullets. "
                    "This is what separates 'has the keyword' from 'has done the work'."
                ),
                "semantic": (
                    "Overall similarity in meaning between the resume and the job "
                    "description, so different vocabulary for the same work still "
                    "matches."
                ),
            },
            "governance": [
                "Scores rank applications; they never reject anyone.",
                "Every score stores the weights and reasoning used, so it can be audited.",
                "Protected attributes are never inferred, stored or used.",
                "Recruiters can override any score-driven suggestion.",
            ],
        }
    )
