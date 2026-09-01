"""Application request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.core.enums import ApplicationSource, ApplicationStatus
from app.schemas.common import ORMModel, UserRef


# ------------------------------------------------------------------ applying
class ScreeningAnswerInput(BaseModel):
    question_id: uuid.UUID
    answer_text: str | None = Field(default=None, max_length=5000)
    answer_number: float | None = None
    answer_boolean: bool | None = None
    answer_options: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _at_least_one(self) -> ScreeningAnswerInput:
        if not any(
            [
                self.answer_text,
                self.answer_number is not None,
                self.answer_boolean is not None,
                self.answer_options,
            ]
        ):
            raise ValueError("An answer is required")
        return self


class ApplyRequest(BaseModel):
    """The multi-step application form, submitted as one payload (s11).

    The frontend collects it across steps; the API accepts it whole so a partially
    submitted application can never exist in the database.
    """

    # Step 1 - personal
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=32)
    location: str | None = Field(default=None, max_length=255)

    # Step 2 - professional
    current_designation: str | None = Field(default=None, max_length=200)
    current_company: str | None = Field(default=None, max_length=200)
    total_experience_years: float | None = Field(default=None, ge=0, le=60)
    expected_salary: float | None = Field(default=None, ge=0)
    notice_period_days: int | None = Field(default=None, ge=0, le=365)
    linkedin_url: str | None = Field(default=None, max_length=512)
    github_url: str | None = Field(default=None, max_length=512)
    portfolio_url: str | None = Field(default=None, max_length=512)

    # Step 3 - education (optional at apply time; the resume usually supplies it)
    highest_qualification: str | None = Field(default=None, max_length=200)
    institution: str | None = Field(default=None, max_length=255)
    graduation_year: int | None = Field(default=None, ge=1950, le=2100)

    # Step 5 - screening answers
    screening_answers: list[ScreeningAnswerInput] = Field(
        default_factory=list, max_length=30
    )

    cover_letter: str | None = Field(default=None, max_length=10_000)

    # Step 6 - consent
    consent_given: bool = Field(
        description="Consent to store and process the application. Required."
    )
    privacy_policy_accepted: bool = Field(default=True)

    @model_validator(mode="after")
    def _require_consent(self) -> ApplyRequest:
        if not self.consent_given:
            raise ValueError(
                "Consent to process your application data is required to apply"
            )
        return self


class ApplyResponse(BaseModel):
    application_id: uuid.UUID
    reference_code: str
    status: ApplicationStatus
    candidate_id: uuid.UUID
    resume_uploaded: bool
    #: True when resume parsing and ATS scoring have been queued.
    processing_queued: bool
    message: str
    track_url: str


# ------------------------------------------------------------------ reading
class JobBrief(ORMModel):
    id: uuid.UUID
    title: str
    reference_code: str
    location_text: str | None = None
    department_id: uuid.UUID | None = None


class CandidateBrief(ORMModel):
    id: uuid.UUID
    full_name: str
    email: EmailStr
    phone: str | None = None
    location: str | None = None
    photo_url: str | None = None
    current_designation: str | None = None
    current_company: str | None = None
    total_experience_years: float
    notice_period_days: int | None = None
    email_verified: bool


class ApplicationSummary(ORMModel):
    id: uuid.UUID
    reference_code: str
    status: ApplicationStatus
    source: ApplicationSource
    source_detail: str | None = None
    ats_score: float | None = None
    ats_rank: int | None = None
    screening_score: float | None = None
    stage_position: int
    tags: list[str] = Field(default_factory=list)
    assigned_recruiter_id: uuid.UUID | None = None
    created_at: datetime
    status_changed_at: datetime | None = None
    job: JobBrief | None = None
    candidate: CandidateBrief | None = None


class ScreeningAnswerOut(ORMModel):
    id: uuid.UUID
    question_id: uuid.UUID
    question_snapshot: str
    answer_text: str | None = None
    answer_number: float | None = None
    answer_boolean: bool | None = None
    answer_options: list[str] = Field(default_factory=list)
    points_awarded: float | None = None
    points_possible: float | None = None
    knockout_triggered: bool


class ApplicationDetail(ApplicationSummary):
    cover_letter: str | None = None
    expected_salary: float | None = None
    notice_period_days: int | None = None
    rejection_reason: str | None = None
    resume_id: uuid.UUID | None = None
    referral_id: uuid.UUID | None = None
    utm: dict = Field(default_factory=dict)
    consent_given_at: datetime | None = None
    withdrawn_at: datetime | None = None
    shortlisted_at: datetime | None = None
    interviewed_at: datetime | None = None
    offered_at: datetime | None = None
    hired_at: datetime | None = None
    last_automated_action_at: datetime | None = None
    screening_answers: list[ScreeningAnswerOut] = Field(default_factory=list)
    #: Statuses this application may move to next, for the UI to render.
    allowed_transitions: list[str] = Field(default_factory=list)
    updated_at: datetime


class TimelineEventOut(ORMModel):
    id: uuid.UUID
    event_type: str
    title: str
    description: str | None = None
    previous_status: ApplicationStatus | None = None
    new_status: ApplicationStatus | None = None
    actor_type: str
    actor: UserRef | None = None
    is_visible_to_candidate: bool
    meta: dict = Field(default_factory=dict)
    created_at: datetime


class StatusChangeRequest(BaseModel):
    status: ApplicationStatus
    reason: str | None = Field(default=None, max_length=500)
    send_email: bool = Field(
        default=False, description="Send the status-change email to the candidate"
    )
    custom_message: str | None = Field(default=None, max_length=2000)


class BulkStatusRequest(BaseModel):
    application_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    status: ApplicationStatus
    reason: str | None = Field(default=None, max_length=500)
    send_email: bool = False


class BulkAssignRequest(BaseModel):
    application_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    recruiter_id: uuid.UUID


class BulkTagRequest(BaseModel):
    application_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    tags: list[str] = Field(min_length=1, max_length=10)
    mode: str = Field(default="add", pattern="^(add|remove|replace)$")


class BulkEmailRequest(BaseModel):
    application_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    template_key: str
    custom_message: str | None = Field(default=None, max_length=2000)


class BulkTalentPoolRequest(BaseModel):
    application_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    pool_id: uuid.UUID | None = None
    pool_name: str | None = Field(default=None, max_length=150)

    @model_validator(mode="after")
    def _need_pool(self) -> BulkTalentPoolRequest:
        if not self.pool_id and not self.pool_name:
            raise ValueError("Provide pool_id or pool_name")
        return self


class KanbanCard(BaseModel):
    id: uuid.UUID
    reference_code: str
    candidate_id: uuid.UUID
    candidate_name: str
    candidate_photo_url: str | None = None
    current_designation: str | None = None
    ats_score: float | None = None
    ats_rank: int | None = None
    total_experience_years: float
    notice_period_days: int | None = None
    tags: list[str] = Field(default_factory=list)
    stage_position: int
    has_pending_feedback: bool = False
    applied_at: datetime


class KanbanColumn(BaseModel):
    status: ApplicationStatus
    label: str
    count: int
    cards: list[KanbanCard]


class KanbanBoard(BaseModel):
    job_id: uuid.UUID | None = None
    columns: list[KanbanColumn]
    total: int


class MoveCardRequest(BaseModel):
    status: ApplicationStatus
    position: int = Field(default=0, ge=0)
    send_email: bool = False


class WithdrawRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class CandidateApplicationView(ORMModel):
    """What a candidate sees about their own application - no internal fields."""

    id: uuid.UUID
    reference_code: str
    #: Friendly label, not the raw internal status.
    status_label: str
    applied_at: datetime
    last_updated: datetime
    job_title: str
    company_name: str
    location: str | None = None
    can_withdraw: bool
    #: Only candidate-visible timeline entries.
    timeline: list[TimelineEventOut] = Field(default_factory=list)
