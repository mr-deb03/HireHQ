"""Assessment management (recruiter) and the candidate-facing tokenised test flow."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import AssessmentAttemptStatus, AssessmentQuestionType
from app.core.exceptions import ResourceNotFound
from app.core.permissions import Perm
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.assessment import AssessmentAttempt, JobAssessment
from app.modules.assessments.service import AssessmentService
from app.schemas.common import ORMModel, PaginationParams, pagination

router = APIRouter(prefix="/assessments", tags=["Assessments"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class QuestionInput(BaseModel):
    question_type: AssessmentQuestionType
    prompt: str = Field(min_length=1, max_length=10_000)
    points: float = Field(default=1, gt=0, le=100)
    difficulty: str = Field(default="MEDIUM", pattern="^(EASY|MEDIUM|HARD)$")
    options: list[dict] = Field(default_factory=list, max_length=10)
    correct_options: list[str] = Field(default_factory=list, max_length=10)
    starter_code: str | None = Field(default=None, max_length=20_000)
    allowed_languages: list[str] = Field(default_factory=list, max_length=15)
    test_cases: list[dict] = Field(default_factory=list, max_length=30)
    expected_answer: str | None = Field(default=None, max_length=5000)
    explanation: str | None = Field(default=None, max_length=5000)


class AssessmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: str = Field(default="MIXED", max_length=30)
    duration_minutes: int = Field(default=60, ge=5, le=480)
    passing_score: float = Field(default=60, ge=0, le=100)
    max_attempts: int = Field(default=1, ge=1, le=5)
    randomise_questions: bool = True
    questions: list[QuestionInput] = Field(min_length=1, max_length=100)


class QuestionOut(ORMModel):
    id: uuid.UUID
    question_type: AssessmentQuestionType
    prompt: str
    points: float
    difficulty: str
    display_order: int
    options: list = Field(default_factory=list)
    allowed_languages: list[str] = Field(default_factory=list)


class AssessmentOut(ORMModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    category: str
    duration_minutes: int
    passing_score: float
    max_attempts: int
    randomise_questions: bool
    is_active: bool
    total_points: float
    questions: list[QuestionOut] = Field(default_factory=list)
    created_at: datetime


class InviteRequest(BaseModel):
    assessment_id: uuid.UUID
    application_id: uuid.UUID
    valid_for_days: int = Field(default=7, ge=1, le=60)


class InviteResponse(BaseModel):
    attempt_id: uuid.UUID
    candidate_url: str
    expires_at: datetime | None = None
    #: Honest reporting - the invitation may not have been transmitted.
    email_delivery_status: str
    message: str


class AttemptOut(ORMModel):
    id: uuid.UUID
    assessment_id: uuid.UUID
    application_id: uuid.UUID
    candidate_id: uuid.UUID
    attempt_number: int
    status: AssessmentAttemptStatus
    invited_at: datetime | None = None
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    expires_at: datetime | None = None
    time_spent_seconds: int | None = None
    score: float | None = None
    max_score: float | None = None
    percentage: float | None = None
    passed: bool | None = None
    #: Question ids that a human still has to grade (coding, SQL, free text).
    pending_manual_review: list = Field(default_factory=list)
    created_at: datetime


class AnswerInput(BaseModel):
    question_id: uuid.UUID
    selected_options: list[str] = Field(default_factory=list, max_length=10)
    answer_text: str | None = Field(default=None, max_length=20_000)
    code_submission: str | None = Field(default=None, max_length=100_000)
    language: str | None = Field(default=None, max_length=30)
    time_spent_seconds: int | None = Field(default=None, ge=0)


class SubmitRequest(BaseModel):
    answers: list[AnswerInput] = Field(min_length=1, max_length=100)


class ManualGradeRequest(BaseModel):
    question_id: uuid.UUID
    points: float = Field(ge=0)
    comment: str | None = Field(default=None, max_length=2000)


class AttachRequest(BaseModel):
    job_id: uuid.UUID
    is_mandatory: bool = True
    trigger_status: str | None = Field(default=None, max_length=30)


# ------------------------------------------------------------------ recruiter
@router.get(
    "",
    response_model=SuccessResponse[list[AssessmentOut]],
    summary="List assessments",
    dependencies=[Depends(require_permission(Perm.ASSESSMENT_MANAGE, Perm.ASSESSMENT_RESULT_READ))],
)
async def list_assessments(
    company_id: CompanyScope, session: DbSession, active_only: bool = False
) -> SuccessResponse[list[AssessmentOut]]:
    items = await AssessmentService(session, company_id).list(active_only=active_only)
    return SuccessResponse(data=[AssessmentOut.model_validate(a) for a in items])


@router.post(
    "",
    response_model=SuccessResponse[AssessmentOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create an assessment",
    description=(
        "MCQ and aptitude questions are graded automatically. Coding and SQL "
        "submissions are stored for human grading - this server does not execute "
        "candidate code."
    ),
    dependencies=[Depends(require_permission(Perm.ASSESSMENT_MANAGE))],
)
async def create_assessment(
    payload: AssessmentCreate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[AssessmentOut]:
    service = AssessmentService(session, company_id)
    assessment = await service.create(
        created_by_id=principal.id,
        questions=[q.model_dump() for q in payload.questions],
        **payload.model_dump(exclude={"questions"}),
    )
    assessment = await service.get(assessment.id)
    return SuccessResponse(
        data=AssessmentOut.model_validate(assessment), message="Assessment created"
    )


@router.get(
    "/{assessment_id}",
    response_model=SuccessResponse[AssessmentOut],
    summary="Get an assessment",
    description="Correct answers and hidden test cases are never included.",
    dependencies=[Depends(require_permission(Perm.ASSESSMENT_MANAGE))],
)
async def get_assessment(
    assessment_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[AssessmentOut]:
    assessment = await AssessmentService(session, company_id).get(assessment_id)
    return SuccessResponse(data=AssessmentOut.model_validate(assessment))


@router.post(
    "/{assessment_id}/attach",
    response_model=SuccessResponse[dict],
    summary="Attach an assessment to a job",
    dependencies=[Depends(require_permission(Perm.ASSESSMENT_MANAGE))],
)
async def attach_to_job(
    assessment_id: uuid.UUID,
    payload: AttachRequest,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[dict]:
    await AssessmentService(session, company_id).get(assessment_id)

    existing = await session.scalar(
        select(JobAssessment).where(
            JobAssessment.job_id == payload.job_id,
            JobAssessment.assessment_id == assessment_id,
        )
    )
    if existing is not None:
        existing.is_mandatory = payload.is_mandatory
        existing.trigger_status = payload.trigger_status
    else:
        session.add(
            JobAssessment(
                job_id=payload.job_id,
                assessment_id=assessment_id,
                is_mandatory=payload.is_mandatory,
                trigger_status=payload.trigger_status,
            )
        )
    await session.flush()
    return SuccessResponse(
        data={"job_id": str(payload.job_id), "assessment_id": str(assessment_id)},
        message="Assessment attached to the job",
    )


@router.post(
    "/invite",
    response_model=SuccessResponse[InviteResponse],
    summary="Invite a candidate to take an assessment",
    dependencies=[Depends(require_permission(Perm.ASSESSMENT_MANAGE))],
)
async def invite(
    payload: InviteRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[InviteResponse]:
    from app.core.config import settings

    service = AssessmentService(session, company_id)
    attempt, raw_token, delivery = await service.invite(
        assessment_id=payload.assessment_id,
        application_id=payload.application_id,
        actor_id=principal.id,
        valid_for_days=payload.valid_for_days,
    )
    url = f"{settings.FRONTEND_BASE_URL}/assessments/{attempt.id}?token={raw_token}"
    transmitted = delivery == "SENT"
    return SuccessResponse(
        data=InviteResponse(
            attempt_id=attempt.id,
            candidate_url=url,
            expires_at=attempt.expires_at,
            email_delivery_status=delivery,
            message=(
                "Invitation emailed to the candidate."
                if transmitted
                else (
                    "Attempt created, but the email was not transmitted. Share the link "
                    "with the candidate directly."
                )
            ),
        )
    )


@router.get(
    "/attempts/list",
    response_model=SuccessResponse[Page[AttemptOut]],
    summary="List assessment attempts",
    dependencies=[Depends(require_permission(Perm.ASSESSMENT_RESULT_READ))],
)
async def list_attempts(
    company_id: CompanyScope,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    application_id: uuid.UUID | None = None,
    attempt_status: Annotated[AssessmentAttemptStatus | None, Query(alias="status")] = None,
    needs_grading: Annotated[bool, Query()] = False,
) -> SuccessResponse[Page[AttemptOut]]:
    stmt = select(AssessmentAttempt).where(AssessmentAttempt.company_id == company_id)
    if application_id:
        stmt = stmt.where(AssessmentAttempt.application_id == application_id)
    if attempt_status:
        stmt = stmt.where(AssessmentAttempt.status == attempt_status)
    if needs_grading:
        stmt = stmt.where(AssessmentAttempt.status == AssessmentAttemptStatus.SUBMITTED)

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(AssessmentAttempt.created_at.desc())
                .limit(page_params.page_size)
                .offset(page_params.offset)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    items = [AttemptOut.model_validate(a) for a in rows]
    if needs_grading:
        items = [a for a in items if a.pending_manual_review]

    return SuccessResponse(
        data=Page.build(
            items, page=page_params.page, page_size=page_params.page_size, total=total
        )
    )


@router.get(
    "/attempts/{attempt_id}",
    response_model=SuccessResponse[dict],
    summary="Get an attempt with its answers",
    dependencies=[Depends(require_permission(Perm.ASSESSMENT_RESULT_READ))],
)
async def get_attempt(
    attempt_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[dict]:
    attempt = (
        (
            await session.execute(
                select(AssessmentAttempt)
                .where(
                    AssessmentAttempt.id == attempt_id,
                    AssessmentAttempt.company_id == company_id,
                )
                .options(selectinload(AssessmentAttempt.answers))
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if attempt is None:
        raise ResourceNotFound("Assessment attempt", attempt_id)

    return SuccessResponse(
        data={
            "attempt": AttemptOut.model_validate(attempt).model_dump(),
            "answers": [
                {
                    "question_id": str(a.question_id),
                    "selected_options": a.selected_options,
                    "answer_text": a.answer_text,
                    "code_submission": a.code_submission,
                    "language": a.language,
                    "points_awarded": (
                        float(a.points_awarded) if a.points_awarded is not None else None
                    ),
                    "points_possible": float(a.points_possible),
                    "is_correct": a.is_correct,
                    "needs_grading": a.points_awarded is None,
                    "grader_comment": a.grader_comment,
                }
                for a in attempt.answers
            ],
        }
    )


@router.post(
    "/attempts/{attempt_id}/grade",
    response_model=SuccessResponse[AttemptOut],
    summary="Manually grade one answer",
    description="Used for coding, SQL and free-text answers the server cannot auto-grade.",
    dependencies=[Depends(require_permission(Perm.ASSESSMENT_MANAGE))],
)
async def grade_answer(
    attempt_id: uuid.UUID,
    payload: ManualGradeRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[AttemptOut]:
    attempt = await session.scalar(
        select(AssessmentAttempt).where(
            AssessmentAttempt.id == attempt_id,
            AssessmentAttempt.company_id == company_id,
        )
    )
    if attempt is None:
        raise ResourceNotFound("Assessment attempt", attempt_id)

    service = AssessmentService(session, company_id)
    await service.grade_manually(
        attempt,
        question_id=payload.question_id,
        points=payload.points,
        grader_id=principal.id,
        comment=payload.comment,
    )
    return SuccessResponse(data=AttemptOut.model_validate(attempt), message="Answer graded")


# ------------------------------------------------------------- candidate flow
candidate_router = APIRouter(prefix="/assessments", tags=["Assessments"])


@candidate_router.get(
    "/take/{attempt_id}",
    response_model=SuccessResponse[dict],
    summary="Open an assessment (candidate)",
    description=(
        "Starts the timer and returns the questions. Correct answers and hidden test "
        "cases are stripped before the response leaves the server."
    ),
)
async def take_assessment(
    attempt_id: uuid.UUID,
    token: Annotated[str, Query(description="Token from the invitation email")],
    session: DbSession,
) -> SuccessResponse[dict]:
    attempt = await session.scalar(
        select(AssessmentAttempt).where(AssessmentAttempt.id == attempt_id)
    )
    if attempt is None:
        raise ResourceNotFound("Assessment attempt", attempt_id)

    service = AssessmentService(session, attempt.company_id)
    attempt = await service.verify_token(attempt_id, token)
    attempt, assessment = await service.start(attempt)

    return SuccessResponse(
        data={
            "attempt_id": str(attempt.id),
            "status": attempt.status.value,
            "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
            "expires_at": attempt.expires_at.isoformat() if attempt.expires_at else None,
            "assessment": service.serialise_for_candidate(assessment),
        }
    )


@candidate_router.post(
    "/take/{attempt_id}/submit",
    response_model=SuccessResponse[dict],
    summary="Submit an assessment (candidate)",
    description=(
        "Objective questions are graded immediately. Coding, SQL and free-text answers "
        "are stored for a human to review - the response says so rather than reporting "
        "an invented score."
    ),
)
async def submit_assessment(
    attempt_id: uuid.UUID,
    payload: SubmitRequest,
    token: Annotated[str, Query()],
    session: DbSession,
) -> SuccessResponse[dict]:
    attempt = await session.scalar(
        select(AssessmentAttempt).where(AssessmentAttempt.id == attempt_id)
    )
    if attempt is None:
        raise ResourceNotFound("Assessment attempt", attempt_id)

    service = AssessmentService(session, attempt.company_id)
    attempt = await service.verify_token(attempt_id, token)
    attempt = await service.submit(attempt, [a.model_dump() for a in payload.answers])
    await session.commit()
    await service.events.flush()

    pending = len(attempt.pending_manual_review or [])
    return SuccessResponse(
        data={
            "attempt_id": str(attempt.id),
            "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
            "questions_awaiting_review": pending,
        },
        message=(
            "Thank you - your assessment has been submitted."
            + (
                " Some answers need review by our team, so your final result will follow."
                if pending
                else ""
            )
        ),
    )
