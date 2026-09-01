"""Interview and feedback schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.core.enums import InterviewRecommendation, InterviewStatus, InterviewType
from app.schemas.common import ORMModel, UserRef


class ParticipantOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    role: str
    is_required: bool
    response_status: str
    user: UserRef | None = None


class InterviewCreate(BaseModel):
    application_id: uuid.UUID
    interview_type: InterviewType
    scheduled_start: datetime = Field(description="UTC start time")
    duration_minutes: int = Field(default=60, ge=5, le=480)
    interviewer_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    title: str | None = Field(default=None, max_length=200)
    round_name: str | None = Field(default=None, max_length=100)
    timezone: str = Field(default="UTC", max_length=64)
    meeting_link: str | None = Field(default=None, max_length=512)
    location: str | None = Field(default=None, max_length=255)
    candidate_instructions: str | None = Field(default=None, max_length=5000)
    internal_notes: str | None = Field(
        default=None, max_length=5000, description="Never shown to the candidate"
    )
    send_invitation: bool = True
    create_conference: bool = Field(
        default=False,
        description="Ask the calendar provider to mint a Meet/Teams link (needs an integration)",
    )


class InterviewReschedule(BaseModel):
    scheduled_start: datetime
    duration_minutes: int | None = Field(default=None, ge=5, le=480)
    reason: str | None = Field(default=None, max_length=500)
    notify: bool = True


class InterviewCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
    notify: bool = True


class ApplicationBrief(ORMModel):
    id: uuid.UUID
    reference_code: str
    status: str


class InterviewSummary(ORMModel):
    id: uuid.UUID
    title: str
    round_number: int
    round_name: str | None = None
    interview_type: InterviewType
    status: InterviewStatus
    scheduled_start: datetime
    scheduled_end: datetime
    duration_minutes: int
    timezone: str
    meeting_link: str | None = None
    location: str | None = None
    application_id: uuid.UUID
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_name: str | None = None
    job_title: str | None = None
    organiser_id: uuid.UUID | None = None
    participants: list[ParticipantOut] = Field(default_factory=list)
    feedback_count: int = 0
    created_at: datetime


class CalendarSyncOut(BaseModel):
    """Honest reporting of whether an external calendar actually received this."""

    status: str = Field(
        description="SYNCED | PENDING_NO_PROVIDER | FAILED - PENDING_NO_PROVIDER means "
        "the interview exists in HireHQ only, with no external invitation sent"
    )
    provider: str | None = None
    external_event_id: str | None = None
    detail: str | None = None


class InterviewDetail(InterviewSummary):
    candidate_instructions: str | None = None
    #: Only present for users who may see internal notes.
    internal_notes: str | None = None
    rescheduled_from: datetime | None = None
    reschedule_count: int
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    completed_at: datetime | None = None
    candidate_confirmed_at: datetime | None = None
    reminders_sent: list = Field(default_factory=list)
    calendar_sync: CalendarSyncOut | None = None
    updated_at: datetime


class FeedbackCreate(BaseModel):
    overall_rating: float = Field(ge=1, le=5)
    recommendation: InterviewRecommendation
    technical_skills: int | None = Field(default=None, ge=1, le=5)
    communication: int | None = Field(default=None, ge=1, le=5)
    problem_solving: int | None = Field(default=None, ge=1, le=5)
    domain_knowledge: int | None = Field(default=None, ge=1, le=5)
    culture_fit: int | None = Field(default=None, ge=1, le=5)
    strengths: str | None = Field(default=None, max_length=5000)
    weaknesses: str | None = Field(default=None, max_length=5000)
    comments: str | None = Field(default=None, max_length=10_000)
    private_remarks: str | None = Field(
        default=None,
        max_length=5000,
        description="Visible only to you and company admins. Never shown to the candidate.",
    )
    scorecard: dict = Field(default_factory=dict)
    is_draft: bool = False

    @model_validator(mode="after")
    def _require_reasoning(self) -> FeedbackCreate:
        # A NO_HIRE with no written reasoning is not reviewable, and reviewability is
        # what makes a hiring decision defensible.
        if (
            not self.is_draft
            and self.recommendation == InterviewRecommendation.NO_HIRE
            and not (self.weaknesses or self.comments)
        ):
            raise ValueError(
                "A 'no hire' recommendation needs written reasoning in 'weaknesses' or "
                "'comments'"
            )
        return self


class FeedbackOut(ORMModel):
    id: uuid.UUID
    interview_id: uuid.UUID
    application_id: uuid.UUID
    interviewer_id: uuid.UUID
    interviewer: UserRef | None = None
    overall_rating: float
    recommendation: InterviewRecommendation
    technical_skills: int | None = None
    communication: int | None = None
    problem_solving: int | None = None
    domain_knowledge: int | None = None
    culture_fit: int | None = None
    average_competency: float | None = None
    strengths: str | None = None
    weaknesses: str | None = None
    comments: str | None = None
    #: Omitted unless the caller holds ``feedback:read:private``.
    private_remarks: str | None = None
    scorecard: dict = Field(default_factory=dict)
    ai_summary: str | None = None
    ai_summary_engine: str | None = None
    is_draft: bool
    submitted_at: datetime | None = None
    created_at: datetime


class FeedbackSummaryResponse(BaseModel):
    summary: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    consensus: str | None = None
    engine: str
    feedback_count: int
    disclaimer: str = (
        "AI-generated digest of the interviewers' own written feedback. It is advisory: "
        "the hiring decision belongs to the recruiting team."
    )


class ConflictCheckRequest(BaseModel):
    interviewer_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    scheduled_start: datetime
    duration_minutes: int = Field(default=60, ge=5, le=480)
    exclude_interview_id: uuid.UUID | None = None


class ConflictOut(BaseModel):
    interview_id: uuid.UUID
    interviewer_id: uuid.UUID
    interviewer_name: str
    starts_at: datetime


class ConflictCheckResponse(BaseModel):
    has_conflicts: bool
    conflicts: list[ConflictOut] = Field(default_factory=list)


class CalendarEventOut(ORMModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    location: str | None = None
    meeting_link: str | None = None
    start_at: datetime
    end_at: datetime
    timezone: str
    all_day: bool
    status: str
    sync_status: str
    provider: str | None = None
    interview_id: uuid.UUID | None = None
    attendees: list = Field(default_factory=list)


class CalendarView(BaseModel):
    view: str = Field(description="day | week | month | agenda")
    start: datetime
    end: datetime
    events: list[CalendarEventOut]
    total: int
    #: Warns the UI when no external calendar is connected.
    provider_status: str
