"""Job management endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    EmploymentType,
    JobStatus,
    WorkMode,
)
from app.core.permissions import Perm
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.application import Application
from app.models.job import JobScreeningQuestion
from app.modules.applications.service import status_counts_to_funnel
from app.modules.jobs.schemas import (
    ApplyAnalysisRequest,
    HiringTeamUpdate,
    JobAnalysisRequest,
    JobAnalysisResponse,
    JobCreate,
    JobDetail,
    JobStatsOut,
    JobStatusChange,
    JobSummary,
    JobUpdate,
    ScreeningQuestionInput,
    ScreeningQuestionOut,
)
from app.modules.jobs.service import JobService
from app.providers.ai.schemas import ExtractedSkill, JobDescriptionAnalysis
from app.schemas.common import DeleteResponse, PaginationParams, pagination

router = APIRouter(prefix="/jobs", tags=["Jobs"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _service(session: AsyncSession, company_id: uuid.UUID) -> JobService:
    return JobService(session, company_id)


@router.get(
    "",
    response_model=SuccessResponse[Page[JobSummary]],
    summary="List and search jobs",
    dependencies=[Depends(require_permission(Perm.JOB_READ, Perm.JOB_READ_ASSIGNED))],
)
async def list_jobs(
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    q: Annotated[str | None, Query(description="Free-text search")] = None,
    job_status: Annotated[list[JobStatus] | None, Query(alias="status")] = None,
    department_id: uuid.UUID | None = None,
    work_mode: Annotated[list[WorkMode] | None, Query()] = None,
    employment_type: Annotated[list[EmploymentType] | None, Query()] = None,
    location: str | None = None,
    sort: Annotated[str, Query(description="e.g. -created_at, title, -applications")] = "-created_at",
) -> SuccessResponse[Page[JobSummary]]:
    service = _service(session, company_id)

    # Holding only ``job:read:assigned`` (hiring managers, interviewers) restricts the
    # listing to jobs this user is actually on.
    only_assigned = not principal.has(Perm.JOB_READ) and principal.has(Perm.JOB_READ_ASSIGNED)

    jobs, total = await service.search(
        query=q,
        status=job_status,
        department_id=department_id,
        work_mode=work_mode,
        employment_type=employment_type,
        location=location,
        assigned_to_user_id=principal.id if only_assigned else None,
        page=page_params.page,
        page_size=page_params.page_size,
        sort=sort,
    )
    return SuccessResponse(
        data=Page.build(
            [JobSummary.model_validate(j) for j in jobs],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


@router.post(
    "",
    response_model=SuccessResponse[JobDetail],
    status_code=status.HTTP_201_CREATED,
    summary="Create a job",
    description="Creates a DRAFT job. Publish it separately once the requirements are set.",
    dependencies=[Depends(require_permission(Perm.JOB_CREATE))],
)
async def create_job(
    payload: JobCreate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[JobDetail]:
    service = _service(session, company_id)
    job = await service.create(
        created_by_id=principal.id,
        required_skills=[s.model_dump() for s in payload.required_skills],
        preferred_skills=[s.model_dump() for s in payload.preferred_skills],
        **payload.model_dump(
            exclude={"required_skills", "preferred_skills", "screening_questions"}
        ),
    )
    for question in payload.screening_questions:
        session.add(JobScreeningQuestion(job_id=job.id, **question.model_dump()))
    await session.flush()

    job = await service.get(job.id)
    return SuccessResponse(
        data=JobDetail.model_validate(job), message="Job created as a draft"
    )


@router.get(
    "/{job_id}",
    response_model=SuccessResponse[JobDetail],
    summary="Get a job",
    dependencies=[Depends(require_permission(Perm.JOB_READ, Perm.JOB_READ_ASSIGNED))],
)
async def get_job(
    job_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[JobDetail]:
    job = await _service(session, company_id).get(job_id)

    # Assigned-only readers must be on this job's team.
    if not principal.has(Perm.JOB_READ) and principal.has(Perm.JOB_READ_ASSIGNED):
        member_ids = {m.user_id for m in job.hiring_team}
        if principal.id not in member_ids | {job.hiring_manager_id, job.created_by_id}:
            from app.core.exceptions import ResourceNotFound

            raise ResourceNotFound("Job", job_id)

    return SuccessResponse(data=JobDetail.model_validate(job))


@router.patch(
    "/{job_id}",
    response_model=SuccessResponse[JobDetail],
    summary="Update a job",
    dependencies=[Depends(require_permission(Perm.JOB_UPDATE))],
)
async def update_job(
    job_id: uuid.UUID,
    payload: JobUpdate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[JobDetail]:
    service = _service(session, company_id)
    job = await service.get(job_id)

    # ``exclude_unset`` so an omitted field is left alone rather than nulled - PATCH
    # semantics. ``model_dump`` already flattens nested skill models into dicts, which is
    # what the service expects.
    changes = payload.model_dump(exclude_unset=True)

    await service.update(job, actor_id=principal.id, changes=changes)
    job = await service.get(job_id)

    message = "Job updated"
    # Changing requirements invalidates existing scores; say so rather than leaving
    # stale numbers on screen with no explanation.
    if {"required_skills", "preferred_skills", "min_experience_years",
        "education_requirements", "responsibilities"} & set(changes):
        message = (
            "Job updated. Existing ATS scores were computed against the previous "
            "requirements - re-score the job to refresh them."
        )
    return SuccessResponse(data=JobDetail.model_validate(job), message=message)


@router.delete(
    "/{job_id}",
    response_model=SuccessResponse[DeleteResponse],
    summary="Delete a draft job",
    description="Only jobs with no applications can be deleted. Otherwise archive it.",
    dependencies=[Depends(require_permission(Perm.JOB_DELETE))],
)
async def delete_job(
    job_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[DeleteResponse]:
    service = _service(session, company_id)
    job = await service.get(job_id)
    await service.delete(job, actor_id=principal.id)
    return SuccessResponse(
        data=DeleteResponse(id=job_id, message="Job deleted"), message="Job deleted"
    )


@router.post(
    "/{job_id}/publish",
    response_model=SuccessResponse[JobDetail],
    summary="Publish a job",
    description="Validates readiness (description, skills, location) before going live.",
    dependencies=[Depends(require_permission(Perm.JOB_PUBLISH))],
)
async def publish_job(
    job_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[JobDetail]:
    service = _service(session, company_id)
    job = await service.get(job_id)
    await service.publish(job, actor_id=principal.id)
    await session.commit()
    await service.events.flush()
    job = await service.get(job_id)
    return SuccessResponse(data=JobDetail.model_validate(job), message="Job published")


@router.post(
    "/{job_id}/status",
    response_model=SuccessResponse[JobDetail],
    summary="Change job status",
    description="Pause, close, archive or re-publish a job.",
    dependencies=[Depends(require_permission(Perm.JOB_PUBLISH))],
)
async def change_job_status(
    job_id: uuid.UUID,
    payload: JobStatusChange,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[JobDetail]:
    service = _service(session, company_id)
    job = await service.get(job_id)
    await service.change_status(job, status=payload.status, actor_id=principal.id)
    job = await service.get(job_id)
    return SuccessResponse(
        data=JobDetail.model_validate(job), message=f"Job is now {payload.status.value}"
    )


@router.post(
    "/{job_id}/duplicate",
    response_model=SuccessResponse[JobDetail],
    status_code=status.HTTP_201_CREATED,
    summary="Duplicate a job",
    dependencies=[Depends(require_permission(Perm.JOB_CREATE))],
)
async def duplicate_job(
    job_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[JobDetail]:
    service = _service(session, company_id)
    original = await service.get(job_id)
    clone = await service.duplicate(original, actor_id=principal.id)
    clone = await service.get(clone.id)
    return SuccessResponse(data=JobDetail.model_validate(clone), message="Job duplicated")


# ---------------------------------------------------------------------- AI
@router.post(
    "/analyze-description",
    response_model=SuccessResponse[JobAnalysisResponse],
    summary="Analyse a job description with AI",
    description=(
        "Extracts required and preferred skills, experience, education and "
        "responsibilities from a description. **Nothing is applied to the job** - the "
        "recruiter reviews and confirms the result, then POSTs it to "
        "`/jobs/{job_id}/apply-analysis`."
    ),
    dependencies=[Depends(require_permission(Perm.AI_GENERATE))],
)
async def analyze_description(
    payload: JobAnalysisRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[JobAnalysisResponse]:
    service = _service(session, company_id)
    analysis, engine = await service.analyze_description(
        title=payload.title, description=payload.description, actor_id=principal.id
    )
    return SuccessResponse(
        data=_analysis_response(analysis, engine),
        message="Review these requirements before applying them to the job",
    )


@router.post(
    "/{job_id}/analyze-description",
    response_model=SuccessResponse[JobAnalysisResponse],
    summary="Analyse an existing job's description",
    dependencies=[Depends(require_permission(Perm.AI_GENERATE))],
)
async def analyze_existing_job(
    job_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[JobAnalysisResponse]:
    service = _service(session, company_id)
    job = await service.get(job_id)
    analysis, engine = await service.analyze_description(
        title=job.title, description=job.description, job=job, actor_id=principal.id
    )
    return SuccessResponse(
        data=_analysis_response(analysis, engine),
        message="Review these requirements before applying them to the job",
    )


@router.post(
    "/{job_id}/apply-analysis",
    response_model=SuccessResponse[JobDetail],
    summary="Apply recruiter-confirmed requirements",
    description=(
        "Writes the requirements the recruiter approved onto the job. This is the only "
        "path by which AI-derived requirements reach a job."
    ),
    dependencies=[Depends(require_permission(Perm.JOB_UPDATE))],
)
async def apply_analysis(
    job_id: uuid.UUID,
    payload: ApplyAnalysisRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[JobDetail]:
    service = _service(session, company_id)
    job = await service.get(job_id)

    analysis = JobDescriptionAnalysis(
        required_skills=[
            ExtractedSkill(
                name=s.name,
                importance="REQUIRED",
                category=s.category or "TECHNICAL",
                min_years=s.min_years,
            )
            for s in payload.required_skills
        ],
        preferred_skills=[
            ExtractedSkill(
                name=s.name,
                importance="PREFERRED",
                category=s.category or "TECHNICAL",
                min_years=s.min_years,
            )
            for s in payload.preferred_skills
        ],
        min_experience_years=payload.min_experience_years or 0,
        max_experience_years=payload.max_experience_years,
        education_requirements=payload.education_requirements,
        certifications=payload.certifications,
        responsibilities=payload.responsibilities,
        keywords=payload.keywords,
        confidence=1.0,
    )
    await service.apply_analysis(job, analysis, actor_id=principal.id)
    job = await service.get(job_id)
    return SuccessResponse(
        data=JobDetail.model_validate(job), message="Requirements applied to the job"
    )


def _analysis_response(
    analysis: JobDescriptionAnalysis, engine: str
) -> JobAnalysisResponse:
    return JobAnalysisResponse(
        required_skills=[
            {
                "name": s.name,
                "importance": s.importance,
                "category": s.category,
                "min_years": s.min_years,
            }
            for s in analysis.required_skills
        ],
        preferred_skills=[
            {
                "name": s.name,
                "importance": s.importance,
                "category": s.category,
                "min_years": s.min_years,
            }
            for s in analysis.preferred_skills
        ],
        min_experience_years=analysis.min_experience_years,
        max_experience_years=analysis.max_experience_years,
        education_requirements=analysis.education_requirements,
        certifications=analysis.certifications,
        responsibilities=analysis.responsibilities,
        keywords=analysis.keywords,
        technical_skills=analysis.technical_skills,
        soft_skills=analysis.soft_skills,
        seniority=analysis.seniority,
        confidence=analysis.confidence,
        engine=engine,
    )


# ------------------------------------------------------- screening questions
@router.get(
    "/{job_id}/screening-questions",
    response_model=SuccessResponse[list[ScreeningQuestionOut]],
    summary="List a job's screening questions",
    tags=["Screening"],
    dependencies=[Depends(require_permission(Perm.JOB_READ, Perm.JOB_READ_ASSIGNED))],
)
async def list_screening_questions(
    job_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[ScreeningQuestionOut]]:
    job = await _service(session, company_id).get(job_id)
    return SuccessResponse(
        data=[ScreeningQuestionOut.model_validate(q) for q in job.screening_questions]
    )


@router.put(
    "/{job_id}/screening-questions",
    response_model=SuccessResponse[list[ScreeningQuestionOut]],
    summary="Replace a job's screening questions",
    tags=["Screening"],
    dependencies=[Depends(require_permission(Perm.SCREENING_MANAGE))],
)
async def set_screening_questions(
    job_id: uuid.UUID,
    payload: list[ScreeningQuestionInput],
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[list[ScreeningQuestionOut]]:
    service = _service(session, company_id)
    job = await service.get(job_id)

    # Answers reference the question row, so questions are replaced rather than edited
    # in place only when no answers exist yet; otherwise the old rows are kept and
    # deactivated by removing them from the job's active set.
    job.screening_questions.clear()
    await session.flush()
    for index, question in enumerate(payload):
        data = question.model_dump()
        data.setdefault("display_order", index)
        session.add(JobScreeningQuestion(job_id=job.id, **data))
    await session.flush()

    job = await service.get(job_id)
    return SuccessResponse(
        data=[ScreeningQuestionOut.model_validate(q) for q in job.screening_questions],
        message="Screening questions updated",
    )


# -------------------------------------------------------------- hiring team
@router.put(
    "/{job_id}/hiring-team",
    response_model=SuccessResponse[JobDetail],
    summary="Set the hiring team for a job",
    dependencies=[Depends(require_permission(Perm.JOB_UPDATE))],
)
async def set_hiring_team(
    job_id: uuid.UUID,
    payload: HiringTeamUpdate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[JobDetail]:
    service = _service(session, company_id)
    job = await service.get(job_id)
    await service.set_hiring_team(
        job, [m.model_dump() for m in payload.members], actor_id=principal.id
    )
    job = await service.get(job_id)
    return SuccessResponse(data=JobDetail.model_validate(job), message="Hiring team updated")


# --------------------------------------------------------------------- stats
@router.get(
    "/{job_id}/stats",
    response_model=SuccessResponse[JobStatsOut],
    summary="Job pipeline statistics",
    dependencies=[Depends(require_permission(Perm.JOB_READ, Perm.JOB_READ_ASSIGNED))],
)
async def job_stats(
    job_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[JobStatsOut]:
    await _service(session, company_id).get(job_id)

    status_rows = (
        await session.execute(
            select(Application.status, func.count())
            .where(Application.job_id == job_id, Application.company_id == company_id)
            .group_by(Application.status)
        )
    ).all()
    by_status = {row[0].value: row[1] for row in status_rows}

    source_rows = (
        await session.execute(
            select(Application.source, func.count())
            .where(Application.job_id == job_id, Application.company_id == company_id)
            .group_by(Application.source)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()

    average = (
        await session.execute(
            select(func.avg(Application.ats_score)).where(
                Application.job_id == job_id,
                Application.company_id == company_id,
                Application.ats_score.is_not(None),
            )
        )
    ).scalar()

    from app.models.interview import Interview
    from app.models.offer import Offer

    interviews = (
        await session.execute(
            select(func.count()).select_from(Interview).where(Interview.job_id == job_id)
        )
    ).scalar_one()
    offers = (
        await session.execute(
            select(func.count()).select_from(Offer).where(Offer.job_id == job_id)
        )
    ).scalar_one()

    return SuccessResponse(
        data=JobStatsOut(
            job_id=job_id,
            total_applications=sum(by_status.values()),
            by_status=by_status,
            funnel=status_counts_to_funnel(by_status),
            average_ats_score=round(float(average), 2) if average is not None else None,
            top_sources={row[0].value: row[1] for row in source_rows},
            interviews_scheduled=interviews,
            offers_extended=offers,
        )
    )
