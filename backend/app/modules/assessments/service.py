"""Technical assessments: invitations, submissions and grading.

Auto-grading covers what can be graded objectively - MCQs, exact-match short answers, and
coding/SQL submissions *when a runner is configured that can actually execute them*.
Anything else is stored and routed to a human: the attempt reports which questions await
manual review rather than inventing a pass/fail (s69). A runner that cannot execute a
submission yields "not graded", never "failed".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.enums import (
    AssessmentAttemptStatus,
    AssessmentQuestionType,
    EmailTemplateKey,
)
from app.core.exceptions import BusinessRuleError, ResourceNotFound, ValidationError
from app.core.logging import get_logger
from app.core.security import generate_url_token, hash_url_token
from app.models.application import Application
from app.models.assessment import (
    Assessment,
    AssessmentAnswer,
    AssessmentAttempt,
    AssessmentQuestion,
)
from app.services.events import DomainEvent, EventCollector, Events
from app.utils.text import normalise

logger = get_logger(__name__)

#: Question types this server can grade without executing anything.
AUTO_GRADED = frozenset(
    {
        AssessmentQuestionType.MCQ_SINGLE,
        AssessmentQuestionType.MCQ_MULTIPLE,
        AssessmentQuestionType.APTITUDE,
    }
)


class AssessmentService:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID) -> None:
        self.session = session
        self.company_id = company_id
        self.events = EventCollector()

    async def get(self, assessment_id: uuid.UUID) -> Assessment:
        assessment = (
            (
                await self.session.execute(
                    select(Assessment)
                    .where(
                        Assessment.id == assessment_id,
                        Assessment.company_id == self.company_id,
                    )
                    .options(selectinload(Assessment.questions))
                )
            )
            .unique()
            .scalar_one_or_none()
        )
        if assessment is None:
            raise ResourceNotFound("Assessment", assessment_id)
        return assessment

    async def list(self, *, active_only: bool = False) -> list[Assessment]:
        stmt = (
            select(Assessment)
            .where(Assessment.company_id == self.company_id)
            .options(selectinload(Assessment.questions))
            .order_by(Assessment.title)
        )
        if active_only:
            stmt = stmt.where(Assessment.is_active.is_(True))
        return list((await self.session.execute(stmt)).unique().scalars().all())

    async def create(
        self,
        *,
        title: str,
        questions: list[dict[str, Any]],
        created_by_id: uuid.UUID,
        description: str | None = None,
        category: str = "MIXED",
        duration_minutes: int = 60,
        passing_score: float = 60,
        max_attempts: int = 1,
        randomise_questions: bool = True,
    ) -> Assessment:
        if not questions:
            raise ValidationError("An assessment needs at least one question")

        assessment = Assessment(
            company_id=self.company_id,
            title=title,
            description=description,
            category=category,
            duration_minutes=duration_minutes,
            passing_score=passing_score,
            max_attempts=max_attempts,
            randomise_questions=randomise_questions,
            created_by_id=created_by_id,
        )
        self.session.add(assessment)
        await self.session.flush()

        for index, question in enumerate(questions):
            self._validate_question(question, index)
            self.session.add(
                AssessmentQuestion(
                    assessment_id=assessment.id, display_order=index, **question
                )
            )
        await self.session.flush()
        return assessment

    @staticmethod
    def _validate_question(question: dict[str, Any], index: int) -> None:
        kind = AssessmentQuestionType(question["question_type"])
        label = f"Question {index + 1}"

        if kind in (AssessmentQuestionType.MCQ_SINGLE, AssessmentQuestionType.MCQ_MULTIPLE):
            options = question.get("options") or []
            if len(options) < 2:
                raise ValidationError(f"{label}: multiple-choice needs at least two options")
            option_ids = {str(o.get("id")) for o in options}
            correct = {str(c) for c in (question.get("correct_options") or [])}
            if not correct:
                raise ValidationError(f"{label}: mark at least one correct option")
            if not correct.issubset(option_ids):
                raise ValidationError(
                    f"{label}: correct options must reference option ids that exist"
                )
            if kind == AssessmentQuestionType.MCQ_SINGLE and len(correct) != 1:
                raise ValidationError(
                    f"{label}: a single-answer question must have exactly one correct option"
                )

        if kind in (AssessmentQuestionType.CODING, AssessmentQuestionType.SQL):
            if not question.get("allowed_languages") and kind == AssessmentQuestionType.CODING:
                raise ValidationError(f"{label}: list at least one allowed language")

    # ----------------------------------------------------------- invitations
    async def invite(
        self,
        *,
        assessment_id: uuid.UUID,
        application_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
        valid_for_days: int = 7,
    ) -> tuple[AssessmentAttempt, str, str]:
        """Create an attempt and email the candidate.

        Returns ``(attempt, raw_access_token, email_delivery_status)``.
        """
        assessment = await self.get(assessment_id)
        if not assessment.is_active:
            raise BusinessRuleError("This assessment is not active")

        application = (
            (
                await self.session.execute(
                    select(Application)
                    .where(
                        Application.id == application_id,
                        Application.company_id == self.company_id,
                    )
                    .options(
                        selectinload(Application.candidate), selectinload(Application.job)
                    )
                )
            )
            .unique()
            .scalar_one_or_none()
        )
        if application is None:
            raise ResourceNotFound("Application", application_id)

        previous = (
            await self.session.execute(
                select(func.count())
                .select_from(AssessmentAttempt)
                .where(
                    AssessmentAttempt.assessment_id == assessment_id,
                    AssessmentAttempt.application_id == application_id,
                )
            )
        ).scalar_one()
        if previous >= assessment.max_attempts:
            raise BusinessRuleError(
                f"This candidate has already used all {assessment.max_attempts} attempt(s)",
                code="MAX_ATTEMPTS_REACHED",
            )

        raw_token = generate_url_token()
        now = datetime.now(UTC)
        attempt = AssessmentAttempt(
            company_id=self.company_id,
            assessment_id=assessment_id,
            application_id=application_id,
            candidate_id=application.candidate_id,
            attempt_number=previous + 1,
            status=AssessmentAttemptStatus.NOT_STARTED,
            access_token_hash=hash_url_token(raw_token),
            invited_at=now,
            expires_at=now + timedelta(days=valid_for_days),
            max_score=assessment.total_points,
        )
        self.session.add(attempt)
        await self.session.flush()

        from app.models.company import Company
        from app.modules.emails.service import EmailService

        company = await self.session.get(Company, self.company_id)
        email_service = EmailService(self.session, self.company_id)
        variables = EmailService.build_variables(
            candidate=application.candidate,
            job=application.job,
            application=application,
            company=company,
            extra={
                "assessment_name": assessment.title,
                "assessment_url": (
                    f"{settings.FRONTEND_BASE_URL}/assessments/{attempt.id}?token={raw_token}"
                ),
                "assessment_deadline": attempt.expires_at.strftime("%d %B %Y"),
            },
        )
        message = await email_service.send_templated(
            key=EmailTemplateKey.ASSESSMENT_INVITATION,
            to=[application.candidate.email],
            variables=variables,
            application_id=application.id,
            candidate_id=application.candidate_id,
            job_id=application.job_id,
            sent_by_id=actor_id,
        )

        logger.info("assessment_invited", attempt_id=str(attempt.id))
        return attempt, raw_token, message.delivery_status.value

    async def verify_token(self, attempt_id: uuid.UUID, raw_token: str) -> AssessmentAttempt:
        from app.core.exceptions import InvalidToken
        from app.core.security import constant_time_equals

        attempt = await self.session.scalar(
            select(AssessmentAttempt)
            .where(AssessmentAttempt.id == attempt_id)
            .options(selectinload(AssessmentAttempt.answers))
        )
        if attempt is None or not attempt.access_token_hash:
            raise ResourceNotFound("Assessment attempt", attempt_id)
        if not constant_time_equals(attempt.access_token_hash, hash_url_token(raw_token)):
            raise InvalidToken("This assessment link is not valid")
        if attempt.expires_at and attempt.expires_at <= datetime.now(UTC):
            if attempt.status != AssessmentAttemptStatus.SUBMITTED:
                attempt.status = AssessmentAttemptStatus.EXPIRED
                await self.session.flush()
            raise BusinessRuleError("This assessment link has expired", code="ASSESSMENT_EXPIRED")
        return attempt

    async def start(self, attempt: AssessmentAttempt) -> tuple[AssessmentAttempt, Assessment]:
        if attempt.status == AssessmentAttemptStatus.SUBMITTED:
            raise BusinessRuleError("This assessment has already been submitted")

        assessment = await self.session.scalar(
            select(Assessment)
            .where(Assessment.id == attempt.assessment_id)
            .options(selectinload(Assessment.questions))
        )
        if assessment is None:
            raise ResourceNotFound("Assessment", attempt.assessment_id)

        if attempt.status == AssessmentAttemptStatus.NOT_STARTED:
            attempt.status = AssessmentAttemptStatus.IN_PROGRESS
            attempt.started_at = datetime.now(UTC)
            # From here the clock is the assessment's own duration, not the link expiry.
            attempt.expires_at = attempt.started_at + timedelta(
                minutes=assessment.duration_minutes
            )
            await self.session.flush()

        return attempt, assessment

    # -------------------------------------------------------------- grading
    async def submit(
        self, attempt: AssessmentAttempt, answers: list[dict[str, Any]]
    ) -> AssessmentAttempt:
        if attempt.status == AssessmentAttemptStatus.SUBMITTED:
            raise BusinessRuleError("This assessment has already been submitted")

        assessment = await self.session.scalar(
            select(Assessment)
            .where(Assessment.id == attempt.assessment_id)
            .options(selectinload(Assessment.questions))
        )
        if assessment is None:
            raise ResourceNotFound("Assessment", attempt.assessment_id)

        questions = {q.id: q for q in assessment.questions}
        now = datetime.now(UTC)

        awarded = 0.0
        auto_gradable_total = 0.0
        pending: list[str] = []

        for answer in answers:
            question_id = uuid.UUID(str(answer["question_id"]))
            question = questions.get(question_id)
            if question is None:
                continue

            points = float(question.points)
            row = AssessmentAnswer(
                attempt_id=attempt.id,
                question_id=question_id,
                selected_options=answer.get("selected_options") or [],
                answer_text=answer.get("answer_text"),
                code_submission=answer.get("code_submission"),
                language=answer.get("language"),
                points_possible=points,
                time_spent_seconds=answer.get("time_spent_seconds"),
            )

            if question.question_type in AUTO_GRADED:
                auto_gradable_total += points
                selected = {str(o) for o in (answer.get("selected_options") or [])}
                correct = {str(o) for o in (question.correct_options or [])}
                is_correct = selected == correct
                row.is_correct = is_correct
                row.points_awarded = points if is_correct else 0.0
                # Partial credit for a multi-select that is right but incomplete.
                if (
                    not is_correct
                    and question.question_type == AssessmentQuestionType.MCQ_MULTIPLE
                    and selected
                    and selected.issubset(correct)
                ):
                    row.points_awarded = round(points * len(selected) / len(correct) * 0.5, 2)
                awarded += float(row.points_awarded)

            elif question.question_type == AssessmentQuestionType.SHORT_ANSWER:
                expected = (question.expected_answer or "").strip()
                if expected:
                    auto_gradable_total += points
                    is_correct = normalise(answer.get("answer_text") or "") == normalise(expected)
                    row.is_correct = is_correct
                    row.points_awarded = points if is_correct else 0.0
                    awarded += float(row.points_awarded)
                else:
                    pending.append(str(question_id))
            else:
                # Coding and SQL. Graded only if a runner can actually execute this
                # language; otherwise stored for a human. A runner that fails to execute
                # yields "not graded", never "failed".
                execution = await self._execute_submission(question, answer)
                if execution is not None and execution.executed and execution.results:
                    auto_gradable_total += points
                    fraction = execution.score_fraction or 0.0
                    row.points_awarded = round(points * fraction, 2)
                    row.is_correct = fraction >= 1.0
                    row.test_results = [r.for_candidate() for r in execution.results]
                    awarded += float(row.points_awarded)
                else:
                    pending.append(str(question_id))
                    if execution is not None and execution.detail:
                        row.grader_comment = execution.detail[:2000]

            self.session.add(row)

        attempt.status = AssessmentAttemptStatus.SUBMITTED
        attempt.submitted_at = now
        if attempt.started_at:
            attempt.time_spent_seconds = int((now - attempt.started_at).total_seconds())
        attempt.score = round(awarded, 2)
        attempt.max_score = assessment.total_points
        attempt.pending_manual_review = pending

        # The percentage reflects only what could actually be graded, so a submission
        # with outstanding coding questions is not misreported as a low score.
        if auto_gradable_total > 0:
            attempt.percentage = round(awarded / auto_gradable_total * 100, 2)
            if not pending:
                attempt.passed = attempt.percentage >= float(assessment.passing_score)
        else:
            attempt.percentage = None

        await self.session.flush()

        self.events.collect(
            DomainEvent(
                name=Events.ASSESSMENT_SUBMITTED,
                company_id=self.company_id,
                entity_type="Application",
                entity_id=attempt.application_id,
                payload={
                    "attempt_id": str(attempt.id),
                    "assessment_name": assessment.title,
                    "assessment_score": attempt.percentage,
                    "candidate_id": str(attempt.candidate_id),
                    "pending_manual_review": len(pending),
                },
            )
        )
        logger.info(
            "assessment_submitted",
            attempt_id=str(attempt.id),
            score=attempt.percentage,
            pending_review=len(pending),
        )
        return attempt

    async def _execute_submission(
        self, question: AssessmentQuestion, answer: dict[str, Any]
    ):
        """Run a coding/SQL answer against its test cases, if a runner can handle it.

        Returns ``None`` when there is nothing to run (no submission, no test cases), so
        the caller routes the answer to a human rather than scoring an empty result.
        """
        source = answer.get("code_submission") or answer.get("answer_text")
        if not source or not (question.test_cases or []):
            return None

        language = (
            answer.get("language")
            or ("sql" if question.question_type == AssessmentQuestionType.SQL else None)
        )
        if not language:
            return None

        from app.providers.code_runner import get_runner_for_language

        runner = get_runner_for_language(language)
        if not runner.executes:
            return await runner.run(
                language=language, source=source, test_cases=list(question.test_cases)
            )

        try:
            return await runner.run(
                language=language,
                source=source,
                test_cases=list(question.test_cases),
                timeout_seconds=settings.CODE_RUNNER_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning("code_execution_failed", error=str(exc)[:300])
            from app.providers.code_runner import ExecutionResult

            return ExecutionResult(
                executed=False,
                detail=(
                    "Automatic grading could not be completed, so this answer was stored "
                    "for review by the hiring team."
                ),
            )

    async def grade_manually(
        self,
        attempt: AssessmentAttempt,
        *,
        question_id: uuid.UUID,
        points: float,
        grader_id: uuid.UUID,
        comment: str | None = None,
    ) -> AssessmentAttempt:
        answer = await self.session.scalar(
            select(AssessmentAnswer).where(
                AssessmentAnswer.attempt_id == attempt.id,
                AssessmentAnswer.question_id == question_id,
            )
        )
        if answer is None:
            raise ResourceNotFound("Assessment answer", question_id)
        if points < 0 or points > float(answer.points_possible):
            raise ValidationError(
                f"Points must be between 0 and {float(answer.points_possible)}"
            )

        answer.points_awarded = points
        answer.is_correct = points >= float(answer.points_possible)
        answer.graded_by_id = grader_id
        answer.grader_comment = comment

        pending = [p for p in (attempt.pending_manual_review or []) if p != str(question_id)]
        attempt.pending_manual_review = pending

        # Recompute the totals from every graded answer.
        graded = (
            (
                await self.session.execute(
                    select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt.id)
                )
            )
            .scalars()
            .all()
        )
        total_awarded = sum(float(a.points_awarded or 0) for a in graded)
        total_possible = sum(float(a.points_possible or 0) for a in graded)
        attempt.score = round(total_awarded, 2)
        attempt.percentage = (
            round(total_awarded / total_possible * 100, 2) if total_possible else None
        )

        if not pending:
            assessment = await self.session.get(Assessment, attempt.assessment_id)
            attempt.status = AssessmentAttemptStatus.EVALUATED
            if assessment is not None and attempt.percentage is not None:
                attempt.passed = attempt.percentage >= float(assessment.passing_score)

        await self.session.flush()
        return attempt

    def serialise_for_candidate(self, assessment: Assessment) -> dict[str, Any]:
        """Strip answer keys and hidden test cases before sending to a candidate."""
        questions = sorted(assessment.questions, key=lambda q: q.display_order)
        return {
            "id": str(assessment.id),
            "title": assessment.title,
            "description": assessment.description,
            "duration_minutes": assessment.duration_minutes,
            "total_points": assessment.total_points,
            "questions": [
                {
                    "id": str(q.id),
                    "question_type": q.question_type.value,
                    "prompt": q.prompt,
                    "points": float(q.points),
                    "options": [
                        {"id": o.get("id"), "text": o.get("text")} for o in (q.options or [])
                    ],
                    "starter_code": q.starter_code,
                    "allowed_languages": q.allowed_languages,
                    # Only the visible examples; hidden cases never leave the server.
                    "example_test_cases": [
                        {"input": t.get("input"), "expected_output": t.get("expected_output")}
                        for t in (q.test_cases or [])
                        if not t.get("is_hidden")
                    ],
                }
                for q in questions
            ],
        }
