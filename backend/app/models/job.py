"""Jobs, their skill requirements, hiring team and screening questions."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    EmploymentType,
    JobStatus,
    ScreeningQuestionType,
    SkillImportance,
    WorkMode,
)
from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType, StringArray, UTCDateTime

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.company import Company


class Job(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_company_status", "company_id", "status"),
        Index("ix_jobs_status_published", "status", "published_at"),
        Index("ix_jobs_company_created", "company_id", "created_at"),
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    #: Human-friendly reference shown in the UI and in emails, e.g. ``ENG-2024-014``.
    reference_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    department_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="SET NULL"), index=True
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("company_locations.id", ondelete="SET NULL")
    )
    location_text: Mapped[str | None] = mapped_column(String(255), index=True)

    work_mode: Mapped[WorkMode] = mapped_column(
        SAEnum(WorkMode, native_enum=False, length=20), default=WorkMode.ONSITE, nullable=False,
        index=True,
    )
    employment_type: Mapped[EmploymentType] = mapped_column(
        SAEnum(EmploymentType, native_enum=False, length=20),
        default=EmploymentType.FULL_TIME,
        nullable=False,
        index=True,
    )

    min_experience_years: Mapped[float] = mapped_column(Numeric(4, 1), default=0, nullable=False)
    max_experience_years: Mapped[float | None] = mapped_column(Numeric(4, 1))
    salary_min: Mapped[float | None] = mapped_column(Numeric(14, 2))
    salary_max: Mapped[float | None] = mapped_column(Numeric(14, 2))
    salary_currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    salary_period: Mapped[str] = mapped_column(String(16), default="YEARLY", nullable=False)
    show_salary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    openings: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    description: Mapped[str] = mapped_column(Text, nullable=False)
    responsibilities: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)
    benefits: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)
    education_requirements: Mapped[list[str]] = mapped_column(
        StringArray(), default=list, nullable=False
    )
    certifications: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)

    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, native_enum=False, length=20),
        default=JobStatus.DRAFT,
        nullable=False,
        index=True,
    )
    is_internal_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    application_deadline: Mapped[date | None] = mapped_column(Date, index=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    hiring_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    #: Per-job override of the company ATS weight profile. NULL falls back to the
    #: company profile, then to the platform default.
    ats_weight_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("ats_weight_profiles.id", ondelete="SET NULL")
    )
    #: What the AI extracted from the description, *after* recruiter review. Kept
    #: alongside the normalised skills so the review UI can show provenance.
    ai_analysis: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    ai_analysis_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    # denormalised counters, maintained by the application service
    application_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    company: Mapped[Company] = relationship(back_populates="jobs", lazy="noload")
    skills: Mapped[list[JobSkill]] = relationship(
        back_populates="job", lazy="selectin", cascade="all, delete-orphan"
    )
    screening_questions: Mapped[list[JobScreeningQuestion]] = relationship(
        back_populates="job",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="JobScreeningQuestion.display_order",
    )
    hiring_team: Mapped[list[JobHiringTeamMember]] = relationship(
        back_populates="job", lazy="selectin", cascade="all, delete-orphan"
    )
    applications: Mapped[list[Application]] = relationship(back_populates="job", lazy="noload")

    # ------------------------------------------------------------- helpers
    @property
    def required_skills(self) -> list[str]:
        return [s.name for s in self.skills if s.importance == SkillImportance.REQUIRED]

    @property
    def preferred_skills(self) -> list[str]:
        return [s.name for s in self.skills if s.importance == SkillImportance.PREFERRED]

    @property
    def is_open_for_applications(self) -> bool:
        if self.status != JobStatus.PUBLISHED:
            return False
        if self.application_deadline and self.application_deadline < date.today():
            return False
        return True


class JobSkill(Base, UUIDMixin, TimestampMixin):
    """Normalised skill requirement. ``normalised_name`` is what the ATS matches on."""

    __tablename__ = "job_skills"
    __table_args__ = (Index("ix_job_skills_job_importance", "job_id", "importance"),)

    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    normalised_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    importance: Mapped[SkillImportance] = mapped_column(
        SAEnum(SkillImportance, native_enum=False, length=20),
        default=SkillImportance.REQUIRED,
        nullable=False,
    )
    #: Relative weight inside the skills component (1-5). Lets a recruiter say "React
    #: matters five times more than Git" without touching the global weight profile.
    weight: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    min_years: Mapped[float | None] = mapped_column(Numeric(4, 1))
    category: Mapped[str | None] = mapped_column(String(50))  # TECHNICAL | SOFT | DOMAIN
    source: Mapped[str] = mapped_column(String(20), default="MANUAL", nullable=False)  # MANUAL | AI

    job: Mapped[Job] = relationship(back_populates="skills", lazy="noload")


class JobScreeningQuestion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "screening_questions"

    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[ScreeningQuestionType] = mapped_column(
        SAEnum(ScreeningQuestionType, native_enum=False, length=30), nullable=False
    )
    options: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: Optional automatic scoring. ``{"expected": "YES", "points": 10}`` for YES_NO,
    #: ``{"min": 2, "points": 10}`` for NUMERIC/EXPERIENCE, ``{"max": 30, "points": 5}``
    #: for NOTICE_PERIOD. Evaluated by ``ScreeningService`` - never auto-rejects.
    scoring: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    #: A knockout question surfaces a review flag; it does not reject the candidate.
    is_knockout: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    job: Mapped[Job] = relationship(back_populates="screening_questions", lazy="noload")


class JobHiringTeamMember(Base, UUIDMixin, TimestampMixin):
    """Who works on this job. Drives ``job:read:assigned`` scoping for managers and
    interviewers, and the default interviewer pool."""

    __tablename__ = "job_hiring_team"
    __table_args__ = (Index("ix_job_hiring_team_job_user", "job_id", "user_id", unique=True),)

    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_role: Mapped[str] = mapped_column(String(40), nullable=False)  # RECRUITER|MANAGER|INTERVIEWER

    job: Mapped[Job] = relationship(back_populates="hiring_team", lazy="noload")
