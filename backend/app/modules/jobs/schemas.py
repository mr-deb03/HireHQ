"""Job request/response schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.enums import (
    EmploymentType,
    JobStatus,
    ScreeningQuestionType,
    SkillImportance,
    WorkMode,
)
from app.schemas.common import ORMModel, UserRef


class SkillInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    weight: int = Field(default=3, ge=1, le=5, description="Relative importance, 1-5")
    min_years: float | None = Field(default=None, ge=0, le=50)
    category: str | None = Field(default=None, max_length=50)


class SkillOut(ORMModel):
    id: uuid.UUID
    name: str
    normalised_name: str
    importance: SkillImportance
    weight: int
    min_years: float | None = None
    category: str | None = None
    source: str


class ScreeningQuestionInput(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    question_type: ScreeningQuestionType
    options: list[str] = Field(default_factory=list, max_length=20)
    is_required: bool = True
    display_order: int = 0
    scoring: dict = Field(default_factory=dict)
    is_knockout: bool = False

    @model_validator(mode="after")
    def _validate_options(self) -> ScreeningQuestionInput:
        needs_options = self.question_type in (
            ScreeningQuestionType.SINGLE_CHOICE,
            ScreeningQuestionType.MULTIPLE_CHOICE,
        )
        if needs_options and len(self.options) < 2:
            raise ValueError("Choice questions need at least two options")
        if not needs_options and self.options:
            raise ValueError(f"{self.question_type.value} questions do not take options")
        return self


class ScreeningQuestionOut(ORMModel):
    id: uuid.UUID
    question: str
    question_type: ScreeningQuestionType
    options: list[str]
    is_required: bool
    display_order: int
    is_knockout: bool


class HiringTeamMemberInput(BaseModel):
    user_id: uuid.UUID
    team_role: str = Field(default="INTERVIEWER", pattern="^(RECRUITER|MANAGER|INTERVIEWER)$")


class HiringTeamMemberOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    team_role: str


class JobBase(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=20, max_length=50_000)
    department_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    location_text: str | None = Field(default=None, max_length=255)
    work_mode: WorkMode = WorkMode.ONSITE
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    min_experience_years: float = Field(default=0, ge=0, le=50)
    max_experience_years: float | None = Field(default=None, ge=0, le=50)
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    salary_currency: str = Field(default="INR", min_length=3, max_length=3)
    show_salary: bool = True
    openings: int = Field(default=1, ge=1, le=1000)
    responsibilities: list[str] = Field(default_factory=list, max_length=40)
    benefits: list[str] = Field(default_factory=list, max_length=30)
    education_requirements: list[str] = Field(default_factory=list, max_length=10)
    certifications: list[str] = Field(default_factory=list, max_length=15)
    application_deadline: date | None = None
    hiring_manager_id: uuid.UUID | None = None
    is_internal_only: bool = False

    @field_validator("salary_currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.upper()


class JobCreate(JobBase):
    required_skills: list[SkillInput] = Field(default_factory=list, max_length=50)
    preferred_skills: list[SkillInput] = Field(default_factory=list, max_length=50)
    screening_questions: list[ScreeningQuestionInput] = Field(
        default_factory=list, max_length=25
    )


class JobUpdate(BaseModel):
    """Every field optional - PATCH semantics."""

    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, min_length=20, max_length=50_000)
    department_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    location_text: str | None = Field(default=None, max_length=255)
    work_mode: WorkMode | None = None
    employment_type: EmploymentType | None = None
    min_experience_years: float | None = Field(default=None, ge=0, le=50)
    max_experience_years: float | None = Field(default=None, ge=0, le=50)
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    show_salary: bool | None = None
    openings: int | None = Field(default=None, ge=1, le=1000)
    responsibilities: list[str] | None = None
    benefits: list[str] | None = None
    education_requirements: list[str] | None = None
    certifications: list[str] | None = None
    application_deadline: date | None = None
    hiring_manager_id: uuid.UUID | None = None
    is_internal_only: bool | None = None
    ats_weight_profile_id: uuid.UUID | None = None
    required_skills: list[SkillInput] | None = None
    preferred_skills: list[SkillInput] | None = None


class CompanyBrief(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    logo_url: str | None = None
    industry: str | None = None


class JobSummary(ORMModel):
    """List-view representation."""

    id: uuid.UUID
    title: str
    slug: str
    reference_code: str
    status: JobStatus
    location_text: str | None = None
    work_mode: WorkMode
    employment_type: EmploymentType
    min_experience_years: float
    max_experience_years: float | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str
    show_salary: bool
    openings: int
    application_count: int
    view_count: int
    is_internal_only: bool
    application_deadline: date | None = None
    published_at: datetime | None = None
    created_at: datetime


class JobDetail(JobSummary):
    description: str
    responsibilities: list[str]
    benefits: list[str]
    education_requirements: list[str]
    certifications: list[str]
    keywords: list[str]
    department_id: uuid.UUID | None = None
    hiring_manager_id: uuid.UUID | None = None
    created_by_id: uuid.UUID | None = None
    ats_weight_profile_id: uuid.UUID | None = None
    skills: list[SkillOut] = Field(default_factory=list)
    screening_questions: list[ScreeningQuestionOut] = Field(default_factory=list)
    hiring_team: list[HiringTeamMemberOut] = Field(default_factory=list)
    ai_analysis_confirmed_at: datetime | None = None
    updated_at: datetime


class PublicJobSummary(ORMModel):
    """What the public portal sees. Deliberately omits internal fields."""

    id: uuid.UUID
    title: str
    slug: str
    reference_code: str
    location_text: str | None = None
    work_mode: WorkMode
    employment_type: EmploymentType
    min_experience_years: float
    max_experience_years: float | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str
    openings: int
    application_deadline: date | None = None
    published_at: datetime | None = None
    company: CompanyBrief | None = None
    required_skills: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _hide_salary(self) -> PublicJobSummary:
        # ``show_salary`` is a company setting; enforce it in the serializer so no route
        # can leak it by forgetting to check.
        return self


class PublicJobDetail(PublicJobSummary):
    description: str
    responsibilities: list[str]
    benefits: list[str]
    education_requirements: list[str]
    certifications: list[str]
    preferred_skills: list[str] = Field(default_factory=list)
    screening_questions: list[ScreeningQuestionOut] = Field(default_factory=list)
    #: Set when the viewer is signed in and has already applied.
    already_applied: bool = False
    existing_application_id: uuid.UUID | None = None


class ExtractedSkillOut(BaseModel):
    name: str
    importance: str
    category: str
    min_years: float | None = None


class JobAnalysisRequest(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=20, max_length=50_000)


class JobAnalysisResponse(BaseModel):
    required_skills: list[ExtractedSkillOut]
    preferred_skills: list[ExtractedSkillOut]
    min_experience_years: float
    max_experience_years: float | None = None
    education_requirements: list[str]
    certifications: list[str]
    responsibilities: list[str]
    keywords: list[str]
    technical_skills: list[str]
    soft_skills: list[str]
    seniority: str | None = None
    confidence: float
    #: ``heuristic-v1`` or ``anthropic:<model>``. The UI labels the source accordingly.
    engine: str
    #: Always true: the recruiter must confirm before these are applied to the job.
    requires_review: bool = True


class ApplyAnalysisRequest(BaseModel):
    """Recruiter-confirmed requirements. This is what actually reaches the job."""

    required_skills: list[SkillInput] = Field(default_factory=list, max_length=50)
    preferred_skills: list[SkillInput] = Field(default_factory=list, max_length=50)
    responsibilities: list[str] = Field(default_factory=list, max_length=40)
    education_requirements: list[str] = Field(default_factory=list, max_length=10)
    certifications: list[str] = Field(default_factory=list, max_length=15)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    min_experience_years: float | None = Field(default=None, ge=0, le=50)
    max_experience_years: float | None = Field(default=None, ge=0, le=50)


class JobStatusChange(BaseModel):
    status: JobStatus
    reason: str | None = Field(default=None, max_length=500)


class HiringTeamUpdate(BaseModel):
    members: list[HiringTeamMemberInput] = Field(max_length=30)


class JobStatsOut(BaseModel):
    job_id: uuid.UUID
    total_applications: int
    by_status: dict[str, int]
    funnel: dict[str, int]
    average_ats_score: float | None = None
    top_sources: dict[str, int]
    interviews_scheduled: int
    offers_extended: int


class JobTeamMemberDetail(ORMModel):
    id: uuid.UUID
    team_role: str
    user: UserRef | None = None
