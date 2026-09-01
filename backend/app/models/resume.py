"""Resume files and the structured data extracted from them."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ResumeStatus
from app.db.base import Base, TenantMixin, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType, UTCDateTime

if TYPE_CHECKING:
    from app.models.candidate import Candidate


class Resume(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """The uploaded file plus its processing state.

    The original binary always stays in object storage; only extracted text and derived
    structure live in PostgreSQL.
    """

    __tablename__ = "resumes"
    __table_args__ = (
        Index("ix_resumes_candidate_created", "candidate_id", "created_at"),
        Index("ix_resumes_company_status", "company_id", "status"),
        Index("ix_resumes_checksum", "company_id", "checksum_sha256"),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Exact-duplicate detection and "same file re-uploaded" review flags.
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    status: Mapped[ResumeStatus] = mapped_column(
        SAEnum(ResumeStatus, native_enum=False, length=20),
        default=ResumeStatus.UPLOADED,
        nullable=False,
        index=True,
    )
    status_detail: Mapped[str | None] = mapped_column(String(500))
    processing_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    processing_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    processing_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    scan_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    scan_engine: Mapped[str | None] = mapped_column(String(40))
    scan_detail: Mapped[str | None] = mapped_column(String(255))

    #: Plain text extracted from the document. Treated as sensitive: never logged, and
    #: only exposed through endpoints that require ``candidate:document:read``.
    extracted_text: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    word_count: Mapped[int | None] = mapped_column(Integer)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    candidate: Mapped[Candidate] = relationship(back_populates="resumes", lazy="noload")
    analysis: Mapped[ResumeAnalysis | None] = relationship(
        back_populates="resume", lazy="selectin", cascade="all, delete-orphan", uselist=False
    )


class ResumeAnalysis(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """Structured output of the parsing pipeline for one resume.

    Keeping this separate from ``Resume`` means re-parsing (a better model, a fixed bug)
    replaces the analysis without touching the immutable file record.
    """

    __tablename__ = "resume_analysis"

    resume_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    # identity as read from the document (may differ from what the candidate typed)
    parsed_name: Mapped[str | None] = mapped_column(String(200))
    parsed_email: Mapped[str | None] = mapped_column(String(320))
    parsed_phone: Mapped[str | None] = mapped_column(String(64))
    parsed_location: Mapped[str | None] = mapped_column(String(255))
    parsed_linkedin: Mapped[str | None] = mapped_column(String(512))
    parsed_github: Mapped[str | None] = mapped_column(String(512))
    parsed_portfolio: Mapped[str | None] = mapped_column(String(512))

    #: Normalised structures: ``skills``, ``experience``, ``education``,
    #: ``certifications``, ``projects``, ``achievements``, ``languages``.
    #: Shapes are validated against ``app.modules.resumes.schemas.ParsedResume``.
    skills: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    experience: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    education: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    certifications: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    projects: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    achievements: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    languages: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)

    total_experience_years: Mapped[float | None] = mapped_column(Numeric(4, 1))
    current_designation: Mapped[str | None] = mapped_column(String(200))
    current_company: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)

    #: 0-1 self-reported confidence. Below the configured floor the candidate record is
    #: flagged ``RESUME_PARSE_LOW_CONFIDENCE`` so a human reviews the extraction.
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), default=0, nullable=False)
    #: Which implementation produced this: e.g. ``heuristic-v1`` or ``anthropic:claude-opus-5``.
    parser_engine: Mapped[str] = mapped_column(String(60), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(20), default="1", nullable=False)
    #: Fields the parser could not find, driving the "missing information" review flag.
    missing_fields: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    warnings: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)

    resume: Mapped[Resume] = relationship(back_populates="analysis", lazy="noload")
