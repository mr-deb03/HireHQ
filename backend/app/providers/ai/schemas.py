"""Data contracts for the AI layer.

Every provider - real LLM or deterministic fallback - returns exactly these shapes, so
swapping providers can never change what the rest of the application sees. They double
as the JSON schemas handed to the model for structured output.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ------------------------------------------------------------ job description
class ExtractedSkill(BaseModel):
    name: str = Field(description="The skill as a recruiter would write it, e.g. 'React'")
    importance: str = Field(
        default="REQUIRED", description="REQUIRED or PREFERRED", pattern="^(REQUIRED|PREFERRED)$"
    )
    category: str = Field(
        default="TECHNICAL", description="TECHNICAL, SOFT or DOMAIN"
    )
    min_years: float | None = Field(default=None, description="Minimum years if stated")


class JobDescriptionAnalysis(BaseModel):
    """What the AI reads out of a job description, for the recruiter to confirm (s8)."""

    required_skills: list[ExtractedSkill] = Field(default_factory=list)
    preferred_skills: list[ExtractedSkill] = Field(default_factory=list)
    min_experience_years: float = 0
    max_experience_years: float | None = None
    education_requirements: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    technical_skills: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    seniority: str | None = Field(default=None, description="INTERN/JUNIOR/MID/SENIOR/LEAD")
    #: 0-1. Low confidence tells the UI to be louder about "please review this".
    confidence: float = 0.5


# ------------------------------------------------------------------- resume
class ParsedExperience(BaseModel):
    company: str = ""
    position: str = ""
    start_date: str | None = Field(default=None, description="ISO date or YYYY-MM")
    end_date: str | None = Field(default=None, description="ISO date, YYYY-MM, or null if current")
    is_current: bool = False
    location: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class ParsedEducation(BaseModel):
    degree: str = ""
    degree_level: str | None = Field(
        default=None, description="DOCTORATE/MASTERS/BACHELORS/DIPLOMA/HIGH_SCHOOL"
    )
    field_of_study: str | None = None
    institution: str | None = None
    university: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    grade: str | None = None


class ParsedResume(BaseModel):
    """Structured resume content (s13).

    Deliberately contains no inferred personal attributes - no age, gender, nationality,
    marital status or anything else a hiring decision must not rest on (s49, s63).
    """

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None

    summary: str | None = None
    current_designation: str | None = None
    current_company: str | None = None
    total_experience_years: float = 0

    skills: list[str] = Field(default_factory=list)
    experience: list[ParsedExperience] = Field(default_factory=list)
    education: list[ParsedEducation] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)

    confidence: float = 0.5
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------- summaries
class CandidateSummary(BaseModel):
    summary: str
    strengths: list[str] = Field(default_factory=list)
    considerations: list[str] = Field(
        default_factory=list,
        description="Gaps relative to the role's stated requirements. Never personal traits.",
    )


class FeedbackSummary(BaseModel):
    """AI digest of interview feedback (s29). Advisory only - never a decision."""

    summary: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    #: Reflects what interviewers said; the recommendation of record stays theirs.
    consensus: str | None = Field(
        default=None, description="One of STRONG_HIRE/HIRE/MAYBE/NO_HIRE/MIXED"
    )


class SemanticAssessment(BaseModel):
    """Optional LLM contribution to the ATS semantic component."""

    similarity: float = Field(ge=0, le=1)
    rationale: str = ""


# --------------------------------------------------------------- assistant
class AssistantToolCall(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)
    result_summary: str = ""


class AssistantAnswer(BaseModel):
    """Recruiter-assistant reply (s41).

    ``engine`` tells the UI whether a real model answered or the deterministic rule-based
    router did, so the interface never implies capability it does not have.
    """

    answer: str
    engine: str
    tool_calls: list[AssistantToolCall] = Field(default_factory=list)
    #: Structured payload the frontend can render as a table/list instead of prose.
    data: dict | None = None
    suggestions: list[str] = Field(default_factory=list)
