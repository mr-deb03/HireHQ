"""Interviews, participants and structured feedback."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import InterviewRecommendation, InterviewStatus, InterviewType
from app.db.base import Base, TenantMixin, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType, UTCDateTime

if TYPE_CHECKING:
    from app.models.application import Application


class Interview(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "interviews"
    __table_args__ = (
        Index("ix_interviews_company_scheduled", "company_id", "scheduled_start"),
        Index("ix_interviews_application_round", "application_id", "round_number"),
        Index("ix_interviews_company_status", "company_id", "status"),
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

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    round_name: Mapped[str | None] = mapped_column(String(100))
    interview_type: Mapped[InterviewType] = mapped_column(
        SAEnum(InterviewType, native_enum=False, length=20), nullable=False, index=True
    )
    status: Mapped[InterviewStatus] = mapped_column(
        SAEnum(InterviewStatus, native_enum=False, length=20),
        default=InterviewStatus.SCHEDULED,
        nullable=False,
        index=True,
    )

    scheduled_start: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    scheduled_end: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)

    meeting_link: Mapped[str | None] = mapped_column(String(512))
    location: Mapped[str | None] = mapped_column(String(255))
    #: Instructions shown to the candidate in the invitation.
    candidate_instructions: Mapped[str | None] = mapped_column(Text)
    #: Internal notes - never included in candidate-facing emails or API responses.
    internal_notes: Mapped[str | None] = mapped_column(Text)

    organiser_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # An interview points at the calendar event it created, and the event points back at
    # the interview - a reference cycle. See the note on Application.referral_id.
    calendar_event_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("calendar_events.id", ondelete="SET NULL", use_alter=True)
    )

    rescheduled_from: Mapped[datetime | None] = mapped_column(UTCDateTime())
    reschedule_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancellation_reason: Mapped[str | None] = mapped_column(String(255))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    candidate_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    #: Which reminder offsets have already fired, so the reminder job is idempotent
    #: e.g. ``[1440, 60]`` for the 24h and 1h reminders.
    reminders_sent: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)

    application: Mapped[Application] = relationship(lazy="joined")
    participants: Mapped[list[InterviewParticipant]] = relationship(
        back_populates="interview", lazy="selectin", cascade="all, delete-orphan"
    )
    feedback: Mapped[list[InterviewFeedback]] = relationship(
        back_populates="interview", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def interviewer_ids(self) -> list[uuid.UUID]:
        return [p.user_id for p in self.participants if p.user_id and p.role != "OBSERVER"]

    @property
    def is_upcoming(self) -> bool:
        return self.status in (InterviewStatus.SCHEDULED, InterviewStatus.CONFIRMED)


class InterviewParticipant(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "interview_participants"
    __table_args__ = (
        Index("ix_interview_participants_interview_user", "interview_id", "user_id", unique=True),
        Index("ix_interview_participants_user", "user_id"),
    )

    interview_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    #: INTERVIEWER | ORGANISER | OBSERVER
    role: Mapped[str] = mapped_column(String(20), default="INTERVIEWER", nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    response_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    interview: Mapped[Interview] = relationship(back_populates="participants", lazy="noload")


class InterviewFeedback(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """One interviewer's evaluation. Candidates never see any of it."""

    __tablename__ = "interview_feedback"
    __table_args__ = (
        Index("ix_interview_feedback_interview_user", "interview_id", "interviewer_id", unique=True),
        Index("ix_interview_feedback_application", "application_id"),
    )

    interview_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    interviewer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 1-5 competency ratings
    technical_skills: Mapped[int | None] = mapped_column(Integer)
    communication: Mapped[int | None] = mapped_column(Integer)
    problem_solving: Mapped[int | None] = mapped_column(Integer)
    domain_knowledge: Mapped[int | None] = mapped_column(Integer)
    culture_fit: Mapped[int | None] = mapped_column(Integer)
    overall_rating: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)

    recommendation: Mapped[InterviewRecommendation] = mapped_column(
        SAEnum(InterviewRecommendation, native_enum=False, length=20), nullable=False, index=True
    )

    strengths: Mapped[str | None] = mapped_column(Text)
    weaknesses: Mapped[str | None] = mapped_column(Text)
    comments: Mapped[str | None] = mapped_column(Text)
    #: Visible only to the author, company admins and users with
    #: ``feedback:read:private``. Excluded from every candidate-facing serializer.
    private_remarks: Mapped[str | None] = mapped_column(Text)

    #: Free-form per-skill scores when the round uses a custom scorecard.
    scorecard: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    #: AI-generated digest of this feedback. Advisory only; the recommendation above is
    #: always the interviewer's own.
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_summary_engine: Mapped[str | None] = mapped_column(String(60))

    interview: Mapped[Interview] = relationship(back_populates="feedback", lazy="noload")

    @property
    def average_competency(self) -> float | None:
        values = [
            v
            for v in (
                self.technical_skills,
                self.communication,
                self.problem_solving,
                self.domain_knowledge,
                self.culture_fit,
            )
            if v is not None
        ]
        return round(sum(values) / len(values), 2) if values else None
