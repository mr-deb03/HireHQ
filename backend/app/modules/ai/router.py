"""AI recruiter assistant and AI-governance endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Perm
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.audit import AiDecisionLog
from app.models.company import Company
from app.modules.ai.tools import AssistantToolkit
from app.providers.ai.base import AssistantContext
from app.providers.ai.factory import get_ai_provider
from app.schemas.common import ORMModel, PaginationParams, pagination
from app.services.audit import AuditService

router = APIRouter(prefix="/ai", tags=["AI"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

MAX_HISTORY_TURNS = 10


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    #: Prior turns as ``[{"role": "user"|"assistant", "content": "..."}]``.
    history: list[dict] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS * 2)


class ToolCallOut(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)


class AskResponse(BaseModel):
    answer: str
    #: ``heuristic-v1`` or ``anthropic:<model>``. The UI labels the source so nobody
    #: mistakes the rule-based router for a conversational model.
    engine: str
    is_language_model: bool
    tool_calls: list[ToolCallOut] = Field(default_factory=list)
    data: dict | None = None
    suggestions: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Answers are generated from HireHQ data you are authorised to see. Verify before "
        "acting; hiring decisions remain yours."
    )


class AiStatusOut(BaseModel):
    provider: str
    is_language_model: bool
    model: str | None = None
    capabilities: dict[str, bool]
    message: str


class AiDecisionOut(ORMModel):
    id: uuid.UUID
    feature: str
    engine: str
    model: str | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    input_digest: dict = Field(default_factory=dict)
    output_summary: dict = Field(default_factory=dict)
    confidence: float | None = None
    human_review_status: str
    reviewed_by_id: uuid.UUID | None = None
    review_note: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    created_at: datetime


class ReviewDecisionRequest(BaseModel):
    status: str = Field(pattern="^(ACCEPTED|EDITED|OVERRIDDEN|REJECTED)$")
    note: str | None = Field(default=None, max_length=2000)


@router.get(
    "/status",
    response_model=SuccessResponse[AiStatusOut],
    summary="Which AI engine is active",
    description=(
        "Reports honestly whether a real language model is configured. When it is not, "
        "AI features run on the built-in deterministic engine and are labelled as such."
    ),
)
async def ai_status(principal: CurrentUser) -> SuccessResponse[AiStatusOut]:
    provider = get_ai_provider()
    health = await provider.health()

    message = (
        f"Using {provider.name}. Full language-model features are available."
        if provider.is_real_model
        else (
            "No language-model provider is configured. HireHQ is using its built-in "
            "deterministic engine: resume parsing, job-description analysis and ATS "
            "scoring all work, and the assistant answers a fixed set of questions. Set "
            "AI_PROVIDER=anthropic with AI_API_KEY for free-form conversation and "
            "higher-quality extraction."
        )
    )
    return SuccessResponse(
        data=AiStatusOut(
            provider=provider.name,
            is_language_model=provider.is_real_model,
            model=health.get("model"),
            capabilities={
                "job_description_analysis": True,
                "resume_parsing": True,
                "ats_semantic_matching": True,
                "candidate_summaries": True,
                "feedback_summaries": True,
                "conversational_assistant": provider.is_real_model,
            },
            message=message,
        )
    )


@router.post(
    "/ask",
    response_model=SuccessResponse[AskResponse],
    summary="Ask the recruiter assistant",
    description=(
        "Answers questions about your jobs, candidates, pipeline and interviews.\n\n"
        "The assistant has **no database access**. It can only call a fixed set of tools "
        "that are pre-bound to your company and filtered by your permissions, so it can "
        "never surface data you are not authorised to see."
    ),
    dependencies=[Depends(require_permission(Perm.AI_ASSISTANT_USE))],
)
async def ask(
    payload: AskRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[AskResponse]:
    provider = get_ai_provider()
    toolkit = AssistantToolkit(session, principal)
    tools = toolkit.build()

    company = await session.get(Company, company_id)
    context = AssistantContext(
        user_name=principal.user.first_name,
        company_name=company.name if company else "your company",
        role_names=sorted(principal.roles),
        today=datetime.now(UTC).strftime("%A, %d %B %Y"),
    )

    # Only well-formed prior turns are replayed; anything else is dropped rather than
    # trusted, since history arrives from the client.
    history = [
        {"role": turn["role"], "content": str(turn["content"])[:4000]}
        for turn in payload.history[-MAX_HISTORY_TURNS * 2 :]
        if isinstance(turn, dict)
        and turn.get("role") in ("user", "assistant")
        and turn.get("content")
    ]

    result = await provider.answer_recruiter_question(
        question=payload.question, tools=tools, context=context, history=history
    )
    answer = result.value

    await AuditService(session).record_ai(
        feature="ASSISTANT_QUERY",
        engine=result.usage.engine,
        model=result.usage.model,
        company_id=company_id,
        user_id=principal.id,
        input_digest={
            "question_length": len(payload.question),
            "tools_available": len(tools),
            "history_turns": len(history),
        },
        output_summary={
            "tools_called": [c.name for c in answer.tool_calls],
            "answer_length": len(answer.answer),
        },
        latency_ms=result.usage.latency_ms,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        error=result.usage.error,
    )

    return SuccessResponse(
        data=AskResponse(
            answer=answer.answer,
            engine=answer.engine,
            is_language_model=provider.is_real_model,
            tool_calls=[
                ToolCallOut(name=c.name, arguments=c.arguments) for c in answer.tool_calls
            ],
            data=answer.data,
            suggestions=answer.suggestions,
        )
    )


@router.get(
    "/tools",
    response_model=SuccessResponse[list[dict]],
    summary="Tools available to you",
    description=(
        "The exact capability surface the assistant has for your account. Useful for "
        "auditing what the AI layer can reach."
    ),
    dependencies=[Depends(require_permission(Perm.AI_ASSISTANT_USE))],
)
async def list_tools(
    principal: CurrentUser, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[dict]]:
    tools = AssistantToolkit(session, principal).build()
    return SuccessResponse(
        data=[
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "required_permission": t.required_permission,
            }
            for t in tools
        ]
    )


@router.get(
    "/decisions",
    response_model=SuccessResponse[Page[AiDecisionOut]],
    summary="AI decision log",
    description=(
        "Every AI-assisted output: which engine produced it, what it concluded, and "
        "whether a human accepted, edited or overrode it (s63)."
    ),
    dependencies=[Depends(require_permission(Perm.AUDIT_READ, Perm.AI_CONFIG_MANAGE))],
)
async def list_ai_decisions(
    company_id: CompanyScope,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    feature: str | None = None,
    review_status: Annotated[str | None, Query()] = None,
) -> SuccessResponse[Page[AiDecisionOut]]:
    stmt = select(AiDecisionLog).where(AiDecisionLog.company_id == company_id)
    if feature:
        stmt = stmt.where(AiDecisionLog.feature == feature)
    if review_status:
        stmt = stmt.where(AiDecisionLog.human_review_status == review_status)

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(AiDecisionLog.created_at.desc())
                .limit(page_params.page_size)
                .offset(page_params.offset)
            )
        )
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=Page.build(
            [AiDecisionOut.model_validate(r) for r in rows],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


@router.post(
    "/decisions/{decision_id}/review",
    response_model=SuccessResponse[AiDecisionOut],
    summary="Record a human review of an AI output",
    description=(
        "Marks an AI-assisted output as accepted, edited, overridden or rejected by a "
        "person. This is what makes 'human override' auditable rather than assumed."
    ),
    dependencies=[Depends(require_permission(Perm.AI_ASSISTANT_USE))],
)
async def review_decision(
    decision_id: uuid.UUID,
    payload: ReviewDecisionRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[AiDecisionOut]:
    from app.core.exceptions import ResourceNotFound

    decision = await session.scalar(
        select(AiDecisionLog).where(
            AiDecisionLog.id == decision_id, AiDecisionLog.company_id == company_id
        )
    )
    if decision is None:
        raise ResourceNotFound("AI decision", decision_id)

    decision.human_review_status = payload.status
    decision.reviewed_by_id = principal.id
    decision.review_note = payload.note
    await session.flush()

    return SuccessResponse(
        data=AiDecisionOut.model_validate(decision), message="Review recorded"
    )


@router.get(
    "/governance",
    response_model=SuccessResponse[dict],
    summary="AI governance policy",
    description="The commitments the AI layer operates under, and how they are enforced.",
)
async def governance() -> SuccessResponse[dict]:
    return SuccessResponse(
        data={
            "principles": [
                "AI assists; authorised humans decide. No AI output rejects a candidate.",
                "Protected attributes are never inferred, stored, or used in scoring.",
                "ATS scores are explainable: every component states its reasoning.",
                "Every AI-assisted output is logged with the engine that produced it.",
                "Recruiters can override any AI suggestion, and the override is recorded.",
                "Automation that would reject, hire or make an offer requires human approval.",
            ],
            "enforcement": {
                "protected_attributes": (
                    "The AI system prompt forbids inferring them, the parser schema has "
                    "no field to store them, and the ATS engine has no dimension that "
                    "could use them."
                ),
                "no_auto_reject": (
                    "The workflow engine refuses to move an application to REJECTED, "
                    "HIRED or OFFER unless the workflow requires human approval - "
                    "checked both when the workflow is saved and again at execution."
                ),
                "rbac": (
                    "The assistant has no database access. It can only call tools that "
                    "are pre-bound to the caller's company and filtered by their "
                    "permissions."
                ),
                "auditability": (
                    "ai_decision_logs records feature, engine, model, a non-sensitive "
                    "input digest, the output summary and the human review outcome."
                ),
            },
            "candidate_rights": [
                "Candidates are never shown internal scores, notes or interview remarks.",
                "Consent is recorded at application time.",
                "Data export and deletion can be requested.",
                "Records are anonymised once the retention period elapses.",
            ],
        }
    )
