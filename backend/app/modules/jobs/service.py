"""Job lifecycle: creation, AI requirement analysis, publication and search."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import (
    AuditAction,
    EmploymentType,
    JobStatus,
    SkillImportance,
    WorkMode,
)
from app.core.exceptions import BusinessRuleError, ResourceNotFound, ValidationError
from app.core.logging import get_logger
from app.models.job import Job, JobHiringTeamMember, JobScreeningQuestion, JobSkill
from app.providers.ai.base import AIProvider
from app.providers.ai.factory import get_ai_provider
from app.providers.ai.schemas import JobDescriptionAnalysis
from app.services.audit import AuditService
from app.services.events import DomainEvent, EventCollector, Events
from app.utils.skills import categorise_skill, display_skill, normalise_skill
from app.utils.text import slugify

logger = get_logger(__name__)


def generate_reference(department: str | None = None) -> str:
    prefix = (department or "JOB")[:3].upper().replace(" ", "")
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return f"{prefix or 'JOB'}-{datetime.now(UTC).year}-{''.join(secrets.choice(alphabet) for _ in range(4))}"


class JobService:
    def __init__(
        self,
        session: AsyncSession,
        company_id: uuid.UUID,
        *,
        ai_provider: AIProvider | None = None,
    ) -> None:
        self.session = session
        self.company_id = company_id
        self.ai = ai_provider or get_ai_provider()
        self.audit = AuditService(session)
        self.events = EventCollector()

    # --------------------------------------------------------------- reads
    def base_query(self) -> Select[tuple[Job]]:
        return (
            select(Job)
            .where(Job.company_id == self.company_id, Job.deleted_at.is_(None))
            .options(selectinload(Job.skills), selectinload(Job.hiring_team))
        )

    async def get(self, job_id: uuid.UUID) -> Job:
        stmt = self.base_query().where(Job.id == job_id).options(
            selectinload(Job.screening_questions)
        )
        job = (await self.session.execute(stmt)).unique().scalar_one_or_none()
        if job is None:
            raise ResourceNotFound("Job", job_id)
        return job

    async def search(
        self,
        *,
        query: str | None = None,
        status: list[JobStatus] | None = None,
        department_id: uuid.UUID | None = None,
        work_mode: list[WorkMode] | None = None,
        employment_type: list[EmploymentType] | None = None,
        location: str | None = None,
        hiring_manager_id: uuid.UUID | None = None,
        created_by_id: uuid.UUID | None = None,
        assigned_to_user_id: uuid.UUID | None = None,
        include_internal: bool = True,
        page: int = 1,
        page_size: int = 20,
        sort: str = "-created_at",
    ) -> tuple[list[Job], int]:
        stmt = self.base_query()

        if assigned_to_user_id is not None:
            # Restricts to jobs this user is actually on - the scoping a hiring manager
            # or interviewer gets when they hold only ``job:read:assigned``.
            stmt = stmt.where(
                or_(
                    Job.hiring_manager_id == assigned_to_user_id,
                    Job.created_by_id == assigned_to_user_id,
                    Job.id.in_(
                        select(JobHiringTeamMember.job_id).where(
                            JobHiringTeamMember.user_id == assigned_to_user_id
                        )
                    ),
                )
            )

        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    Job.title.ilike(pattern),
                    Job.description.ilike(pattern),
                    Job.reference_code.ilike(pattern),
                    Job.location_text.ilike(pattern),
                )
            )
        if status:
            stmt = stmt.where(Job.status.in_(status))
        if department_id:
            stmt = stmt.where(Job.department_id == department_id)
        if work_mode:
            stmt = stmt.where(Job.work_mode.in_(work_mode))
        if employment_type:
            stmt = stmt.where(Job.employment_type.in_(employment_type))
        if location:
            stmt = stmt.where(Job.location_text.ilike(f"%{location.strip()}%"))
        if hiring_manager_id:
            stmt = stmt.where(Job.hiring_manager_id == hiring_manager_id)
        if created_by_id:
            stmt = stmt.where(Job.created_by_id == created_by_id)
        if not include_internal:
            stmt = stmt.where(Job.is_internal_only.is_(False))

        total = (
            await self.session.execute(
                select(func.count()).select_from(stmt.order_by(None).subquery())
            )
        ).scalar_one()

        stmt = stmt.order_by(*_sort_expression(sort))
        rows = (
            (
                await self.session.execute(
                    stmt.limit(page_size).offset((page - 1) * page_size)
                )
            )
            .unique()
            .scalars()
            .all()
        )
        return list(rows), total

    async def visible_to(self, user_id: uuid.UUID, *, only_assigned: bool) -> Select[tuple[Job]]:
        """Restrict jobs to those a hiring manager / interviewer is actually on."""
        stmt = self.base_query()
        if not only_assigned:
            return stmt
        return stmt.where(
            or_(
                Job.hiring_manager_id == user_id,
                Job.created_by_id == user_id,
                Job.id.in_(
                    select(JobHiringTeamMember.job_id).where(
                        JobHiringTeamMember.user_id == user_id
                    )
                ),
            )
        )

    # -------------------------------------------------------------- writes
    async def create(
        self,
        *,
        title: str,
        description: str,
        created_by_id: uuid.UUID,
        department_id: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
        location_text: str | None = None,
        work_mode: WorkMode = WorkMode.ONSITE,
        employment_type: EmploymentType = EmploymentType.FULL_TIME,
        min_experience_years: float = 0,
        max_experience_years: float | None = None,
        salary_min: float | None = None,
        salary_max: float | None = None,
        salary_currency: str = "INR",
        show_salary: bool = True,
        openings: int = 1,
        responsibilities: list[str] | None = None,
        benefits: list[str] | None = None,
        education_requirements: list[str] | None = None,
        certifications: list[str] | None = None,
        required_skills: list[dict[str, Any]] | None = None,
        preferred_skills: list[dict[str, Any]] | None = None,
        application_deadline: date | None = None,
        hiring_manager_id: uuid.UUID | None = None,
        is_internal_only: bool = False,
        department_name: str | None = None,
    ) -> Job:
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            raise ValidationError("The minimum salary cannot exceed the maximum")
        if (
            max_experience_years is not None
            and max_experience_years < min_experience_years
        ):
            raise ValidationError("Maximum experience cannot be below the minimum")
        if application_deadline and application_deadline < date.today():
            raise ValidationError("The application deadline cannot be in the past")

        job = Job(
            company_id=self.company_id,
            title=title.strip(),
            slug=slugify(title),
            reference_code=generate_reference(department_name),
            description=description,
            department_id=department_id,
            location_id=location_id,
            location_text=location_text,
            work_mode=work_mode,
            employment_type=employment_type,
            min_experience_years=min_experience_years,
            max_experience_years=max_experience_years,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            show_salary=show_salary,
            openings=openings,
            responsibilities=responsibilities or [],
            benefits=benefits or [],
            education_requirements=education_requirements or [],
            certifications=certifications or [],
            application_deadline=application_deadline,
            hiring_manager_id=hiring_manager_id,
            created_by_id=created_by_id,
            is_internal_only=is_internal_only,
            status=JobStatus.DRAFT,
        )
        self.session.add(job)
        await self.session.flush()

        await self.set_skills(job, required_skills or [], preferred_skills or [])

        if hiring_manager_id:
            self.session.add(
                JobHiringTeamMember(
                    job_id=job.id, user_id=hiring_manager_id, team_role="MANAGER"
                )
            )
        self.session.add(
            JobHiringTeamMember(job_id=job.id, user_id=created_by_id, team_role="RECRUITER")
        )

        await self.audit.record(
            action=AuditAction.CREATE,
            entity_type="Job",
            entity_id=job.id,
            company_id=self.company_id,
            actor_id=created_by_id,
            summary=f"Created job '{job.title}' ({job.reference_code})",
        )
        await self.session.flush()
        logger.info("job_created", job_id=str(job.id), title=job.title)
        return job

    async def set_skills(
        self,
        job: Job,
        required: list[dict[str, Any]],
        preferred: list[dict[str, Any]],
    ) -> None:
        """Replace the job's skill requirements, de-duplicating by canonical name.

        Deletes by statement rather than ``job.skills.clear()``: on a newly created job
        the collection has never been loaded, and either clearing *or* assigning to it
        would make SQLAlchemy load it first to compute the delta - a lazy load that
        raises ``MissingGreenlet`` under the async session.

        ``set_committed_value`` then syncs the in-memory collection to what was actually
        written, with no I/O. Doing this at the end (rather than marking it empty up
        front) matters: the identity map would otherwise keep serving a stale empty list
        to the caller's subsequent read.
        """
        from sqlalchemy import delete
        from sqlalchemy.orm.attributes import set_committed_value

        await self.session.execute(delete(JobSkill).where(JobSkill.job_id == job.id))

        created: list[JobSkill] = []
        seen: set[str] = set()
        for group, importance in (
            (required, SkillImportance.REQUIRED),
            (preferred, SkillImportance.PREFERRED),
        ):
            for entry in group:
                raw_name = (entry.get("name") or "").strip()
                if not raw_name:
                    continue
                key = normalise_skill(raw_name)
                if not key or key in seen:
                    continue
                seen.add(key)
                weight = entry.get("weight", 3)
                skill = JobSkill(
                    job_id=job.id,
                    name=display_skill(raw_name),
                    normalised_name=key,
                    importance=importance,
                    weight=max(1, min(5, int(weight))),
                    min_years=entry.get("min_years"),
                    category=entry.get("category") or categorise_skill(raw_name),
                    source=entry.get("source", "MANUAL"),
                )
                self.session.add(skill)
                created.append(skill)

        set_committed_value(job, "skills", created)
        await self.session.flush()

    async def update(
        self, job: Job, *, actor_id: uuid.UUID, changes: dict[str, Any]
    ) -> Job:
        before = {
            field: getattr(job, field)
            for field in changes
            if hasattr(job, field)
        }

        for field, value in changes.items():
            if field in ("required_skills", "preferred_skills"):
                continue
            if hasattr(job, field) and value is not None:
                setattr(job, field, value)

        if "title" in changes and changes["title"]:
            job.slug = slugify(changes["title"])

        if "required_skills" in changes or "preferred_skills" in changes:
            await self.set_skills(
                job,
                changes.get("required_skills") or [],
                changes.get("preferred_skills") or [],
            )

        from app.services.audit import diff

        await self.audit.record(
            action=AuditAction.UPDATE,
            entity_type="Job",
            entity_id=job.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=f"Updated job '{job.title}'",
            changes=diff(before, {k: getattr(job, k, None) for k in before}),
        )
        await self.session.flush()
        return job

    async def publish(self, job: Job, *, actor_id: uuid.UUID) -> Job:
        if job.status == JobStatus.PUBLISHED:
            raise BusinessRuleError("This job is already published")
        if job.status in (JobStatus.CLOSED, JobStatus.ARCHIVED):
            raise BusinessRuleError(
                f"A {job.status.value.lower()} job cannot be published. Duplicate it instead."
            )

        problems: list[str] = []
        if len(job.description or "") < 100:
            problems.append("the description is too short (at least 100 characters)")
        if not job.skills:
            problems.append("no skills have been added, so ATS scoring cannot rank applicants")
        if not job.location_text and job.work_mode != WorkMode.REMOTE:
            problems.append("a location is required for on-site and hybrid roles")
        if problems:
            raise ValidationError(
                "This job is not ready to publish: " + "; ".join(problems),
                code="JOB_NOT_PUBLISHABLE",
                details={"problems": problems},
            )

        job.status = JobStatus.PUBLISHED
        job.published_at = job.published_at or datetime.now(UTC)
        await self.audit.record(
            action=AuditAction.STATUS_CHANGE,
            entity_type="Job",
            entity_id=job.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=f"Published job '{job.title}'",
            changes={"status": {"from": "DRAFT", "to": "PUBLISHED"}},
        )
        self.events.collect(
            DomainEvent(
                name=Events.JOB_PUBLISHED,
                company_id=self.company_id,
                entity_type="Job",
                entity_id=job.id,
                actor_id=actor_id,
                payload={"job_id": str(job.id), "job_title": job.title},
            )
        )
        await self.session.flush()
        logger.info("job_published", job_id=str(job.id))
        return job

    async def change_status(
        self, job: Job, *, status: JobStatus, actor_id: uuid.UUID
    ) -> Job:
        previous = job.status
        if previous == status:
            raise BusinessRuleError(f"This job is already {status.value.lower()}")

        job.status = status
        if status == JobStatus.CLOSED:
            job.closed_at = datetime.now(UTC)
        if status == JobStatus.PUBLISHED:
            job.published_at = job.published_at or datetime.now(UTC)

        await self.audit.record(
            action=AuditAction.STATUS_CHANGE,
            entity_type="Job",
            entity_id=job.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=f"Job '{job.title}' moved from {previous.value} to {status.value}",
            changes={"status": {"from": previous.value, "to": status.value}},
        )
        await self.session.flush()
        return job

    async def duplicate(self, job: Job, *, actor_id: uuid.UUID) -> Job:
        """Copy a job as a fresh draft, including skills and screening questions."""
        clone = Job(
            company_id=self.company_id,
            title=f"{job.title} (copy)",
            slug=slugify(f"{job.title}-copy"),
            reference_code=generate_reference(),
            description=job.description,
            department_id=job.department_id,
            location_id=job.location_id,
            location_text=job.location_text,
            work_mode=job.work_mode,
            employment_type=job.employment_type,
            min_experience_years=job.min_experience_years,
            max_experience_years=job.max_experience_years,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
            salary_currency=job.salary_currency,
            show_salary=job.show_salary,
            openings=job.openings,
            responsibilities=list(job.responsibilities),
            benefits=list(job.benefits),
            education_requirements=list(job.education_requirements),
            certifications=list(job.certifications),
            keywords=list(job.keywords),
            hiring_manager_id=job.hiring_manager_id,
            created_by_id=actor_id,
            is_internal_only=job.is_internal_only,
            ats_weight_profile_id=job.ats_weight_profile_id,
            ai_analysis=dict(job.ai_analysis or {}),
            status=JobStatus.DRAFT,
        )
        self.session.add(clone)
        await self.session.flush()

        for skill in job.skills:
            self.session.add(
                JobSkill(
                    job_id=clone.id,
                    name=skill.name,
                    normalised_name=skill.normalised_name,
                    importance=skill.importance,
                    weight=skill.weight,
                    min_years=skill.min_years,
                    category=skill.category,
                    source=skill.source,
                )
            )
        for question in job.screening_questions:
            self.session.add(
                JobScreeningQuestion(
                    job_id=clone.id,
                    question=question.question,
                    question_type=question.question_type,
                    options=list(question.options),
                    is_required=question.is_required,
                    display_order=question.display_order,
                    scoring=dict(question.scoring or {}),
                    is_knockout=question.is_knockout,
                )
            )
        self.session.add(
            JobHiringTeamMember(job_id=clone.id, user_id=actor_id, team_role="RECRUITER")
        )

        await self.audit.record(
            action=AuditAction.CREATE,
            entity_type="Job",
            entity_id=clone.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=f"Duplicated '{job.title}' into '{clone.title}'",
            meta={"source_job_id": str(job.id)},
        )
        await self.session.flush()
        return clone

    async def delete(self, job: Job, *, actor_id: uuid.UUID) -> None:
        if job.application_count:
            raise BusinessRuleError(
                f"This job has {job.application_count} application(s) and cannot be "
                "deleted. Archive it instead so the applications and their history "
                "remain available.",
                code="JOB_HAS_APPLICATIONS",
            )
        job.deleted_at = datetime.now(UTC)
        await self.audit.record(
            action=AuditAction.DELETE,
            entity_type="Job",
            entity_id=job.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=f"Deleted draft job '{job.title}'",
        )
        await self.session.flush()

    # ------------------------------------------------------------------ ai
    async def analyze_description(
        self,
        *,
        title: str,
        description: str,
        job: Job | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> tuple[JobDescriptionAnalysis, str]:
        """Extract requirements from a description for the recruiter to review.

        The result is *not* applied to the job. A recruiter confirms or edits it first
        (s8) - AI proposes, a human decides.
        """
        result = await self.ai.analyze_job_description(title=title, description=description)
        analysis: JobDescriptionAnalysis = result.value

        await self.audit.record_ai(
            feature="JD_ANALYSIS",
            engine=result.usage.engine,
            model=result.usage.model,
            company_id=self.company_id,
            user_id=actor_id,
            entity_type="Job",
            entity_id=job.id if job else None,
            input_digest={"title": title, "description_length": len(description)},
            output_summary={
                "required_skills": [s.name for s in analysis.required_skills][:20],
                "preferred_skills": [s.name for s in analysis.preferred_skills][:20],
                "min_experience_years": analysis.min_experience_years,
                "seniority": analysis.seniority,
            },
            confidence=analysis.confidence,
            latency_ms=result.usage.latency_ms,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            error=result.usage.error,
        )

        if job is not None:
            job.ai_analysis = {
                "engine": result.usage.engine,
                "generated_at": datetime.now(UTC).isoformat(),
                "confidence": analysis.confidence,
                "analysis": analysis.model_dump(),
            }
            await self.session.flush()

        logger.info(
            "jd_analysed",
            engine=result.usage.engine,
            required=len(analysis.required_skills),
            confidence=analysis.confidence,
        )
        return analysis, result.usage.engine

    async def apply_analysis(
        self,
        job: Job,
        analysis: JobDescriptionAnalysis,
        *,
        actor_id: uuid.UUID,
    ) -> Job:
        """Apply recruiter-confirmed AI requirements to a job."""
        await self.set_skills(
            job,
            [
                {
                    "name": s.name,
                    "category": s.category,
                    "min_years": s.min_years,
                    "source": "AI",
                }
                for s in analysis.required_skills
            ],
            [
                {
                    "name": s.name,
                    "category": s.category,
                    "min_years": s.min_years,
                    "source": "AI",
                }
                for s in analysis.preferred_skills
            ],
        )
        if analysis.responsibilities:
            job.responsibilities = analysis.responsibilities
        if analysis.education_requirements:
            job.education_requirements = analysis.education_requirements
        if analysis.certifications:
            job.certifications = analysis.certifications
        if analysis.keywords:
            job.keywords = analysis.keywords[:30]
        if analysis.min_experience_years:
            job.min_experience_years = analysis.min_experience_years
        if analysis.max_experience_years:
            job.max_experience_years = analysis.max_experience_years

        job.ai_analysis_confirmed_at = datetime.now(UTC)
        await self.audit.record(
            action=AuditAction.AI_DECISION_ASSIST,
            entity_type="Job",
            entity_id=job.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=f"Applied reviewed AI requirements to '{job.title}'",
            meta={
                "required_skills": len(analysis.required_skills),
                "preferred_skills": len(analysis.preferred_skills),
            },
        )
        await self.session.flush()
        return job

    # ------------------------------------------------------- hiring team
    async def set_hiring_team(
        self, job: Job, members: list[dict[str, Any]], *, actor_id: uuid.UUID
    ) -> Job:
        from sqlalchemy import delete
        from sqlalchemy.orm.attributes import set_committed_value

        await self.session.execute(
            delete(JobHiringTeamMember).where(JobHiringTeamMember.job_id == job.id)
        )
        created: list[JobHiringTeamMember] = []
        for member in members:
            row = JobHiringTeamMember(
                job_id=job.id,
                user_id=uuid.UUID(str(member["user_id"])),
                team_role=member.get("team_role", "INTERVIEWER"),
            )
            self.session.add(row)
            created.append(row)
        set_committed_value(job, "hiring_team", created)
        await self.audit.record(
            action=AuditAction.UPDATE,
            entity_type="Job",
            entity_id=job.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=f"Updated the hiring team for '{job.title}'",
            meta={"members": len(members)},
        )
        await self.session.flush()
        return job


def _sort_expression(sort: str):
    """Map a ``?sort=`` value onto ORDER BY columns, defaulting safely."""
    descending = sort.startswith("-")
    field = sort.lstrip("-")
    column = {
        "created_at": Job.created_at,
        "published_at": Job.published_at,
        "title": Job.title,
        "applications": Job.application_count,
        "deadline": Job.application_deadline,
        "views": Job.view_count,
    }.get(field, Job.created_at)
    return (column.desc().nullslast(), Job.id) if descending else (column.asc().nullslast(), Job.id)


def public_job_query(*, include_internal: bool = False) -> Select[tuple[Job]]:
    """Jobs visible on the public portal, across every company.

    The only query in the system that deliberately spans tenants - it is restricted to
    published, non-internal jobs and returns no company-private fields.
    """
    conditions = [
        Job.status == JobStatus.PUBLISHED,
        Job.deleted_at.is_(None),
        or_(Job.application_deadline.is_(None), Job.application_deadline >= date.today()),
    ]
    if not include_internal:
        conditions.append(Job.is_internal_only.is_(False))
    return (
        select(Job)
        .where(and_(*conditions))
        .options(selectinload(Job.skills), selectinload(Job.company))
    )
