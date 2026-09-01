"""Candidate profile management, search and AI summarisation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import ApplicationStatus, AuditAction
from app.core.exceptions import ResourceNotFound, ValidationError
from app.core.logging import get_logger
from app.models.application import Application
from app.models.candidate import (
    Candidate,
    CandidateEducation,
    CandidateExperience,
    CandidateNote,
    CandidateSkill,
)
from app.models.job import Job
from app.providers.ai.base import AIProvider
from app.providers.ai.factory import get_ai_provider
from app.services.audit import AuditService
from app.utils.skills import categorise_skill, display_skill, normalise_skill
from app.utils.text import truncate

logger = get_logger(__name__)


class CandidateService:
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

    # --------------------------------------------------------------- reads
    def base_query(self) -> Select[tuple[Candidate]]:
        return (
            select(Candidate)
            .where(
                Candidate.company_id == self.company_id, Candidate.deleted_at.is_(None)
            )
            .options(
                selectinload(Candidate.skills),
                selectinload(Candidate.education),
                selectinload(Candidate.experience),
            )
        )

    async def get(self, candidate_id: uuid.UUID) -> Candidate:
        candidate = (
            (await self.session.execute(self.base_query().where(Candidate.id == candidate_id)))
            .unique()
            .scalar_one_or_none()
        )
        if candidate is None:
            raise ResourceNotFound("Candidate", candidate_id)
        return candidate

    async def search(
        self,
        *,
        query: str | None = None,
        skills: list[str] | None = None,
        min_experience: float | None = None,
        max_experience: float | None = None,
        location: str | None = None,
        min_ats_score: float | None = None,
        job_id: uuid.UUID | None = None,
        application_status: list[ApplicationStatus] | None = None,
        max_notice_period: int | None = None,
        tags: list[str] | None = None,
        page: int = 1,
        page_size: int = 20,
        sort: str = "-created_at",
    ) -> tuple[list[Candidate], int]:
        stmt = self.base_query()

        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    Candidate.first_name.ilike(pattern),
                    Candidate.last_name.ilike(pattern),
                    Candidate.email.ilike(pattern),
                    Candidate.phone.ilike(pattern),
                    Candidate.current_designation.ilike(pattern),
                    Candidate.current_company.ilike(pattern),
                    Candidate.headline.ilike(pattern),
                )
            )

        if skills:
            # Every requested skill must be present, so a multi-skill search narrows
            # rather than widens. Matching is on the normalised name so "ReactJS" finds
            # a candidate whose profile says "React".
            for skill in skills:
                key = normalise_skill(skill)
                if not key:
                    continue
                stmt = stmt.where(
                    Candidate.id.in_(
                        select(CandidateSkill.candidate_id).where(
                            CandidateSkill.normalised_name == key
                        )
                    )
                )

        if min_experience is not None:
            stmt = stmt.where(Candidate.total_experience_years >= min_experience)
        if max_experience is not None:
            stmt = stmt.where(Candidate.total_experience_years <= max_experience)
        if location:
            pattern = f"%{location.strip()}%"
            stmt = stmt.where(
                or_(Candidate.location.ilike(pattern), Candidate.city.ilike(pattern))
            )
        if max_notice_period is not None:
            stmt = stmt.where(Candidate.notice_period_days <= max_notice_period)

        if job_id or min_ats_score is not None or application_status:
            application_filter = select(Application.candidate_id).where(
                Application.company_id == self.company_id
            )
            if job_id:
                application_filter = application_filter.where(Application.job_id == job_id)
            if min_ats_score is not None:
                application_filter = application_filter.where(
                    Application.ats_score >= min_ats_score
                )
            if application_status:
                application_filter = application_filter.where(
                    Application.status.in_(application_status)
                )
            stmt = stmt.where(Candidate.id.in_(application_filter))

        if tags:
            for tag in tags:
                stmt = stmt.where(Candidate.tags.contains([tag]))

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

    # -------------------------------------------------------------- writes
    async def update_profile(
        self, candidate: Candidate, *, changes: dict[str, Any], actor_id: uuid.UUID | None = None
    ) -> Candidate:
        from app.services.audit import diff

        before = {k: getattr(candidate, k, None) for k in changes}
        for field, value in changes.items():
            if hasattr(candidate, field) and value is not None:
                setattr(candidate, field, value)

        await self.audit.record(
            action=AuditAction.UPDATE,
            entity_type="Candidate",
            entity_id=candidate.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=f"Updated candidate profile for {candidate.full_name}",
            changes=diff(before, {k: getattr(candidate, k, None) for k in before}),
        )
        await self.session.flush()
        return candidate

    async def replace_skills(
        self, candidate: Candidate, skills: list[dict[str, Any]]
    ) -> Candidate:
        candidate.skills.clear()
        await self.session.flush()
        seen: set[str] = set()
        for entry in skills:
            raw = (entry.get("name") or "").strip()
            key = normalise_skill(raw)
            if not key or key in seen:
                continue
            seen.add(key)
            self.session.add(
                CandidateSkill(
                    candidate_id=candidate.id,
                    name=display_skill(raw),
                    normalised_name=key,
                    years_experience=entry.get("years_experience"),
                    proficiency=entry.get("proficiency"),
                    category=entry.get("category") or categorise_skill(raw),
                    source="MANUAL",
                )
            )
        await self.session.flush()
        return candidate

    async def replace_education(
        self, candidate: Candidate, entries: list[dict[str, Any]]
    ) -> Candidate:
        candidate.education.clear()
        await self.session.flush()
        for entry in entries:
            self.session.add(CandidateEducation(candidate_id=candidate.id, **entry))
        await self.session.flush()
        return candidate

    async def replace_experience(
        self, candidate: Candidate, entries: list[dict[str, Any]]
    ) -> Candidate:
        candidate.experience.clear()
        await self.session.flush()
        for entry in entries:
            if entry.get("start_date") and entry.get("end_date"):
                if entry["end_date"] < entry["start_date"]:
                    raise ValidationError(
                        f"'{entry.get('position', 'A role')}' ends before it starts"
                    )
            self.session.add(CandidateExperience(candidate_id=candidate.id, **entry))
        await self.session.flush()

        # Recompute total experience from the corrected history.
        await self.session.refresh(candidate, ["experience"])
        candidate.total_experience_years = _total_years(candidate.experience)
        await self.session.flush()
        return candidate

    # --------------------------------------------------------------- notes
    async def add_note(
        self,
        candidate: Candidate,
        *,
        body: str,
        author_id: uuid.UUID,
        application_id: uuid.UUID | None = None,
        is_private: bool = False,
    ) -> CandidateNote:
        note = CandidateNote(
            company_id=self.company_id,
            candidate_id=candidate.id,
            application_id=application_id,
            author_id=author_id,
            body=body,
            is_private=is_private,
        )
        self.session.add(note)
        await self.session.flush()
        return note

    async def list_notes(
        self, candidate_id: uuid.UUID, *, viewer_id: uuid.UUID, can_see_private: bool
    ) -> list[CandidateNote]:
        """Private notes are visible only to their author, unless the viewer is an admin."""
        stmt = (
            select(CandidateNote)
            .where(
                CandidateNote.candidate_id == candidate_id,
                CandidateNote.company_id == self.company_id,
            )
            .order_by(CandidateNote.created_at.desc())
        )
        if not can_see_private:
            stmt = stmt.where(
                or_(
                    CandidateNote.is_private.is_(False),
                    CandidateNote.author_id == viewer_id,
                )
            )
        return list((await self.session.execute(stmt)).scalars().all())

    # ----------------------------------------------------------- ai summary
    async def generate_summary(
        self,
        candidate: Candidate,
        *,
        job_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> tuple[str, list[str], list[str], str]:
        """Generate a recruiter-facing summary. Returns
        ``(summary, strengths, considerations, engine)``."""
        profile = {
            "full_name": candidate.full_name,
            "current_designation": candidate.current_designation,
            "current_company": candidate.current_company,
            "total_experience_years": float(candidate.total_experience_years or 0),
            "skills": [s.name for s in candidate.skills][:30],
            "education": [
                " ".join(filter(None, [e.degree, e.institution])) for e in candidate.education
            ][:5],
            "experience": [
                {
                    "company": e.company_name,
                    "position": e.position,
                    "is_current": e.is_current,
                    "responsibilities": (e.responsibilities or [])[:5],
                }
                for e in candidate.experience[:6]
            ],
            "location": candidate.location,
            "email_verified": candidate.email_verified,
            "summary": candidate.summary,
        }

        job_context: dict[str, Any] | None = None
        if job_id is not None:
            job = await self.session.get(Job, job_id)
            if job is not None and job.company_id == self.company_id:
                from app.modules.ats.service import AtsService

                ats = AtsService(self.session, self.company_id, ai_provider=self.ai)
                application = await self.session.scalar(
                    select(Application).where(
                        Application.job_id == job_id,
                        Application.candidate_id == candidate.id,
                    )
                )
                latest = (
                    await ats.latest_for_application(application.id) if application else None
                )
                job_context = {
                    "job_title": job.title,
                    "required_skills": job.required_skills,
                    "min_experience_years": float(job.min_experience_years or 0),
                    "missing_skills": latest.missing_skills if latest else [],
                }

        result = await self.ai.summarize_candidate(
            candidate_profile=profile, job_context=job_context
        )
        summary = result.value

        candidate.ai_summary = truncate(summary.summary, 2000)
        candidate.ai_summary_generated_at = datetime.now(UTC)

        await self.audit.record_ai(
            feature="CANDIDATE_SUMMARY",
            engine=result.usage.engine,
            model=result.usage.model,
            company_id=self.company_id,
            user_id=actor_id,
            entity_type="Candidate",
            entity_id=candidate.id,
            input_digest={
                "skills": len(profile["skills"]),
                "experience_entries": len(profile["experience"]),
                "has_job_context": job_context is not None,
            },
            output_summary={"summary": truncate(summary.summary, 300)},
            latency_ms=result.usage.latency_ms,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            error=result.usage.error,
        )
        await self.session.flush()
        return summary.summary, summary.strengths, summary.considerations, result.usage.engine

    # --------------------------------------------------------------- flags
    async def resolve_flag(
        self, candidate: Candidate, flag_code: str, *, actor_id: uuid.UUID
    ) -> Candidate:
        """Mark a review flag as looked at. Flags are never auto-resolved."""
        flags = list(candidate.review_flags or [])
        found = False
        for flag in flags:
            if flag.get("code") == flag_code and not flag.get("resolved"):
                flag["resolved"] = True
                flag["resolved_at"] = datetime.now(UTC).isoformat()
                flag["resolved_by"] = str(actor_id)
                found = True
        if not found:
            raise ResourceNotFound("Review flag", flag_code)

        candidate.review_flags = flags
        await self.audit.record(
            action=AuditAction.UPDATE,
            entity_type="Candidate",
            entity_id=candidate.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=f"Resolved review flag {flag_code} for {candidate.full_name}",
        )
        await self.session.flush()
        return candidate

    async def applications_for(self, candidate_id: uuid.UUID) -> list[Application]:
        stmt = (
            select(Application)
            .where(
                Application.candidate_id == candidate_id,
                Application.company_id == self.company_id,
            )
            .options(selectinload(Application.job))
            .order_by(Application.created_at.desc())
        )
        return list((await self.session.execute(stmt)).unique().scalars().all())


def _total_years(experience: list[CandidateExperience]) -> float:
    """Merged, non-overlapping total so concurrent roles are not double-counted."""
    from datetime import date

    spans: list[tuple[date, date]] = []
    today = date.today()
    for entry in experience:
        if not entry.start_date:
            continue
        end = entry.end_date or today
        if end < entry.start_date:
            continue
        spans.append((entry.start_date, min(end, today)))
    if not spans:
        return 0.0

    spans.sort()
    merged: list[list[date]] = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    months = sum(
        max(0, (e.year - s.year) * 12 + (e.month - s.month)) for s, e in merged
    )
    return round(months / 12, 1)


def _sort_expression(sort: str):
    descending = sort.startswith("-")
    field = sort.lstrip("-")
    column = {
        "created_at": Candidate.created_at,
        "name": Candidate.last_name,
        "experience": Candidate.total_experience_years,
        "notice_period": Candidate.notice_period_days,
        "updated_at": Candidate.updated_at,
    }.get(field, Candidate.created_at)
    return (
        (column.desc().nullslast(), Candidate.id)
        if descending
        else (column.asc().nullslast(), Candidate.id)
    )
