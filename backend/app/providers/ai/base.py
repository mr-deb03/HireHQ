"""The AI provider interface.

Nothing outside ``app/providers/ai`` knows which implementation is active. Services
depend on this ABC, which is what makes the LLM vendor swappable (s1) and keeps the
deterministic fallback a first-class citizen rather than a stub.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.providers.ai.schemas import (
    AssistantAnswer,
    CandidateSummary,
    FeedbackSummary,
    JobDescriptionAnalysis,
    ParsedResume,
    SemanticAssessment,
)


@dataclass(slots=True)
class AIUsage:
    """Cost/latency telemetry recorded against every AI call for governance (s63)."""

    engine: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    error: str | None = None


@dataclass(slots=True)
class AIResult:
    """An AI output paired with how it was produced."""

    value: Any
    usage: AIUsage


@dataclass(slots=True)
class AssistantTool:
    """A capability the recruiter assistant may invoke.

    The assistant never touches the database directly. It can only call these functions,
    each of which is already bound to the caller's company and permission set - so RBAC
    and tenant isolation hold even if the model asks for something out of scope (s41).
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Any  # async callable(**kwargs) -> dict
    required_permission: str | None = None


@dataclass(slots=True)
class AssistantContext:
    """Non-secret context handed to the assistant with every question."""

    user_name: str
    company_name: str
    role_names: list[str] = field(default_factory=list)
    today: str = ""


class AIProvider(ABC):
    """Every capability HireHQ asks of an AI layer."""

    #: Stable identifier recorded in ``ai_decision_logs.engine``.
    name: str = "abstract"

    #: True only for providers that call a real model. Endpoints that must not silently
    #: degrade (and the UI badges) branch on this instead of guessing from the name.
    is_real_model: bool = False

    @abstractmethod
    async def analyze_job_description(
        self, *, title: str, description: str, extra_context: str | None = None
    ) -> AIResult:
        """Extract structured requirements from a job description -> ``JobDescriptionAnalysis``."""

    @abstractmethod
    async def parse_resume(self, *, text: str, hint_name: str | None = None) -> AIResult:
        """Turn resume text into structured data -> ``ParsedResume``."""

    @abstractmethod
    async def summarize_candidate(
        self, *, candidate_profile: dict, job_context: dict | None = None
    ) -> AIResult:
        """Write a recruiter-facing profile summary -> ``CandidateSummary``."""

    @abstractmethod
    async def summarize_interview_feedback(
        self, *, feedback_items: list[dict], candidate_name: str, job_title: str
    ) -> AIResult:
        """Digest one or more feedback forms -> ``FeedbackSummary``."""

    @abstractmethod
    async def assess_semantic_fit(
        self, *, job_text: str, resume_text: str
    ) -> AIResult:
        """Judge how well a resume matches a job in meaning -> ``SemanticAssessment``."""

    @abstractmethod
    async def answer_recruiter_question(
        self,
        *,
        question: str,
        tools: list[AssistantTool],
        context: AssistantContext,
        history: list[dict] | None = None,
    ) -> AIResult:
        """Answer a recruiter's question using only the supplied tools -> ``AssistantAnswer``."""

    # ------------------------------------------------------------- helpers
    async def health(self) -> dict[str, Any]:
        return {"provider": self.name, "real_model": self.is_real_model, "status": "ok"}


__all__ = [
    "AIProvider",
    "AIResult",
    "AIUsage",
    "AssistantContext",
    "AssistantTool",
    "AssistantAnswer",
    "CandidateSummary",
    "FeedbackSummary",
    "JobDescriptionAnalysis",
    "ParsedResume",
    "SemanticAssessment",
]
