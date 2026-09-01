"""Talent pools: reusable candidate groups and AI-assisted matching to new jobs."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ResourceNotFound, ValidationError
from app.core.logging import get_logger
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.talent import TalentPool, TalentPoolMember
from app.modules.ats.engine import (
    CandidateProfile,
    JobRequirements,
    infer_education_level,
    score_application,
)
from app.providers.ai.factory import get_ai_provider
from app.utils.skills import normalise_skill

logger = get_logger(__name__)


class TalentPoolService:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID) -> None:
        self.session = session
        self.company_id = company_id

    # --------------------------------------------------------------- pools
    async def list_pools(self) -> list[TalentPool]:
        result = await self.session.execute(
            select(TalentPool)
            .where(TalentPool.company_id == self.company_id)
            .order_by(TalentPool.name)
        )
        return list(result.scalars().all())

    async def get(self, pool_id: uuid.UUID) -> TalentPool:
        pool = await self.session.scalar(
            select(TalentPool).where(
                TalentPool.id == pool_id, TalentPool.company_id == self.company_id
            )
        )
        if pool is None:
            raise ResourceNotFound("Talent pool", pool_id)
        return pool

    async def create(
        self,
        *,
        name: str,
        description: str | None = None,
        criteria: dict[str, Any] | None = None,
        colour: str | None = None,
        created_by_id: uuid.UUID | None = None,
    ) -> TalentPool:
        name = name.strip()
        if not name:
            raise ValidationError("A pool name is required")

        existing = await self.session.scalar(
            select(TalentPool).where(
                TalentPool.company_id == self.company_id, TalentPool.name == name
            )
        )
        if existing is not None:
            from app.core.exceptions import DuplicateResource

            raise DuplicateResource(f"A pool named '{name}' already exists")

        pool = TalentPool(
            company_id=self.company_id,
            name=name,
            description=description,
            criteria=criteria or {},
            is_dynamic=bool(criteria),
            colour=colour,
            created_by_id=created_by_id,
        )
        self.session.add(pool)
        await self.session.flush()
        return pool

    async def get_or_create(
        self, *, pool_id: uuid.UUID | None = None, name: str = ""
    ) -> TalentPool:
        """Used by automation, which may reference a pool that does not exist yet."""
        if pool_id:
            return await self.get(uuid.UUID(str(pool_id)))
        name = (name or "Automated").strip()
        existing = await self.session.scalar(
            select(TalentPool).where(
                TalentPool.company_id == self.company_id, TalentPool.name == name
            )
        )
        if existing is not None:
            return existing
        return await self.create(name=name, description="Created automatically by a workflow")

    async def delete(self, pool: TalentPool) -> None:
        await self.session.delete(pool)
        await self.session.flush()

    # ------------------------------------------------------------- members
    async def add_candidate(
        self,
        pool: TalentPool,
        candidate_id: uuid.UUID,
        *,
        note: str | None = None,
        added_by_id: uuid.UUID | None = None,
    ) -> bool:
        """Add a candidate. Returns False when they were already a member."""
        candidate = await self.session.scalar(
            select(Candidate).where(
                Candidate.id == candidate_id,
                Candidate.company_id == self.company_id,
                Candidate.deleted_at.is_(None),
            )
        )
        if candidate is None:
            raise ResourceNotFound("Candidate", candidate_id)

        existing = await self.session.scalar(
            select(TalentPoolMember).where(
                TalentPoolMember.pool_id == pool.id,
                TalentPoolMember.candidate_id == candidate_id,
            )
        )
        if existing is not None:
            return False

        from app.models.application import Application

        best_score = await self.session.scalar(
            select(func.max(Application.ats_score)).where(
                Application.candidate_id == candidate_id,
                Application.company_id == self.company_id,
            )
        )

        self.session.add(
            TalentPoolMember(
                pool_id=pool.id,
                candidate_id=candidate_id,
                added_by_id=added_by_id,
                note=note,
                snapshot_ats_score=best_score,
            )
        )
        pool.member_count = (pool.member_count or 0) + 1
        await self.session.flush()
        return True

    async def remove_candidate(self, pool: TalentPool, candidate_id: uuid.UUID) -> bool:
        member = await self.session.scalar(
            select(TalentPoolMember).where(
                TalentPoolMember.pool_id == pool.id,
                TalentPoolMember.candidate_id == candidate_id,
            )
        )
        if member is None:
            return False
        await self.session.delete(member)
        pool.member_count = max(0, (pool.member_count or 1) - 1)
        await self.session.flush()
        return True

    async def list_members(
        self, pool: TalentPool, *, page: int = 1, page_size: int = 20
    ) -> tuple[list[Candidate], int]:
        stmt = (
            select(Candidate)
            .join(TalentPoolMember, TalentPoolMember.candidate_id == Candidate.id)
            .where(
                TalentPoolMember.pool_id == pool.id,
                Candidate.deleted_at.is_(None),
            )
            .options(selectinload(Candidate.skills))
            .order_by(TalentPoolMember.created_at.desc())
        )
        total = (
            await self.session.execute(
                select(func.count()).select_from(stmt.order_by(None).subquery())
            )
        ).scalar_one()
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

    # -------------------------------------------------------------- matching
    async def match_candidates_for_job(
        self,
        job_id: uuid.UUID,
        *,
        pool_id: uuid.UUID | None = None,
        limit: int = 20,
        min_score: float = 50.0,
    ) -> list[dict[str, Any]]:
        """Recommend existing candidates for a new job (s31).

        Runs the same ATS engine used for real applications, so a recommendation is
        directly comparable to a live applicant's score - and equally explainable.
        Candidates who have already applied to this job are excluded.
        """
        job = await self.session.scalar(
            select(Job)
            .where(Job.id == job_id, Job.company_id == self.company_id)
            .options(selectinload(Job.skills))
        )
        if job is None:
            raise ResourceNotFound("Job", job_id)

        from app.models.application import Application

        already_applied = set(
            (
                await self.session.execute(
                    select(Application.candidate_id).where(Application.job_id == job_id)
                )
            )
            .scalars()
            .all()
        )

        stmt = (
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
        if pool_id:
            stmt = stmt.join(
                TalentPoolMember, TalentPoolMember.candidate_id == Candidate.id
            ).where(TalentPoolMember.pool_id == pool_id)

        # Narrow to candidates sharing at least one required skill before scoring, so a
        # large talent pool does not mean scoring thousands of hopeless matches.
        required_keys = [normalise_skill(s.name) for s in job.skills]
        if required_keys:
            from app.models.candidate import CandidateSkill

            stmt = stmt.where(
                Candidate.id.in_(
                    select(CandidateSkill.candidate_id).where(
                        CandidateSkill.normalised_name.in_(required_keys)
                    )
                )
            )

        candidates = (
            (await self.session.execute(stmt.limit(500))).unique().scalars().all()
        )

        from app.core.enums import SkillImportance

        requirements = JobRequirements(
            title=job.title,
            required_skills=[
                s.name for s in job.skills if s.importance == SkillImportance.REQUIRED
            ],
            preferred_skills=[
                s.name for s in job.skills if s.importance == SkillImportance.PREFERRED
            ],
            skill_weights={normalise_skill(s.name): s.weight for s in job.skills},
            min_experience_years=float(job.min_experience_years or 0),
            max_experience_years=(
                float(job.max_experience_years) if job.max_experience_years else None
            ),
            education_requirements=list(job.education_requirements or []),
            certifications=list(job.certifications or []),
            responsibilities=list(job.responsibilities or []),
            description=job.description or "",
        )

        ai = get_ai_provider()
        job_text = "\n".join(
            filter(None, [job.title, job.description, " ".join(job.responsibilities or [])])
        )

        results: list[dict[str, Any]] = []
        for candidate in candidates:
            if candidate.id in already_applied:
                continue

            education_entries = [
                " ".join(filter(None, [e.degree, e.field_of_study, e.institution]))
                for e in candidate.education
            ]
            bullets: list[str] = []
            titles: list[str] = []
            for experience in candidate.experience:
                titles.append(experience.position)
                bullets.extend(experience.responsibilities or [])
            if candidate.current_designation:
                titles.append(candidate.current_designation)

            profile_text = " ".join(
                filter(
                    None,
                    [
                        candidate.summary or "",
                        " ".join(s.name for s in candidate.skills),
                        " ".join(titles),
                        " ".join(bullets[:30]),
                    ],
                )
            )
            similarity = 0.0
            if profile_text.strip():
                try:
                    assessment = await ai.assess_semantic_fit(
                        job_text=job_text, resume_text=profile_text
                    )
                    similarity = float(assessment.value.similarity)
                except Exception:
                    similarity = 0.0

            profile = CandidateProfile(
                skills=[s.name for s in candidate.skills],
                total_experience_years=float(candidate.total_experience_years or 0),
                education_level=next(
                    (e.degree_level for e in candidate.education if e.degree_level),
                    infer_education_level(education_entries),
                ),
                education_entries=education_entries,
                experience_bullets=bullets,
                job_titles=titles,
                resume_text=profile_text,
            )
            outcome = score_application(
                requirements, profile, semantic_similarity=similarity
            )
            if outcome.overall_score < min_score:
                continue

            results.append(
                {
                    "candidate_id": str(candidate.id),
                    "full_name": candidate.full_name,
                    "email": candidate.email,
                    "current_designation": candidate.current_designation,
                    "total_experience_years": float(candidate.total_experience_years or 0),
                    "score": outcome.overall_score,
                    "recommendation": outcome.recommendation.value,
                    "matched_skills": outcome.matched_skills[:10],
                    "missing_skills": outcome.missing_skills[:10],
                    "summary": outcome.explanation["summary"],
                }
            )

        results.sort(key=lambda item: item["score"], reverse=True)
        logger.info(
            "talent_pool_matched",
            job_id=str(job_id),
            evaluated=len(candidates),
            matched=len(results),
        )
        return results[:limit]

    async def refresh_dynamic_pool(self, pool: TalentPool) -> int:
        """Re-run a saved-search pool's criteria and add newly matching candidates."""
        if not pool.is_dynamic or not pool.criteria:
            raise ValidationError("This pool does not have saved search criteria")

        from app.modules.candidates.service import CandidateService

        service = CandidateService(self.session, self.company_id)
        criteria = pool.criteria
        candidates, _ = await service.search(
            query=criteria.get("q"),
            skills=criteria.get("skills"),
            min_experience=criteria.get("min_experience"),
            max_experience=criteria.get("max_experience"),
            location=criteria.get("location"),
            min_ats_score=criteria.get("min_ats_score"),
            max_notice_period=criteria.get("max_notice_period"),
            page=1,
            page_size=500,
        )

        added = 0
        for candidate in candidates:
            if await self.add_candidate(pool, candidate.id, note="Matched saved criteria"):
                added += 1
        return added
