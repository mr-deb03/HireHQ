"""ATS scoring service: loads data, calls the pure engine, persists the explanation."""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.enums import SkillImportance
from app.core.exceptions import ResourceNotFound, ValidationError
from app.core.logging import get_logger
from app.models.application import Application
from app.models.ats import AtsMatch, AtsScore, AtsWeightProfile
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.resume import Resume
from app.modules.ats.engine import (
    AtsResult,
    CandidateProfile,
    JobRequirements,
    compute_ranks,
    infer_education_level,
    score_application,
)
from app.providers.ai.base import AIProvider
from app.providers.ai.factory import get_ai_provider
from app.services.audit import AuditService
from app.services.events import DomainEvent, EventCollector, Events
from app.utils.skills import normalise_skill

logger = get_logger(__name__)

ENGINE_VERSION = "1.0"


class AtsService:
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

    # ------------------------------------------------------------- profiles
    async def resolve_weight_profile(self, job: Job) -> AtsWeightProfile | None:
        """Job override -> company default -> platform default (returns None)."""
        if job.ats_weight_profile_id:
            profile = await self.session.get(AtsWeightProfile, job.ats_weight_profile_id)
            if profile is not None and profile.company_id == self.company_id:
                return profile
        return await self.session.scalar(
            select(AtsWeightProfile).where(
                AtsWeightProfile.company_id == self.company_id,
                AtsWeightProfile.is_default.is_(True),
            )
        )

    async def list_profiles(self) -> list[AtsWeightProfile]:
        result = await self.session.execute(
            select(AtsWeightProfile)
            .where(AtsWeightProfile.company_id == self.company_id)
            .order_by(AtsWeightProfile.is_default.desc(), AtsWeightProfile.name)
        )
        return list(result.scalars().all())

    async def create_profile(
        self,
        *,
        name: str,
        weights: dict[str, float],
        thresholds: dict[str, float] | None = None,
        description: str | None = None,
        is_default: bool = False,
    ) -> AtsWeightProfile:
        for key, value in weights.items():
            if value < 0:
                raise ValidationError(f"The {key} weight cannot be negative")
        if sum(weights.values()) <= 0:
            raise ValidationError("At least one weight must be greater than zero")

        thresholds = thresholds or {}
        strong = thresholds.get("strong", 85)
        good = thresholds.get("good", 70)
        partial = thresholds.get("partial", 50)
        if not (strong > good > partial):
            raise ValidationError(
                "Thresholds must decrease: strong > good > partial",
                details={"strong": strong, "good": good, "partial": partial},
            )

        if is_default:
            await self.session.execute(
                update(AtsWeightProfile)
                .where(AtsWeightProfile.company_id == self.company_id)
                .values(is_default=False)
            )

        profile = AtsWeightProfile(
            company_id=self.company_id,
            name=name,
            description=description,
            is_default=is_default,
            skills_weight=weights.get("skills", settings.ATS_WEIGHT_SKILLS),
            experience_weight=weights.get("experience", settings.ATS_WEIGHT_EXPERIENCE),
            education_weight=weights.get("education", settings.ATS_WEIGHT_EDUCATION),
            responsibilities_weight=weights.get(
                "responsibilities", settings.ATS_WEIGHT_RESPONSIBILITIES
            ),
            semantic_weight=weights.get("semantic", settings.ATS_WEIGHT_SEMANTIC),
            strong_match_threshold=strong,
            good_match_threshold=good,
            partial_match_threshold=partial,
        )
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def ensure_default_profile(self) -> AtsWeightProfile:
        existing = await self.session.scalar(
            select(AtsWeightProfile).where(
                AtsWeightProfile.company_id == self.company_id,
                AtsWeightProfile.is_default.is_(True),
            )
        )
        if existing is not None:
            return existing
        return await self.create_profile(
            name="Balanced (default)",
            description=(
                "The platform default: skills 40%, experience 25%, responsibilities 15%, "
                "education 10%, semantic similarity 10%."
            ),
            weights={
                "skills": settings.ATS_WEIGHT_SKILLS,
                "experience": settings.ATS_WEIGHT_EXPERIENCE,
                "education": settings.ATS_WEIGHT_EDUCATION,
                "responsibilities": settings.ATS_WEIGHT_RESPONSIBILITIES,
                "semantic": settings.ATS_WEIGHT_SEMANTIC,
            },
            is_default=True,
        )

    # -------------------------------------------------------------- scoring
    async def score(
        self, application_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> AtsScore:
        """Score one application and persist the full explanation."""
        started = time.monotonic()

        application = await self._load_application(application_id)
        job, candidate = application.job, application.candidate

        resume = None
        if application.resume_id:
            resume = await self.session.get(Resume, application.resume_id)
        if resume is None:
            resume = await self.session.scalar(
                select(Resume)
                .where(
                    Resume.candidate_id == candidate.id,
                    Resume.company_id == self.company_id,
                    Resume.is_primary.is_(True),
                )
                .order_by(Resume.created_at.desc())
                .limit(1)
            )

        requirements = self._build_requirements(job)
        profile_data = self._build_profile(candidate, resume)

        semantic_similarity, semantic_engine = await self._semantic(job, profile_data)

        weight_profile = await self.resolve_weight_profile(job)
        weights = weight_profile.as_weights() if weight_profile else {}
        thresholds = (
            {
                "strong": float(weight_profile.strong_match_threshold),
                "good": float(weight_profile.good_match_threshold),
                "partial": float(weight_profile.partial_match_threshold),
            }
            if weight_profile
            else None
        )

        result = score_application(
            requirements,
            profile_data,
            weights=weights,
            thresholds=thresholds,
            semantic_similarity=semantic_similarity,
            semantic_engine=semantic_engine,
        )

        score_row = await self._persist(
            application=application,
            result=result,
            resume_id=resume.id if resume else None,
            semantic_engine=semantic_engine,
            computed_ms=int((time.monotonic() - started) * 1000),
        )

        await self.audit.record_ai(
            feature="ATS_SEMANTIC",
            engine=semantic_engine,
            company_id=self.company_id,
            user_id=actor_id,
            entity_type="Application",
            entity_id=application.id,
            input_digest={
                "required_skills": len(requirements.required_skills),
                "candidate_skills": len(profile_data.skills),
                "has_resume_text": bool(profile_data.resume_text),
            },
            output_summary={
                "overall_score": result.overall_score,
                "recommendation": result.recommendation.value,
                "semantic": result.semantic_score,
            },
            confidence=semantic_similarity,
        )

        self.events.collect(
            DomainEvent(
                name=Events.ATS_SCORE_GENERATED,
                company_id=self.company_id,
                entity_type="Application",
                entity_id=application.id,
                actor_id=actor_id,
                payload={
                    "score": result.overall_score,
                    "recommendation": result.recommendation.value,
                    "score_id": str(score_row.id),
                    "job_id": str(job.id),
                    "job_title": job.title,
                    "candidate_id": str(candidate.id),
                    "candidate_name": candidate.full_name,
                },
            )
        )

        logger.info(
            "ats_scored",
            application_id=str(application.id),
            score=result.overall_score,
            recommendation=result.recommendation.value,
        )
        return score_row

    async def _load_application(self, application_id: uuid.UUID) -> Application:
        stmt = (
            select(Application)
            .where(
                Application.id == application_id, Application.company_id == self.company_id
            )
            .options(
                selectinload(Application.job).selectinload(Job.skills),
                selectinload(Application.candidate).selectinload(Candidate.skills),
                selectinload(Application.candidate).selectinload(Candidate.education),
                selectinload(Application.candidate).selectinload(Candidate.experience),
            )
        )
        application = (await self.session.execute(stmt)).unique().scalar_one_or_none()
        if application is None:
            raise ResourceNotFound("Application", application_id)
        return application

    @staticmethod
    def _build_requirements(job: Job) -> JobRequirements:
        return JobRequirements(
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

    @staticmethod
    def _build_profile(candidate: Candidate, resume: Resume | None) -> CandidateProfile:
        education_entries = [
            " ".join(filter(None, [e.degree, e.field_of_study, e.institution]))
            for e in candidate.education
        ]
        bullets: list[str] = []
        titles: list[str] = []
        for experience in candidate.experience:
            titles.append(experience.position)
            bullets.extend(experience.responsibilities or [])
            if experience.description:
                bullets.append(experience.description)
        if candidate.current_designation:
            titles.append(candidate.current_designation)
        if candidate.summary:
            bullets.append(candidate.summary)

        level = None
        for entry in candidate.education:
            if entry.degree_level:
                level = entry.degree_level
                break
        if level is None:
            level = infer_education_level(education_entries)

        certifications: list[str] = []
        if resume is not None and resume.analysis is not None:
            certifications = list(resume.analysis.certifications or [])

        return CandidateProfile(
            skills=[s.name for s in candidate.skills],
            total_experience_years=float(candidate.total_experience_years or 0),
            education_level=level,
            education_entries=education_entries,
            certifications=certifications,
            experience_bullets=bullets,
            job_titles=titles,
            resume_text=(resume.extracted_text or "") if resume else "",
        )

    async def _semantic(
        self, job: Job, profile: CandidateProfile
    ) -> tuple[float, str]:
        """Semantic similarity between the job and the resume.

        Uses whichever AI provider is configured. If there is no resume text there is
        nothing meaningful to compare, so this returns 0 with an explicit engine label
        rather than inventing a number.
        """
        if not profile.resume_text.strip():
            return 0.0, "unavailable (no resume text)"

        job_text = "\n".join(
            filter(
                None,
                [
                    job.title,
                    job.description,
                    " ".join(job.responsibilities or []),
                    " ".join(s.name for s in job.skills),
                ],
            )
        )
        try:
            result = await self.ai.assess_semantic_fit(
                job_text=job_text, resume_text=profile.resume_text
            )
            return float(result.value.similarity), result.usage.engine
        except Exception as exc:
            logger.warning("semantic_scoring_failed", error=str(exc))
            return 0.0, "unavailable (provider error)"

    async def _persist(
        self,
        *,
        application: Application,
        result: AtsResult,
        resume_id: uuid.UUID | None,
        semantic_engine: str,
        computed_ms: int,
    ) -> AtsScore:
        score = AtsScore(
            company_id=self.company_id,
            application_id=application.id,
            job_id=application.job_id,
            candidate_id=application.candidate_id,
            resume_id=resume_id,
            overall_score=result.overall_score,
            skills_score=result.skills_score,
            experience_score=result.experience_score,
            education_score=result.education_score,
            responsibilities_score=result.responsibilities_score,
            semantic_score=result.semantic_score,
            recommendation=result.recommendation,
            weights_used=result.weights_used,
            explanation=result.explanation,
            engine_version=ENGINE_VERSION,
            semantic_engine=semantic_engine,
            computed_ms=computed_ms,
        )
        self.session.add(score)
        await self.session.flush()

        for match in result.matches:
            self.session.add(
                AtsMatch(
                    ats_score_id=score.id,
                    dimension="SKILL",
                    requirement=match.requirement[:255],
                    importance="REQUIRED",
                    is_matched=match.matched,
                    match_strength=match.strength,
                    evidence=match.evidence[:500] if match.evidence else None,
                )
            )

        # Denormalise onto the application so ranking and filtering are one index scan.
        application.ats_score = result.overall_score
        await self.session.flush()
        await self.rank_job(application.job_id)
        return score

    # -------------------------------------------------------------- ranking
    async def rank_job(self, job_id: uuid.UUID) -> int:
        """Recompute dense ranks for every scored application on a job."""
        rows = (
            await self.session.execute(
                select(Application.id, Application.ats_score).where(
                    Application.job_id == job_id,
                    Application.company_id == self.company_id,
                    Application.ats_score.is_not(None),
                )
            )
        ).all()
        if not rows:
            return 0

        ranks = compute_ranks([(str(row[0]), float(row[1])) for row in rows])
        for application_id, rank in ranks.items():
            await self.session.execute(
                update(Application)
                .where(Application.id == uuid.UUID(application_id))
                .values(ats_rank=rank)
            )
        return len(ranks)

    async def rescore_job(
        self, job_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> dict[str, int]:
        """Re-score every application on a job, e.g. after its requirements were edited."""
        application_ids = list(
            (
                await self.session.execute(
                    select(Application.id).where(
                        Application.job_id == job_id,
                        Application.company_id == self.company_id,
                    )
                )
            )
            .scalars()
            .all()
        )

        succeeded = failed = 0
        for application_id in application_ids:
            try:
                await self.score(application_id, actor_id=actor_id)
                succeeded += 1
            except Exception as exc:
                failed += 1
                logger.warning(
                    "rescore_failed", application_id=str(application_id), error=str(exc)
                )
        return {"total": len(application_ids), "scored": succeeded, "failed": failed}

    async def latest_for_application(self, application_id: uuid.UUID) -> AtsScore | None:
        return await self.session.scalar(
            select(AtsScore)
            .where(
                AtsScore.application_id == application_id,
                AtsScore.company_id == self.company_id,
            )
            .options(selectinload(AtsScore.matches))
            .order_by(AtsScore.created_at.desc())
            .limit(1)
        )

    async def history_for_application(
        self, application_id: uuid.UUID, *, limit: int = 10
    ) -> Sequence[AtsScore]:
        result = await self.session.execute(
            select(AtsScore)
            .where(
                AtsScore.application_id == application_id,
                AtsScore.company_id == self.company_id,
            )
            .order_by(AtsScore.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
