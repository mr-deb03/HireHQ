"""Public job portal: browse, search and apply. No authentication required.

This is the only surface that queries across companies, and it is restricted to
published, non-internal jobs and to fields a company has chosen to make public.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.enums import ApplicationStatus, EmailTemplateKey, SkillImportance
from app.core.exceptions import ResourceNotFound, ValidationError
from app.core.logging import get_logger
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import OptionalUser
from app.models.application import Application
from app.models.company import Company
from app.models.job import Job, JobSkill
from app.modules.applications.schemas import ApplyRequest, ApplyResponse
from app.modules.applications.service import ApplicationIntakeService, resolve_source
from app.modules.jobs.schemas import (
    CompanyBrief,
    PublicJobDetail,
    PublicJobSummary,
    ScreeningQuestionOut,
)
from app.modules.jobs.service import public_job_query
from app.modules.screening.service import ScreeningService
from app.schemas.common import PaginationParams, pagination
from app.utils.skills import normalise_skill

logger = get_logger(__name__)

router = APIRouter(prefix="/public", tags=["Public"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _to_summary(job: Job) -> PublicJobSummary:
    payload = PublicJobSummary.model_validate(job)
    payload.company = CompanyBrief.model_validate(job.company) if job.company else None
    payload.required_skills = [
        s.name for s in job.skills if s.importance == SkillImportance.REQUIRED
    ][:12]
    if not job.show_salary:
        payload.salary_min = payload.salary_max = None
    return payload


@router.get(
    "/jobs",
    response_model=SuccessResponse[Page[PublicJobSummary]],
    summary="Search public job listings",
    description=(
        "Browse every published job across the platform. Supports keyword, location, "
        "experience, salary, employment-type, work-mode and skill filters."
    ),
)
async def list_public_jobs(
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    q: Annotated[str | None, Query(description="Keyword: title, description or skill")] = None,
    location: str | None = None,
    remote: Annotated[bool | None, Query(description="Only fully remote roles")] = None,
    work_mode: Annotated[list[str] | None, Query()] = None,
    employment_type: Annotated[list[str] | None, Query()] = None,
    min_experience: Annotated[float | None, Query(ge=0, le=50)] = None,
    max_experience: Annotated[float | None, Query(ge=0, le=50)] = None,
    min_salary: Annotated[float | None, Query(ge=0)] = None,
    skills: Annotated[list[str] | None, Query(description="Any of these skills")] = None,
    company_slug: str | None = None,
    industry: str | None = None,
    sort: Annotated[str, Query(description="-published_at | -created_at | title")] = "-published_at",
) -> SuccessResponse[Page[PublicJobSummary]]:
    stmt = public_job_query()

    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Job.title.ilike(pattern),
                Job.description.ilike(pattern),
                Job.id.in_(
                    select(JobSkill.job_id).where(JobSkill.normalised_name.ilike(pattern))
                ),
            )
        )
    if location:
        stmt = stmt.where(Job.location_text.ilike(f"%{location.strip()}%"))
    if remote:
        stmt = stmt.where(Job.work_mode == "REMOTE")
    if work_mode:
        stmt = stmt.where(Job.work_mode.in_([w.upper() for w in work_mode]))
    if employment_type:
        stmt = stmt.where(Job.employment_type.in_([e.upper() for e in employment_type]))
    if min_experience is not None:
        stmt = stmt.where(Job.min_experience_years >= min_experience)
    if max_experience is not None:
        stmt = stmt.where(Job.min_experience_years <= max_experience)
    if min_salary is not None:
        # Compare against the top of the band: a role paying 8-12L satisfies "at least 10L".
        stmt = stmt.where(Job.salary_max >= min_salary)
    if skills:
        keys = [normalise_skill(s) for s in skills if normalise_skill(s)]
        if keys:
            stmt = stmt.where(
                Job.id.in_(
                    select(JobSkill.job_id).where(JobSkill.normalised_name.in_(keys))
                )
            )
    if company_slug or industry:
        stmt = stmt.join(Company, Company.id == Job.company_id)
        if company_slug:
            stmt = stmt.where(Company.slug == company_slug)
        if industry:
            stmt = stmt.where(Company.industry.ilike(f"%{industry}%"))

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()

    descending = sort.startswith("-")
    column = {
        "published_at": Job.published_at,
        "created_at": Job.created_at,
        "title": Job.title,
    }.get(sort.lstrip("-"), Job.published_at)
    stmt = stmt.order_by(
        column.desc().nullslast() if descending else column.asc().nullslast(), Job.id
    )

    rows = (
        (await session.execute(stmt.limit(page_params.page_size).offset(page_params.offset)))
        .unique()
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=Page.build(
            [_to_summary(j) for j in rows],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


@router.get(
    "/jobs/{job_id}",
    response_model=SuccessResponse[PublicJobDetail],
    summary="Get a public job",
    description=(
        "Returns full job details plus its screening questions. Pass `?source=` to "
        "attribute the visit - the value is carried through to the application."
    ),
)
async def get_public_job(
    job_id: uuid.UUID,
    session: DbSession,
    viewer: OptionalUser,
    source: Annotated[str | None, Query(description="e.g. linkedin, instagram, referral")] = None,
) -> SuccessResponse[PublicJobDetail]:
    job = (
        (
            await session.execute(
                public_job_query()
                .where(Job.id == job_id)
                .options(selectinload(Job.screening_questions))
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if job is None:
        raise ResourceNotFound("Job", job_id)

    job.view_count = (job.view_count or 0) + 1

    payload = PublicJobDetail.model_validate(job)
    payload.company = CompanyBrief.model_validate(job.company) if job.company else None
    payload.required_skills = [
        s.name for s in job.skills if s.importance == SkillImportance.REQUIRED
    ]
    payload.preferred_skills = [
        s.name for s in job.skills if s.importance == SkillImportance.PREFERRED
    ]
    payload.screening_questions = [
        ScreeningQuestionOut.model_validate(q) for q in job.screening_questions
    ]
    if not job.show_salary:
        payload.salary_min = payload.salary_max = None

    # Tell a signed-in candidate whether they have already applied, so the UI can show
    # "View your application" instead of an apply button that will fail.
    if viewer is not None:
        from app.models.candidate import Candidate

        existing = await session.scalar(
            select(Application)
            .join(Candidate, Candidate.id == Application.candidate_id)
            .where(Application.job_id == job.id, Candidate.user_id == viewer.id)
        )
        if existing is not None:
            payload.already_applied = True
            payload.existing_application_id = existing.id

    return SuccessResponse(data=payload)


@router.get(
    "/companies/{slug}",
    response_model=SuccessResponse[dict],
    summary="Public company profile with open roles",
)
async def public_company(slug: str, session: DbSession) -> SuccessResponse[dict]:
    company = await session.scalar(
        select(Company).where(Company.slug == slug, Company.deleted_at.is_(None))
    )
    if company is None:
        raise ResourceNotFound("Company", slug)

    jobs = (
        (
            await session.execute(
                public_job_query()
                .where(Job.company_id == company.id)
                .order_by(Job.published_at.desc().nullslast())
                .limit(50)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    return SuccessResponse(
        data={
            "company": {
                "id": str(company.id),
                "name": company.name,
                "slug": company.slug,
                "description": company.description,
                "logo_url": company.logo_url,
                "website": company.website,
                "industry": company.industry,
                "size": company.size.value if company.size else None,
                "headquarters": company.headquarters,
            },
            "open_roles": [_to_summary(j).model_dump() for j in jobs],
            "open_role_count": len(jobs),
        }
    )


@router.post(
    "/jobs/{job_id}/apply",
    response_model=SuccessResponse[ApplyResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Apply for a job",
    description=(
        "Submits the multi-step application as `multipart/form-data`:\n\n"
        "- `application` - JSON matching the `ApplyRequest` schema\n"
        "- `resume` - the candidate's PDF or DOCX (optional but strongly recommended)\n\n"
        "The resume is validated, scanned and stored synchronously so the response is "
        "honest about acceptance. Parsing and ATS scoring then run in the background."
    ),
)
async def apply_for_job(
    job_id: uuid.UUID,
    request: Request,
    session: DbSession,
    viewer: OptionalUser,
    application: Annotated[str, Form(description="JSON body matching ApplyRequest")],
    resume: Annotated[UploadFile | None, File(description="PDF or DOCX resume")] = None,
    source: Annotated[str | None, Query()] = None,
) -> SuccessResponse[ApplyResponse]:
    try:
        payload = ApplyRequest.model_validate_json(application)
    except Exception as exc:
        raise ValidationError(
            "The application payload is not valid JSON matching the expected schema",
            details={"detail": str(exc)[:500]},
        ) from exc

    job = (
        (await session.execute(public_job_query(include_internal=True).where(Job.id == job_id)))
        .unique()
        .scalar_one_or_none()
    )
    if job is None:
        raise ResourceNotFound("Job", job_id)
    if job.is_internal_only:
        raise ValidationError(
            "This is an internal opening. Please apply from the internal careers page.",
            code="INTERNAL_JOB",
        )

    company_id = job.company_id
    intake = ApplicationIntakeService(session, company_id)

    resolved_source, source_detail = await resolve_source(
        source or request.query_params.get("utm_source")
    )
    utm = {
        key: value
        for key, value in request.query_params.items()
        if key.startswith("utm_")
    }

    candidate, _created = await intake.find_or_create_candidate(
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
        user_id=viewer.id if viewer else None,
        location=payload.location,
        source=resolved_source.value,
        extra={
            "current_designation": payload.current_designation,
            "current_company": payload.current_company,
            "total_experience_years": payload.total_experience_years or 0,
            "expected_salary": payload.expected_salary,
            "notice_period_days": payload.notice_period_days,
            "linkedin_url": payload.linkedin_url,
            "github_url": payload.github_url,
            "portfolio_url": payload.portfolio_url,
        },
    )

    new_application = await intake.create_application(
        job=job,
        candidate=candidate,
        source=resolved_source,
        source_detail=source_detail,
        utm=utm,
        cover_letter=payload.cover_letter,
        expected_salary=payload.expected_salary,
        notice_period_days=payload.notice_period_days,
        consent_given=payload.consent_given,
        actor_id=viewer.id if viewer else None,
    )

    # Screening answers are recorded and scored, but never used to auto-reject.
    if payload.screening_answers:
        screening = ScreeningService(session, company_id)
        await screening.record_answers(
            application=new_application,
            job=job,
            answers=[a.model_dump() for a in payload.screening_answers],
        )

    # Optional education from the form, when the candidate has no history on file.
    if payload.highest_qualification and not candidate.education:
        from app.models.candidate import CandidateEducation

        session.add(
            CandidateEducation(
                candidate_id=candidate.id,
                degree=payload.highest_qualification[:200],
                institution=payload.institution,
                end_year=payload.graduation_year,
                source="MANUAL",
            )
        )

    resume_uploaded = False
    resume_id: uuid.UUID | None = None
    if resume is not None and resume.filename:
        from app.modules.resumes.service import ResumeService

        content = await resume.read()
        if content:
            resume_service = ResumeService(session, company_id)
            # Validation/scan failures raise, so an accepted response always means the
            # file really was accepted and stored.
            stored_resume = await resume_service.upload(
                candidate=candidate, filename=resume.filename, content=content
            )
            new_application.resume_id = stored_resume.id
            resume_id = stored_resume.id
            resume_uploaded = True

    await intake.refresh_verification_signals(candidate)
    await session.flush()

    reference = new_application.reference_code
    application_id = new_application.id
    candidate_id = candidate.id

    # Commit before queueing so background work never races an uncommitted row.
    await session.commit()
    await intake.events.flush()

    from app.workers.queue import get_queue

    queue = get_queue()
    if resume_id is not None:
        await queue.enqueue(
            "process_resume",
            resume_id=str(resume_id),
            company_id=str(company_id),
            application_id=str(application_id),
        )
    else:
        # No resume: still score on the profile the candidate typed in.
        await queue.enqueue(
            "score_application",
            application_id=str(application_id),
            company_id=str(company_id),
        )

    # A receipt email, sent honestly - the response reports what actually happened.
    from app.modules.emails.service import EmailService

    email_service = EmailService(session, company_id)
    company = await session.get(Company, company_id)
    variables = EmailService.build_variables(
        candidate=candidate, job=job, application=new_application, company=company
    )
    await email_service.send_templated(
        key=EmailTemplateKey.APPLICATION_RECEIVED,
        to=[candidate.email],
        variables=variables,
        application_id=application_id,
        candidate_id=candidate_id,
        job_id=job.id,
        is_automated=True,
    )
    await session.commit()

    logger.info(
        "public_application_submitted",
        application_id=str(application_id),
        job_id=str(job.id),
        source=resolved_source.value,
        resume=resume_uploaded,
    )

    return SuccessResponse(
        data=ApplyResponse(
            application_id=application_id,
            reference_code=reference,
            status=ApplicationStatus.APPLIED,
            candidate_id=candidate_id,
            resume_uploaded=resume_uploaded,
            processing_queued=True,
            message=(
                "Your application has been received. We are processing your resume and "
                "will be in touch."
            ),
            track_url=f"{settings.FRONTEND_BASE_URL}/candidate/applications/{application_id}",
        ),
        message="Application submitted",
    )


@router.get(
    "/track/{reference_code}",
    response_model=SuccessResponse[dict],
    summary="Track an application by reference",
    description=(
        "Lets a candidate check progress with their reference code and email. Returns "
        "only the candidate-facing status - never internal notes, scores or feedback."
    ),
)
async def track_application(
    reference_code: str,
    email: Annotated[str, Query(description="The email used to apply")],
    session: DbSession,
) -> SuccessResponse[dict]:
    from app.models.candidate import Candidate
    from app.modules.applications.state_machine import candidate_label

    application = (
        (
            await session.execute(
                select(Application)
                .join(Candidate, Candidate.id == Application.candidate_id)
                .where(
                    Application.reference_code == reference_code.strip().upper(),
                    func.lower(Candidate.email) == email.strip().lower(),
                )
                .options(selectinload(Application.job), selectinload(Application.candidate))
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if application is None:
        # Same response whether the reference is wrong or the email does not match, so
        # this cannot be used to probe for valid references.
        raise ResourceNotFound("Application", reference_code)

    from app.modules.applications.service import ApplicationPipelineService

    service = ApplicationPipelineService(session, application.company_id)
    timeline = await service.get_timeline(application.id, candidate_view=True)
    company = await session.get(Company, application.company_id)

    return SuccessResponse(
        data={
            "reference_code": application.reference_code,
            "status": candidate_label(application.status),
            "job_title": application.job.title if application.job else None,
            "company_name": company.name if company else None,
            "applied_at": application.created_at.isoformat(),
            "last_updated": (
                application.status_changed_at or application.updated_at
            ).isoformat(),
            "timeline": [
                {
                    "title": event.title,
                    "at": event.created_at.isoformat(),
                    "description": event.description,
                }
                for event in timeline
            ],
        }
    )


@router.get(
    "/filters",
    response_model=SuccessResponse[dict],
    summary="Available filter values for the job portal",
    description="Powers the search sidebar without the client hard-coding option lists.",
)
async def portal_filters(session: DbSession) -> SuccessResponse[dict]:
    from app.core.enums import EmploymentType, WorkMode

    locations = (
        (
            await session.execute(
                select(Job.location_text, func.count())
                .where(Job.status == "PUBLISHED", Job.location_text.is_not(None))
                .group_by(Job.location_text)
                .order_by(func.count().desc())
                .limit(30)
            )
        )
        .all()
    )
    top_skills = (
        (
            await session.execute(
                select(JobSkill.name, func.count())
                .join(Job, Job.id == JobSkill.job_id)
                .where(Job.status == "PUBLISHED")
                .group_by(JobSkill.name)
                .order_by(func.count().desc())
                .limit(40)
            )
        )
        .all()
    )
    industries = (
        (
            await session.execute(
                select(Company.industry, func.count())
                .join(Job, Job.company_id == Company.id)
                .where(Job.status == "PUBLISHED", Company.industry.is_not(None))
                .group_by(Company.industry)
                .order_by(func.count().desc())
                .limit(20)
            )
        )
        .all()
    )

    return SuccessResponse(
        data={
            "locations": [{"value": row[0], "count": row[1]} for row in locations],
            "skills": [{"value": row[0], "count": row[1]} for row in top_skills],
            "industries": [{"value": row[0], "count": row[1]} for row in industries],
            "work_modes": [w.value for w in WorkMode],
            "employment_types": [e.value for e in EmploymentType],
            "experience_bands": [
                {"label": "Fresher (0-1 years)", "min": 0, "max": 1},
                {"label": "1-3 years", "min": 1, "max": 3},
                {"label": "3-5 years", "min": 3, "max": 5},
                {"label": "5-8 years", "min": 5, "max": 8},
                {"label": "8+ years", "min": 8, "max": None},
            ],
        }
    )
