"""ATS scores, per-dimension matches and configurable weight profiles."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AtsRecommendation
from app.db.base import Base, TenantMixin, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType

if TYPE_CHECKING:
    from app.models.application import Application


class AtsWeightProfile(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """A named set of ATS component weights, configurable per company and per job (s15).

    Weights are stored as fractions summing to 1.0; the check constraint plus service-level
    normalisation guarantee a score can never exceed 100 because of a misconfiguration.
    """

    __tablename__ = "ats_weight_profiles"
    __table_args__ = (
        Index("ix_ats_weight_profiles_company_name", "company_id", "name", unique=True),
        CheckConstraint(
            "skills_weight >= 0 AND experience_weight >= 0 AND education_weight >= 0 "
            "AND responsibilities_weight >= 0 AND semantic_weight >= 0",
            name="weights_non_negative",
        ),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    skills_weight: Mapped[float] = mapped_column(Numeric(4, 3), default=0.40, nullable=False)
    experience_weight: Mapped[float] = mapped_column(Numeric(4, 3), default=0.25, nullable=False)
    education_weight: Mapped[float] = mapped_column(Numeric(4, 3), default=0.10, nullable=False)
    responsibilities_weight: Mapped[float] = mapped_column(
        Numeric(4, 3), default=0.15, nullable=False
    )
    semantic_weight: Mapped[float] = mapped_column(Numeric(4, 3), default=0.10, nullable=False)

    #: Score at or above which the engine reports STRONG_MATCH / GOOD_MATCH. These are
    #: labels for humans, not automatic decisions.
    strong_match_threshold: Mapped[float] = mapped_column(Numeric(5, 2), default=85, nullable=False)
    good_match_threshold: Mapped[float] = mapped_column(Numeric(5, 2), default=70, nullable=False)
    partial_match_threshold: Mapped[float] = mapped_column(
        Numeric(5, 2), default=50, nullable=False
    )

    def as_weights(self) -> dict[str, float]:
        return {
            "skills": float(self.skills_weight),
            "experience": float(self.experience_weight),
            "education": float(self.education_weight),
            "responsibilities": float(self.responsibilities_weight),
            "semantic": float(self.semantic_weight),
        }


class AtsScore(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """One scoring run for one application. Immutable; re-scoring inserts a new row.

    Keeping every run means a recruiter can see that a score changed because the job
    requirements were edited, not because the candidate did anything.
    """

    __tablename__ = "ats_scores"
    __table_args__ = (
        Index("ix_ats_scores_application_created", "application_id", "created_at"),
        Index("ix_ats_scores_job_overall", "job_id", "overall_score"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("resumes.id", ondelete="SET NULL")
    )

    overall_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, index=True)
    skills_score: Mapped[float] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    experience_score: Mapped[float] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    education_score: Mapped[float] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    responsibilities_score: Mapped[float] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    semantic_score: Mapped[float] = mapped_column(Numeric(5, 2), default=0, nullable=False)

    recommendation: Mapped[AtsRecommendation] = mapped_column(
        SAEnum(AtsRecommendation, native_enum=False, length=20), nullable=False, index=True
    )
    #: Snapshot of the weights actually used, so an old score stays explainable after
    #: the profile is edited.
    weights_used: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    #: Plain-language reasons behind each component score - this is what makes the
    #: engine explainable rather than a black box (s14, s63).
    explanation: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)

    engine_version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    #: ``deterministic`` for the built-in engine, or ``anthropic:<model>`` when an LLM
    #: contributed the semantic component. Recorded for AI-governance auditing.
    semantic_engine: Mapped[str] = mapped_column(String(60), default="lexical", nullable=False)
    computed_ms: Mapped[int | None] = mapped_column()

    application: Mapped[Application] = relationship(back_populates="ats_scores", lazy="noload")
    matches: Mapped[list[AtsMatch]] = relationship(
        back_populates="score", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def matched_skills(self) -> list[str]:
        return [m.requirement for m in self.matches if m.is_matched]

    @property
    def missing_skills(self) -> list[str]:
        return [m.requirement for m in self.matches if not m.is_matched]


class AtsMatch(Base, UUIDMixin, TimestampMixin):
    """One requirement-level verdict inside a score: matched / partial / missing."""

    __tablename__ = "ats_matches"
    __table_args__ = (Index("ix_ats_matches_score_dimension", "ats_score_id", "dimension"),)

    ats_score_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("ats_scores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: SKILL | EXPERIENCE | EDUCATION | RESPONSIBILITY | CERTIFICATION
    dimension: Mapped[str] = mapped_column(String(30), nullable=False)
    requirement: Mapped[str] = mapped_column(String(255), nullable=False)
    importance: Mapped[str] = mapped_column(String(20), default="REQUIRED", nullable=False)
    is_matched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: 0-1. Below 1.0 with ``is_matched`` true means a fuzzy/semantic match, e.g. the
    #: candidate has "ReactJS" for a "React" requirement.
    match_strength: Mapped[float] = mapped_column(Numeric(3, 2), default=0, nullable=False)
    #: What in the candidate's profile produced the match, for the explanation panel.
    evidence: Mapped[str | None] = mapped_column(String(500))

    score: Mapped[AtsScore] = relationship(back_populates="matches", lazy="noload")
