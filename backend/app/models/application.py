"""Applications, their immutable timeline and screening answers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ApplicationSource, ApplicationStatus
from app.db.base import Base, TenantMixin, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType, StringArray, UTCDateTime

if TYPE_CHECKING:
    from app.models.ats import AtsScore
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.models.resume import Resume


class Application(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "applications"
    __table_args__ = (
        # One live application per candidate per job. Re-applying after a rejection is
        # handled by the service (it reopens rather than inserting a duplicate).
        Index("ix_applications_job_candidate", "job_id", "candidate_id", unique=True),
        Index("ix_applications_company_status", "company_id", "status"),
        Index("ix_applications_job_status", "job_id", "status"),
        Index("ix_applications_company_created", "company_id", "created_at"),
        Index("ix_applications_job_score", "job_id", "ats_score"),
        Index("ix_applications_source", "company_id", "source"),
    )

    reference_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("resumes.id", ondelete="SET NULL"), index=True
    )

    status: Mapped[ApplicationStatus] = mapped_column(
        SAEnum(ApplicationStatus, native_enum=False, length=30),
        default=ApplicationStatus.APPLIED,
        nullable=False,
        index=True,
    )
    #: Kanban ordering within a status column.
    stage_position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    source: Mapped[ApplicationSource] = mapped_column(
        SAEnum(ApplicationSource, native_enum=False, length=30),
        default=ApplicationSource.DIRECT,
        nullable=False,
    )
    #: The raw ``?source=`` value plus any UTM parameters, for source analytics (s40).
    source_detail: Mapped[str | None] = mapped_column(String(120))
    utm: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    referral_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("referrals.id", ondelete="SET NULL")
    )

    #: Denormalised copy of the latest ATS score. The authoritative, versioned record
    #: with its full breakdown lives in ``ats_scores``; this column exists so ranking,
    #: sorting and filtering are a single-table index scan.
    ats_score: Mapped[float | None] = mapped_column(Numeric(5, 2), index=True)
    ats_rank: Mapped[int | None] = mapped_column(Integer)
    screening_score: Mapped[float | None] = mapped_column(Numeric(5, 2))

    cover_letter: Mapped[str | None] = mapped_column(Text)
    expected_salary: Mapped[float | None] = mapped_column(Numeric(14, 2))
    notice_period_days: Mapped[int | None] = mapped_column(Integer)
    available_from: Mapped[datetime | None] = mapped_column(UTCDateTime())

    assigned_recruiter_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(255))
    #: Set when a workflow (not a human) moved this application, so the UI can label it
    #: and a recruiter can always see that a decision was automation-assisted.
    last_automated_action_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    consent_given_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    withdrawn_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    tags: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)

    # stage timing, for time-in-stage and time-to-hire analytics
    status_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    shortlisted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    interviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    offered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    hired_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    job: Mapped[Job] = relationship(back_populates="applications", lazy="joined")
    candidate: Mapped[Candidate] = relationship(back_populates="applications", lazy="joined")
    resume: Mapped[Resume | None] = relationship(lazy="noload", foreign_keys=[resume_id])
    timeline: Mapped[list[ApplicationTimelineEvent]] = relationship(
        back_populates="application",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="ApplicationTimelineEvent.created_at",
    )
    screening_answers: Mapped[list[ScreeningAnswer]] = relationship(
        back_populates="application", lazy="selectin", cascade="all, delete-orphan"
    )
    ats_scores: Mapped[list[AtsScore]] = relationship(
        back_populates="application",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="desc(AtsScore.created_at)",
    )


class ApplicationTimelineEvent(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """Append-only history of everything that happened to an application.

    Rows are never updated or deleted by application code; ``AuditService`` and the
    pipeline service only insert. This is what makes the candidate timeline (s21) and
    the audit trail trustworthy.
    """

    __tablename__ = "application_timeline"
    __table_args__ = (
        Index("ix_application_timeline_app_created", "application_id", "created_at"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    previous_status: Mapped[ApplicationStatus | None] = mapped_column(
        SAEnum(ApplicationStatus, native_enum=False, length=30)
    )
    new_status: Mapped[ApplicationStatus | None] = mapped_column(
        SAEnum(ApplicationStatus, native_enum=False, length=30)
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    #: USER | SYSTEM | WORKFLOW | AI - the candidate-facing timeline hides internal
    #: events, and the recruiter view labels automated ones.
    actor_type: Mapped[str] = mapped_column(String(20), default="USER", nullable=False)
    #: Whether the candidate may see this event on their own tracking page.
    is_visible_to_candidate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)

    application: Mapped[Application] = relationship(back_populates="timeline", lazy="noload")


class ScreeningAnswer(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "screening_answers"
    __table_args__ = (
        Index("ix_screening_answers_app_question", "application_id", "question_id", unique=True),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("screening_questions.id", ondelete="CASCADE"), nullable=False
    )
    #: Snapshot of the question text at answer time - questions can be edited later and
    #: the recruiter must always see what the candidate was actually asked.
    question_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text)
    answer_number: Mapped[float | None] = mapped_column(Numeric(14, 2))
    answer_boolean: Mapped[bool | None] = mapped_column(Boolean)
    answer_options: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)

    points_awarded: Mapped[float | None] = mapped_column(Numeric(6, 2))
    points_possible: Mapped[float | None] = mapped_column(Numeric(6, 2))
    #: True when a knockout question was answered outside the expected range. Surfaces a
    #: review flag for a human - it never rejects the application on its own.
    knockout_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    application: Mapped[Application] = relationship(
        back_populates="screening_answers", lazy="noload"
    )
