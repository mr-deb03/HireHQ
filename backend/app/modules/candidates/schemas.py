"""Candidate request/response schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.schemas.common import ORMModel, UserRef


class SkillItem(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    years_experience: float | None = Field(default=None, ge=0, le=60)
    proficiency: str | None = Field(default=None, max_length=20)
    category: str | None = Field(default=None, max_length=50)


class SkillOut(ORMModel):
    id: uuid.UUID
    name: str
    normalised_name: str
    years_experience: float | None = None
    proficiency: str | None = None
    category: str | None = None
    source: str


class EducationItem(BaseModel):
    degree: str = Field(min_length=1, max_length=200)
    degree_level: str | None = Field(default=None, max_length=30)
    field_of_study: str | None = Field(default=None, max_length=200)
    institution: str | None = Field(default=None, max_length=255)
    university: str | None = Field(default=None, max_length=255)
    start_year: int | None = Field(default=None, ge=1950, le=2100)
    end_year: int | None = Field(default=None, ge=1950, le=2100)
    grade: str | None = Field(default=None, max_length=50)
    is_currently_studying: bool = False

    @model_validator(mode="after")
    def _check_years(self) -> EducationItem:
        if self.start_year and self.end_year and self.end_year < self.start_year:
            raise ValueError("The end year cannot be before the start year")
        return self


class EducationOut(EducationItem, ORMModel):
    id: uuid.UUID
    source: str


class ExperienceItem(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    position: str = Field(min_length=1, max_length=200)
    employment_type: str | None = Field(default=None, max_length=30)
    location: str | None = Field(default=None, max_length=255)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False
    responsibilities: list[str] = Field(default_factory=list, max_length=25)
    technologies: list[str] = Field(default_factory=list, max_length=30)
    description: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def _check_dates(self) -> ExperienceItem:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("The end date cannot be before the start date")
        if self.is_current and self.end_date:
            raise ValueError("A current role cannot have an end date")
        return self


class ExperienceOut(ExperienceItem, ORMModel):
    id: uuid.UUID
    source: str


class ReviewFlagOut(BaseModel):
    code: str
    message: str
    raised_at: str | None = None
    resolved: bool = False
    resolved_at: str | None = None


class CandidateSummaryOut(ORMModel):
    """List-view representation."""

    id: uuid.UUID
    first_name: str
    last_name: str
    full_name: str
    email: EmailStr
    phone: str | None = None
    location: str | None = None
    photo_url: str | None = None
    headline: str | None = None
    current_designation: str | None = None
    current_company: str | None = None
    total_experience_years: float
    notice_period_days: int | None = None
    expected_salary: float | None = None
    salary_currency: str
    email_verified: bool
    phone_verified: bool
    tags: list[str] = Field(default_factory=list)
    source: str | None = None
    is_internal_employee: bool
    created_at: datetime
    skills: list[SkillOut] = Field(default_factory=list)


class CandidateDetail(CandidateSummaryOut):
    date_of_birth: date | None = None
    city: str | None = None
    country: str | None = None
    current_salary: float | None = None
    summary: str | None = None
    ai_summary: str | None = None
    ai_summary_generated_at: datetime | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    other_links: dict = Field(default_factory=dict)
    verification_signals: list[str] = Field(default_factory=list)
    review_flags: list[ReviewFlagOut] = Field(default_factory=list)
    consent_given_at: datetime | None = None
    retention_expires_at: datetime | None = None
    user_id: uuid.UUID | None = None
    education: list[EducationOut] = Field(default_factory=list)
    experience: list[ExperienceOut] = Field(default_factory=list)
    updated_at: datetime


class CandidateUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    location: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    photo_url: str | None = Field(default=None, max_length=512)
    headline: str | None = Field(default=None, max_length=255)
    current_designation: str | None = Field(default=None, max_length=200)
    current_company: str | None = Field(default=None, max_length=200)
    total_experience_years: float | None = Field(default=None, ge=0, le=60)
    expected_salary: float | None = Field(default=None, ge=0)
    current_salary: float | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    notice_period_days: int | None = Field(default=None, ge=0, le=365)
    summary: str | None = Field(default=None, max_length=5000)
    linkedin_url: str | None = Field(default=None, max_length=512)
    github_url: str | None = Field(default=None, max_length=512)
    portfolio_url: str | None = Field(default=None, max_length=512)
    tags: list[str] | None = Field(default=None, max_length=30)


class SkillsUpdate(BaseModel):
    skills: list[SkillItem] = Field(max_length=100)


class EducationUpdate(BaseModel):
    education: list[EducationItem] = Field(max_length=15)


class ExperienceUpdate(BaseModel):
    experience: list[ExperienceItem] = Field(max_length=25)


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)
    application_id: uuid.UUID | None = None
    is_private: bool = Field(
        default=False, description="Private notes are visible only to you and company admins"
    )


class NoteOut(ORMModel):
    id: uuid.UUID
    body: str
    is_private: bool
    application_id: uuid.UUID | None = None
    author: UserRef | None = None
    created_at: datetime


class DocumentOut(ORMModel):
    id: uuid.UUID
    document_type: str
    file_name: str
    content_type: str
    size_bytes: int
    scan_status: str
    is_confidential: bool
    created_at: datetime
    #: Short-lived signed URL; absent when the caller may not access the file.
    download_url: str | None = None


class GenerateSummaryRequest(BaseModel):
    job_id: uuid.UUID | None = Field(
        default=None, description="Contextualise the summary against a specific job"
    )


class CandidateSummaryResponse(BaseModel):
    summary: str
    strengths: list[str] = Field(default_factory=list)
    considerations: list[str] = Field(default_factory=list)
    engine: str
    generated_at: datetime
    disclaimer: str = (
        "AI-generated from the candidate's own profile data. Review before relying on it; "
        "hiring decisions remain yours."
    )


class ResolveFlagRequest(BaseModel):
    code: str = Field(min_length=1, max_length=60)


class CandidateApplicationBrief(ORMModel):
    id: uuid.UUID
    reference_code: str
    status: str
    ats_score: float | None = None
    ats_rank: int | None = None
    created_at: datetime
    job_id: uuid.UUID
    job_title: str | None = None


class CandidateSearchFilters(BaseModel):
    """Documents the query parameters accepted by candidate search."""

    q: str | None = None
    skills: list[str] = Field(default_factory=list)
    min_experience: float | None = None
    max_experience: float | None = None
    location: str | None = None
    min_ats_score: float | None = None
    job_id: uuid.UUID | None = None
    max_notice_period: int | None = None
