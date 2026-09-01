"""Tools the recruiter assistant may call.

Each tool is a small, typed function bound to *one* caller's session, company and
permission set at construction time. The model never receives database access, a query
language, or an unbounded surface - only these functions, already scoped. That is what
makes "every AI action respects RBAC" (s41) a structural property rather than a prompt
instruction the model might ignore.

Every tool also caps its own result size, so a question like "list all candidates" cannot
pull a hundred thousand rows into a prompt.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import ApplicationStatus, InterviewStatus, JobStatus
from app.core.permissions import Perm
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.interview import Interview, InterviewFeedback
from app.models.job import Job
from app.providers.ai.base import AssistantTool

MAX_ROWS = 25


class AssistantToolkit:
    """Builds the tool list for one authenticated caller."""

    def __init__(self, session: AsyncSession, principal: Any) -> None:
        self.session = session
        self.principal = principal
        self.company_id = principal.company_id

    # ------------------------------------------------------------- helpers
    def _applications(self):
        return select(Application).where(Application.company_id == self.company_id)

    async def _resolve_job(self, job_title: str | None) -> Job | None:
        if not job_title:
            return None
        pattern = f"%{job_title.strip()}%"
        return await self.session.scalar(
            select(Job)
            .where(
                Job.company_id == self.company_id,
                Job.deleted_at.is_(None),
                or_(Job.title.ilike(pattern), Job.reference_code.ilike(pattern)),
            )
            .order_by(Job.published_at.desc().nullslast())
            .limit(1)
        )

    # --------------------------------------------------------------- tools
    async def list_top_candidates(
        self, job_title: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), MAX_ROWS))
        stmt = (
            self._applications()
            .where(Application.ats_score.is_not(None))
            .options(selectinload(Application.candidate), selectinload(Application.job))
            .order_by(Application.ats_score.desc())
            .limit(limit)
        )
        job = await self._resolve_job(job_title)
        if job_title and job is None:
            return {"items": [], "total": 0, "note": f"No job matching '{job_title}' was found."}
        if job is not None:
            stmt = stmt.where(Application.job_id == job.id)

        rows = (await self.session.execute(stmt)).unique().scalars().all()
        return {
            "job": job.title if job else "all jobs",
            "total": len(rows),
            "items": [
                {
                    "label": f"{a.candidate.full_name} - {float(a.ats_score):.0f}%",
                    "candidate_id": str(a.candidate_id),
                    "application_id": str(a.id),
                    "name": a.candidate.full_name,
                    "ats_score": float(a.ats_score),
                    "rank": a.ats_rank,
                    "status": a.status.value,
                    "experience_years": float(a.candidate.total_experience_years or 0),
                    "current_designation": a.candidate.current_designation,
                    "job_title": a.job.title if a.job else None,
                }
                for a in rows
            ],
        }

    async def search_candidates(
        self,
        job_title: str | None = None,
        min_ats_score: float | None = None,
        skills: list[str] | None = None,
        min_experience: float | None = None,
        status: str | None = None,
        limit: int = 15,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), MAX_ROWS))
        stmt = self._applications().options(
            selectinload(Application.candidate), selectinload(Application.job)
        )

        job = await self._resolve_job(job_title)
        if job is not None:
            stmt = stmt.where(Application.job_id == job.id)
        if min_ats_score is not None:
            stmt = stmt.where(Application.ats_score >= float(min_ats_score))
        if min_experience is not None:
            stmt = stmt.join(
                Candidate, Candidate.id == Application.candidate_id
            ).where(Candidate.total_experience_years >= float(min_experience))
        if status:
            try:
                stmt = stmt.where(Application.status == ApplicationStatus(status.upper()))
            except ValueError:
                return {"items": [], "total": 0, "note": f"'{status}' is not a valid status."}
        if skills:
            from app.models.candidate import CandidateSkill
            from app.utils.skills import normalise_skill

            keys = [normalise_skill(s) for s in skills if normalise_skill(s)]
            if keys:
                stmt = stmt.where(
                    Application.candidate_id.in_(
                        select(CandidateSkill.candidate_id).where(
                            CandidateSkill.normalised_name.in_(keys)
                        )
                    )
                )

        total = (
            await self.session.execute(
                select(func.count()).select_from(stmt.order_by(None).subquery())
            )
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(Application.ats_score.desc().nullslast()).limit(limit)
                )
            )
            .unique()
            .scalars()
            .all()
        )
        return {
            "total": total,
            "showing": len(rows),
            "items": [
                {
                    "label": f"{a.candidate.full_name} ({a.status.value})",
                    "candidate_id": str(a.candidate_id),
                    "name": a.candidate.full_name,
                    "ats_score": float(a.ats_score) if a.ats_score is not None else None,
                    "status": a.status.value,
                    "job_title": a.job.title if a.job else None,
                    "experience_years": float(a.candidate.total_experience_years or 0),
                }
                for a in rows
            ],
        }

    async def count_applications(self, period: str = "all") -> dict[str, Any]:
        stmt = select(func.count()).select_from(Application).where(
            Application.company_id == self.company_id
        )
        now = datetime.now(UTC)
        if period == "week":
            stmt = stmt.where(Application.created_at >= now - timedelta(days=7))
        elif period == "month":
            stmt = stmt.where(Application.created_at >= now - timedelta(days=30))
        elif period == "today":
            stmt = stmt.where(
                Application.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0)
            )
        count = (await self.session.execute(stmt)).scalar_one()
        return {"count": count, "period": period}

    async def pipeline_overview(self, job_title: str | None = None) -> dict[str, Any]:
        stmt = (
            select(Application.status, func.count())
            .where(Application.company_id == self.company_id)
            .group_by(Application.status)
        )
        job = await self._resolve_job(job_title)
        if job is not None:
            stmt = stmt.where(Application.job_id == job.id)

        rows = (await self.session.execute(stmt)).all()
        stages = {row[0].value: row[1] for row in rows}

        from app.modules.applications.service import status_counts_to_funnel

        return {
            "job": job.title if job else "all jobs",
            "stages": stages,
            "funnel": status_counts_to_funnel(stages),
            "total": sum(stages.values()),
        }

    async def list_pending_feedback(self, limit: int = 15) -> dict[str, Any]:
        limit = max(1, min(int(limit), MAX_ROWS))
        stmt = (
            select(Interview)
            .outerjoin(
                InterviewFeedback,
                (InterviewFeedback.interview_id == Interview.id)
                & (InterviewFeedback.is_draft.is_(False)),
            )
            .where(
                Interview.company_id == self.company_id,
                Interview.status == InterviewStatus.COMPLETED,
                InterviewFeedback.id.is_(None),
            )
            .options(
                selectinload(Interview.application).selectinload(Application.candidate),
                selectinload(Interview.participants),
            )
            .order_by(Interview.scheduled_start.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).unique().scalars().all()
        return {
            "total": len(rows),
            "items": [
                {
                    "label": (
                        f"{i.application.candidate.full_name} - {i.title} "
                        f"({i.scheduled_start.strftime('%d %b')})"
                    ),
                    "interview_id": str(i.id),
                    "candidate_name": i.application.candidate.full_name,
                    "candidate_id": str(i.candidate_id),
                    "interview_title": i.title,
                    "held_on": i.scheduled_start.isoformat(),
                    "interviewer_count": len(i.participants),
                }
                for i in rows
            ],
        }

    async def list_todays_interviews(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return await self._interviews_between(start, start + timedelta(days=1))

    async def list_upcoming_interviews(self, days: int = 7) -> dict[str, Any]:
        now = datetime.now(UTC)
        return await self._interviews_between(now, now + timedelta(days=int(days)))

    async def _interviews_between(
        self, start: datetime, end: datetime
    ) -> dict[str, Any]:
        stmt = (
            select(Interview)
            .where(
                Interview.company_id == self.company_id,
                Interview.scheduled_start >= start,
                Interview.scheduled_start < end,
                Interview.status.in_(
                    [InterviewStatus.SCHEDULED, InterviewStatus.CONFIRMED]
                ),
            )
            .options(
                selectinload(Interview.application).selectinload(Application.candidate),
                selectinload(Interview.application).selectinload(Application.job),
            )
            .order_by(Interview.scheduled_start)
            .limit(MAX_ROWS)
        )
        # An interviewer only sees their own interviews.
        if not self.principal.has(Perm.INTERVIEW_READ):
            from app.models.interview import InterviewParticipant

            stmt = stmt.where(
                Interview.id.in_(
                    select(InterviewParticipant.interview_id).where(
                        InterviewParticipant.user_id == self.principal.id
                    )
                )
            )

        rows = (await self.session.execute(stmt)).unique().scalars().all()
        return {
            "total": len(rows),
            "items": [
                {
                    "label": (
                        f"{i.scheduled_start.strftime('%H:%M')} - "
                        f"{i.application.candidate.full_name} ({i.title})"
                    ),
                    "interview_id": str(i.id),
                    "starts_at": i.scheduled_start.isoformat(),
                    "candidate_name": i.application.candidate.full_name,
                    "job_title": i.application.job.title if i.application.job else None,
                    "interview_type": i.interview_type.value,
                    "meeting_link": i.meeting_link,
                }
                for i in rows
            ],
        }

    async def list_jobs(self, status: str | None = None, limit: int = 15) -> dict[str, Any]:
        limit = max(1, min(int(limit), MAX_ROWS))
        stmt = (
            select(Job)
            .where(Job.company_id == self.company_id, Job.deleted_at.is_(None))
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
        if status:
            try:
                stmt = stmt.where(Job.status == JobStatus(status.upper()))
            except ValueError:
                return {"items": [], "total": 0, "note": f"'{status}' is not a valid job status."}

        rows = (await self.session.execute(stmt)).unique().scalars().all()
        return {
            "total": len(rows),
            "items": [
                {
                    "label": f"{j.title} ({j.status.value}, {j.application_count} applications)",
                    "job_id": str(j.id),
                    "title": j.title,
                    "status": j.status.value,
                    "applications": j.application_count,
                    "openings": j.openings,
                    "location": j.location_text,
                }
                for j in rows
            ],
        }

    async def candidate_summary(self, candidate_name: str) -> dict[str, Any]:
        pattern = f"%{candidate_name.strip()}%"
        candidate = await self.session.scalar(
            select(Candidate)
            .where(
                Candidate.company_id == self.company_id,
                Candidate.deleted_at.is_(None),
                or_(
                    func.lower(Candidate.first_name + " " + Candidate.last_name).ilike(
                        pattern.lower()
                    ),
                    Candidate.email.ilike(pattern),
                ),
            )
            .options(
                selectinload(Candidate.skills), selectinload(Candidate.experience)
            )
            .limit(1)
        )
        if candidate is None:
            return {"found": False, "note": f"No candidate matching '{candidate_name}'."}

        applications = (
            (
                await self.session.execute(
                    self._applications()
                    .where(Application.candidate_id == candidate.id)
                    .options(selectinload(Application.job))
                    .order_by(Application.created_at.desc())
                    .limit(10)
                )
            )
            .unique()
            .scalars()
            .all()
        )
        return {
            "found": True,
            "candidate_id": str(candidate.id),
            "name": candidate.full_name,
            "current_designation": candidate.current_designation,
            "current_company": candidate.current_company,
            "experience_years": float(candidate.total_experience_years or 0),
            "location": candidate.location,
            "notice_period_days": candidate.notice_period_days,
            "skills": [s.name for s in candidate.skills][:20],
            "email_verified": candidate.email_verified,
            "applications": [
                {
                    "job_title": a.job.title if a.job else None,
                    "status": a.status.value,
                    "ats_score": float(a.ats_score) if a.ats_score is not None else None,
                    "applied_at": a.created_at.date().isoformat(),
                }
                for a in applications
            ],
        }

    async def compare_candidates(
        self, job_title: str | None = None, limit: int = 5
    ) -> dict[str, Any]:
        top = await self.list_top_candidates(job_title=job_title, limit=min(int(limit), 10))
        if not top["items"]:
            return top

        from app.modules.ats.service import AtsService

        ats = AtsService(self.session, self.company_id)
        comparison = []
        for item in top["items"]:
            score = await ats.latest_for_application(uuid.UUID(item["application_id"]))
            comparison.append(
                {
                    **item,
                    "matched_skills": score.matched_skills[:8] if score else [],
                    "missing_skills": score.missing_skills[:8] if score else [],
                    "skills_score": float(score.skills_score) if score else None,
                    "experience_score": float(score.experience_score) if score else None,
                    "recommendation": score.recommendation.value if score else None,
                }
            )
        return {"job": top.get("job"), "total": len(comparison), "items": comparison}

    async def conversion_stats(self) -> dict[str, Any]:
        from app.modules.analytics.service import AnalyticsService

        analytics = AnalyticsService(self.session, self.company_id)
        return {
            "funnel": (await analytics.funnel())["stages"],
            "job_performance": (await analytics.job_performance(limit=10))[
                "best_interview_conversion"
            ],
        }

    # ------------------------------------------------------- tool assembly
    def build(self) -> list[AssistantTool]:
        """Return only the tools this caller is permitted to use."""
        candidates: list[AssistantTool] = [
            AssistantTool(
                name="list_top_candidates",
                description=(
                    "List the highest-scoring candidates, optionally for one job. Use "
                    "for 'top candidates', 'best applicants', 'strongest matches'."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "job_title": {
                            "type": "string",
                            "description": "Job title or reference to narrow to one role",
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                    },
                },
                handler=self.list_top_candidates,
                required_permission=Perm.ATS_READ,
            ),
            AssistantTool(
                name="search_candidates",
                description=(
                    "Search applications by ATS score, skills, experience or pipeline "
                    "status. Use for 'candidates with score above 85', 'React developers "
                    "with 5 years'."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "job_title": {"type": "string"},
                        "min_ats_score": {"type": "number", "minimum": 0, "maximum": 100},
                        "skills": {"type": "array", "items": {"type": "string"}},
                        "min_experience": {"type": "number", "minimum": 0},
                        "status": {
                            "type": "string",
                            "description": "Pipeline status, e.g. SHORTLISTED",
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                    },
                },
                handler=self.search_candidates,
                required_permission=Perm.CANDIDATE_READ,
            ),
            AssistantTool(
                name="candidate_summary",
                description=(
                    "Get one candidate's profile and their applications by name or email."
                ),
                parameters={
                    "type": "object",
                    "properties": {"candidate_name": {"type": "string"}},
                    "required": ["candidate_name"],
                },
                handler=self.candidate_summary,
                required_permission=Perm.CANDIDATE_READ,
            ),
            AssistantTool(
                name="compare_candidates",
                description=(
                    "Compare the top candidates for a role side by side, including "
                    "matched and missing skills."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "job_title": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 2, "maximum": 10},
                    },
                },
                handler=self.compare_candidates,
                required_permission=Perm.ATS_READ,
            ),
            AssistantTool(
                name="count_applications",
                description="Count applications in a period: today, week, month or all.",
                parameters={
                    "type": "object",
                    "properties": {
                        "period": {
                            "type": "string",
                            "enum": ["today", "week", "month", "all"],
                        }
                    },
                },
                handler=self.count_applications,
                required_permission=Perm.APPLICATION_READ,
            ),
            AssistantTool(
                name="pipeline_overview",
                description=(
                    "Counts at each pipeline stage plus the funnel, for the whole "
                    "company or one job."
                ),
                parameters={
                    "type": "object",
                    "properties": {"job_title": {"type": "string"}},
                },
                handler=self.pipeline_overview,
                required_permission=Perm.APPLICATION_READ,
            ),
            AssistantTool(
                name="list_pending_feedback",
                description="Completed interviews that are still waiting for feedback.",
                parameters={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 25}
                    },
                },
                handler=self.list_pending_feedback,
                required_permission=Perm.FEEDBACK_READ,
            ),
            AssistantTool(
                name="list_todays_interviews",
                description="Interviews scheduled for today.",
                parameters={"type": "object", "properties": {}},
                handler=self.list_todays_interviews,
                required_permission=Perm.INTERVIEW_READ_ASSIGNED,
            ),
            AssistantTool(
                name="list_upcoming_interviews",
                description="Interviews scheduled over the next N days (default 7).",
                parameters={
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "minimum": 1, "maximum": 60}
                    },
                },
                handler=self.list_upcoming_interviews,
                required_permission=Perm.INTERVIEW_READ_ASSIGNED,
            ),
            AssistantTool(
                name="list_jobs",
                description="List the company's jobs, optionally filtered by status.",
                parameters={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["DRAFT", "PUBLISHED", "PAUSED", "CLOSED", "ARCHIVED"],
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                    },
                },
                handler=self.list_jobs,
                required_permission=Perm.JOB_READ,
            ),
            AssistantTool(
                name="conversion_stats",
                description=(
                    "Funnel counts and which jobs convert best from application to "
                    "interview."
                ),
                parameters={"type": "object", "properties": {}},
                handler=self.conversion_stats,
                required_permission=Perm.ANALYTICS_READ,
            ),
        ]

        # The permission filter is the security boundary, not the prompt.
        return [
            tool
            for tool in candidates
            if tool.required_permission is None
            or self.principal.has(tool.required_permission)
            or (
                tool.required_permission == Perm.INTERVIEW_READ_ASSIGNED
                and self.principal.has(Perm.INTERVIEW_READ)
            )
            or (
                tool.required_permission == Perm.JOB_READ
                and self.principal.has(Perm.JOB_READ_ASSIGNED)
            )
        ]
