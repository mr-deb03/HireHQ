"""Technical assessments: definitions, questions, attempts and answers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AssessmentAttemptStatus, AssessmentQuestionType
from app.db.base import Base, TenantMixin, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType, StringArray, UTCDateTime

if TYPE_CHECKING:
    from app.models.application import Application


class Assessment(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "assessments"
    __table_args__ = (Index("ix_assessments_company_active", "company_id", "is_active"),)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    #: TECHNICAL | APTITUDE | CODING | SQL | MIXED
    category: Mapped[str] = mapped_column(String(30), default="MIXED", nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    passing_score: Mapped[float] = mapped_column(Numeric(5, 2), default=60, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    randomise_questions: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )

    questions: Mapped[list[AssessmentQuestion]] = relationship(
        back_populates="assessment",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="AssessmentQuestion.display_order",
    )

    @property
    def total_points(self) -> float:
        return float(sum(q.points for q in self.questions))


class AssessmentQuestion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "assessment_questions"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_type: Mapped[AssessmentQuestionType] = mapped_column(
        SAEnum(AssessmentQuestionType, native_enum=False, length=20), nullable=False
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    points: Mapped[float] = mapped_column(Numeric(6, 2), default=1, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), default="MEDIUM", nullable=False)

    #: For MCQ types. ``[{"id": "a", "text": "..."}, ...]``
    options: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    #: Option ids that are correct. Never serialised to a candidate.
    correct_options: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)

    # coding / SQL
    starter_code: Mapped[str | None] = mapped_column(Text)
    allowed_languages: Mapped[list[str]] = mapped_column(
        StringArray(), default=list, nullable=False
    )
    #: ``[{"input": "...", "expected_output": "...", "is_hidden": true, "weight": 1}]``
    #: Hidden cases are stripped from every candidate-facing response.
    test_cases: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)

    assessment: Mapped[Assessment] = relationship(back_populates="questions", lazy="noload")


class JobAssessment(Base, UUIDMixin, TimestampMixin):
    """Attaches an assessment to a job, optionally gated on a pipeline stage."""

    __tablename__ = "job_assessments"
    __table_args__ = (
        Index("ix_job_assessments_job_assessment", "job_id", "assessment_id", unique=True),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: Sent automatically when an application reaches this status.
    trigger_status: Mapped[str | None] = mapped_column(String(30))
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AssessmentAttempt(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "assessment_attempts"
    __table_args__ = (
        Index("ix_assessment_attempts_app_assessment", "application_id", "assessment_id"),
        Index("ix_assessment_attempts_company_status", "company_id", "status"),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )

    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[AssessmentAttemptStatus] = mapped_column(
        SAEnum(AssessmentAttemptStatus, native_enum=False, length=20),
        default=AssessmentAttemptStatus.NOT_STARTED,
        nullable=False,
        index=True,
    )
    #: Single-use token embedded in the candidate's invitation link.
    access_token_hash: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    invited_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer)

    score: Mapped[float | None] = mapped_column(Numeric(6, 2))
    max_score: Mapped[float | None] = mapped_column(Numeric(6, 2))
    percentage: Mapped[float | None] = mapped_column(Numeric(5, 2), index=True)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    #: Question ids that need a human to grade them (free text, coding without a runner).
    pending_manual_review: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)

    answers: Mapped[list[AssessmentAnswer]] = relationship(
        back_populates="attempt", lazy="selectin", cascade="all, delete-orphan"
    )
    application: Mapped[Application] = relationship(lazy="noload")


class AssessmentAnswer(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "assessment_answers"
    __table_args__ = (
        Index("ix_assessment_answers_attempt_question", "attempt_id", "question_id", unique=True),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("assessment_attempts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("assessment_questions.id", ondelete="CASCADE"), nullable=False
    )

    selected_options: Mapped[list[str]] = mapped_column(
        StringArray(), default=list, nullable=False
    )
    answer_text: Mapped[str | None] = mapped_column(Text)
    code_submission: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(30))

    points_awarded: Mapped[float | None] = mapped_column(Numeric(6, 2))
    points_possible: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    #: Per-test-case results when a code runner is configured. Empty when the submission
    #: is stored for human review instead - the API never invents a pass/fail.
    test_results: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    graded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    grader_comment: Mapped[str | None] = mapped_column(Text)
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer)

    attempt: Mapped[AssessmentAttempt] = relationship(back_populates="answers", lazy="noload")
