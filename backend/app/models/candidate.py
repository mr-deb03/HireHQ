"""Candidate records and their normalised profile data.

A ``Candidate`` is **company-scoped**: it is one company's record of a person. The same
human applying to two companies gets two candidate rows (tenant isolation, s46) but only
ever one row *inside* a company no matter how many of its jobs they apply to (duplicate
detection, s32). Their optional ``user_id`` links back to the single global login.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DocumentType
from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType, StringArray, UTCDateTime

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.resume import Resume


class Candidate(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "candidates"
    __table_args__ = (
        # The dedup key: one candidate per email per company.
        Index("ix_candidates_company_email", "company_id", "email", unique=True),
        Index("ix_candidates_company_phone", "company_id", "phone"),
        Index("ix_candidates_company_created", "company_id", "created_at"),
        Index("ix_candidates_company_experience", "company_id", "total_experience_years"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    # ------------------------------------------------------------- personal
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    location: Mapped[str | None] = mapped_column(String(255), index=True)
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    country: Mapped[str | None] = mapped_column(String(120))
    photo_url: Mapped[str | None] = mapped_column(String(512))
    date_of_birth: Mapped[date | None] = mapped_column(Date)

    # --------------------------------------------------------- professional
    headline: Mapped[str | None] = mapped_column(String(255))
    current_designation: Mapped[str | None] = mapped_column(String(200), index=True)
    current_company: Mapped[str | None] = mapped_column(String(200))
    total_experience_years: Mapped[float] = mapped_column(Numeric(4, 1), default=0, nullable=False)
    expected_salary: Mapped[float | None] = mapped_column(Numeric(14, 2))
    current_salary: Mapped[float | None] = mapped_column(Numeric(14, 2))
    salary_currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    notice_period_days: Mapped[int | None] = mapped_column(Integer, index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    #: Short AI-generated profile summary. Always labelled as AI-generated in the UI.
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_summary_generated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    # ------------------------------------------------------------------ links
    linkedin_url: Mapped[str | None] = mapped_column(String(512))
    github_url: Mapped[str | None] = mapped_column(String(512))
    portfolio_url: Mapped[str | None] = mapped_column(String(512))
    other_links: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)

    # ------------------------------------------------- verification & review
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Objective signals only (see ``VerificationSignal``). Never a trust judgement.
    verification_signals: Mapped[list[str]] = mapped_column(
        StringArray(), default=list, nullable=False
    )
    #: Items for a human to look at (see ``ReviewFlag``). Never auto-rejects.
    review_flags: Mapped[list[dict]] = mapped_column(JSONType(), default=list, nullable=False)

    # --------------------------------------------------------------- consent
    consent_given_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    consent_version: Mapped[str | None] = mapped_column(String(20))
    privacy_policy_accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    #: When retention expires this record becomes eligible for anonymisation.
    retention_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)

    tags: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)
    source: Mapped[str | None] = mapped_column(String(50), index=True)
    is_internal_employee: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    skills: Mapped[list[CandidateSkill]] = relationship(
        back_populates="candidate", lazy="selectin", cascade="all, delete-orphan"
    )
    education: Mapped[list[CandidateEducation]] = relationship(
        back_populates="candidate",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="desc(CandidateEducation.end_year)",
    )
    experience: Mapped[list[CandidateExperience]] = relationship(
        back_populates="candidate",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="desc(CandidateExperience.start_date)",
    )
    documents: Mapped[list[CandidateDocument]] = relationship(
        back_populates="candidate", lazy="noload", cascade="all, delete-orphan"
    )
    notes: Mapped[list[CandidateNote]] = relationship(
        back_populates="candidate", lazy="noload", cascade="all, delete-orphan"
    )
    resumes: Mapped[list[Resume]] = relationship(
        back_populates="candidate", lazy="noload", cascade="all, delete-orphan"
    )
    applications: Mapped[list[Application]] = relationship(
        back_populates="candidate", lazy="noload"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def skill_names(self) -> list[str]:
        return [s.name for s in self.skills]


class CandidateSkill(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "candidate_skills"
    __table_args__ = (
        Index("ix_candidate_skills_candidate_norm", "candidate_id", "normalised_name", unique=True),
        Index("ix_candidate_skills_norm", "normalised_name"),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    normalised_name: Mapped[str] = mapped_column(String(120), nullable=False)
    years_experience: Mapped[float | None] = mapped_column(Numeric(4, 1))
    proficiency: Mapped[str | None] = mapped_column(String(20))
    category: Mapped[str | None] = mapped_column(String(50))
    #: RESUME | MANUAL | AI - lets the UI show where a skill came from.
    source: Mapped[str] = mapped_column(String(20), default="MANUAL", nullable=False)

    candidate: Mapped[Candidate] = relationship(back_populates="skills", lazy="noload")


class CandidateEducation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "candidate_education"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    degree: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Normalised ladder rung used by ATS education matching (see ``ats.education``).
    degree_level: Mapped[str | None] = mapped_column(String(30), index=True)
    field_of_study: Mapped[str | None] = mapped_column(String(200))
    institution: Mapped[str | None] = mapped_column(String(255))
    university: Mapped[str | None] = mapped_column(String(255))
    start_year: Mapped[int | None] = mapped_column(Integer)
    end_year: Mapped[int | None] = mapped_column(Integer)
    grade: Mapped[str | None] = mapped_column(String(50))
    is_currently_studying: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="MANUAL", nullable=False)

    candidate: Mapped[Candidate] = relationship(back_populates="education", lazy="noload")


class CandidateExperience(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "candidate_experience"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[str] = mapped_column(String(200), nullable=False)
    employment_type: Mapped[str | None] = mapped_column(String(30))
    location: Mapped[str | None] = mapped_column(String(255))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    responsibilities: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)
    technologies: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="MANUAL", nullable=False)

    candidate: Mapped[Candidate] = relationship(back_populates="experience", lazy="noload")

    @property
    def duration_months(self) -> int:
        if not self.start_date:
            return 0
        end = self.end_date or date.today()
        return max(0, (end.year - self.start_date.year) * 12 + (end.month - self.start_date.month))


class CandidateDocument(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """A stored file. Only ever served through a short-lived signed URL."""

    __tablename__ = "candidate_documents"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type: Mapped[DocumentType] = mapped_column(
        SAEnum(DocumentType, native_enum=False, length=30), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    scan_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    scan_detail: Mapped[str | None] = mapped_column(String(255))
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    #: Onboarding/offer documents are restricted beyond normal candidate:read.
    is_confidential: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    candidate: Mapped[Candidate] = relationship(back_populates="documents", lazy="noload")


class CandidateNote(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """Internal recruiter note. Never visible to the candidate."""

    __tablename__ = "candidate_notes"
    __table_args__ = (Index("ix_candidate_notes_candidate_created", "candidate_id", "created_at"),)

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: Private notes are visible only to their author and company admins.
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    candidate: Mapped[Candidate] = relationship(back_populates="notes", lazy="noload")
