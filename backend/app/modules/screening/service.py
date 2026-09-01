"""Screening question answers, scoring and the automated screening rules.

Two responsibilities:

* Recording and scoring a candidate's screening answers.
* Evaluating a company's screening rules and *recommending* a pipeline move.

The second one deliberately produces recommendations rather than performing them when
the outcome is adverse. A rule may auto-advance a candidate (shortlist, move to
assessment); an adverse outcome routes to manual review instead of rejecting (s19).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ApplicationStatus, ReviewFlag, ScreeningQuestionType
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.models.application import Application, ScreeningAnswer
from app.models.job import Job, JobScreeningQuestion
from app.utils.text import truncate

logger = get_logger(__name__)


@dataclass(slots=True)
class ScreeningOutcome:
    score: float | None
    points_awarded: float
    points_possible: float
    knockouts: list[str]
    answered: int
    required_missing: list[str]

    @property
    def has_knockout(self) -> bool:
        return bool(self.knockouts)


class ScreeningService:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID) -> None:
        self.session = session
        self.company_id = company_id

    async def record_answers(
        self,
        *,
        application: Application,
        job: Job,
        answers: list[dict[str, Any]],
    ) -> ScreeningOutcome:
        """Validate, store and score screening answers."""
        questions = {q.id: q for q in job.screening_questions}
        if not questions and answers:
            raise ValidationError("This job has no screening questions")

        provided = {uuid.UUID(str(a["question_id"])) for a in answers}
        unknown = provided - set(questions)
        if unknown:
            raise ValidationError(
                "Some answers reference questions that do not belong to this job",
                details={"unknown_question_ids": [str(u) for u in unknown]},
            )

        missing = [
            q.question for q in questions.values() if q.is_required and q.id not in provided
        ]
        if missing:
            raise ValidationError(
                "Please answer all required screening questions",
                details={"missing": missing[:10]},
            )

        points_awarded = 0.0
        points_possible = 0.0
        knockouts: list[str] = []

        for answer in answers:
            question = questions[uuid.UUID(str(answer["question_id"]))]
            self._validate_answer(question, answer)

            awarded, possible, knocked = self._score_answer(question, answer)
            points_awarded += awarded
            points_possible += possible
            if knocked:
                knockouts.append(question.question)

            self.session.add(
                ScreeningAnswer(
                    company_id=self.company_id,
                    application_id=application.id,
                    question_id=question.id,
                    question_snapshot=truncate(question.question, 2000),
                    answer_text=answer.get("answer_text"),
                    answer_number=answer.get("answer_number"),
                    answer_boolean=answer.get("answer_boolean"),
                    answer_options=answer.get("answer_options") or [],
                    points_awarded=awarded,
                    points_possible=possible,
                    knockout_triggered=knocked,
                )
            )

        score = (
            round(points_awarded / points_possible * 100, 2) if points_possible > 0 else None
        )
        application.screening_score = score
        await self.session.flush()

        if knockouts:
            # A knockout raises a flag for a human; it never rejects the application.
            candidate = application.candidate
            if candidate is not None:
                flags = list(candidate.review_flags or [])
                flags.append(
                    {
                        "code": ReviewFlag.MISSING_INFORMATION.value,
                        "message": (
                            "Screening answers fell outside the expected range for: "
                            + "; ".join(knockouts[:3])
                        ),
                        "raised_at": datetime.now(UTC).isoformat(),
                        "resolved": False,
                    }
                )
                candidate.review_flags = flags

        logger.info(
            "screening_recorded",
            application_id=str(application.id),
            score=score,
            knockouts=len(knockouts),
        )
        return ScreeningOutcome(
            score=score,
            points_awarded=points_awarded,
            points_possible=points_possible,
            knockouts=knockouts,
            answered=len(answers),
            required_missing=[],
        )

    @staticmethod
    def _validate_answer(question: JobScreeningQuestion, answer: dict[str, Any]) -> None:
        kind = question.question_type
        if kind == ScreeningQuestionType.YES_NO and answer.get("answer_boolean") is None:
            raise ValidationError(f"'{truncate(question.question, 80)}' needs a yes/no answer")
        if kind in (
            ScreeningQuestionType.NUMERIC,
            ScreeningQuestionType.EXPERIENCE,
            ScreeningQuestionType.SALARY,
            ScreeningQuestionType.NOTICE_PERIOD,
        ) and answer.get("answer_number") is None:
            raise ValidationError(f"'{truncate(question.question, 80)}' needs a number")
        if kind in (ScreeningQuestionType.SINGLE_CHOICE, ScreeningQuestionType.MULTIPLE_CHOICE):
            selected = answer.get("answer_options") or []
            if not selected:
                raise ValidationError(
                    f"'{truncate(question.question, 80)}' needs at least one selection"
                )
            invalid = [o for o in selected if o not in question.options]
            if invalid:
                raise ValidationError(
                    f"'{truncate(question.question, 80)}' received options that are not offered",
                    details={"invalid_options": invalid},
                )
            if kind == ScreeningQuestionType.SINGLE_CHOICE and len(selected) > 1:
                raise ValidationError(
                    f"'{truncate(question.question, 80)}' accepts only one option"
                )
        if kind == ScreeningQuestionType.TEXT and not (answer.get("answer_text") or "").strip():
            if question.is_required:
                raise ValidationError(f"'{truncate(question.question, 80)}' needs an answer")

    @staticmethod
    def _score_answer(
        question: JobScreeningQuestion, answer: dict[str, Any]
    ) -> tuple[float, float, bool]:
        """Score one answer. Returns ``(awarded, possible, knockout_triggered)``.

        Unscored questions contribute zero to both, so they neither help nor hurt the
        percentage - a recruiter who scores only three of ten questions still gets a
        meaningful number out of those three.
        """
        scoring = question.scoring or {}
        possible = float(scoring.get("points", 0) or 0)
        if possible <= 0:
            return 0.0, 0.0, False

        kind = question.question_type
        awarded = 0.0
        satisfied = False

        if kind == ScreeningQuestionType.YES_NO:
            expected = str(scoring.get("expected", "YES")).upper() == "YES"
            satisfied = bool(answer.get("answer_boolean")) == expected

        elif kind in (
            ScreeningQuestionType.NUMERIC,
            ScreeningQuestionType.EXPERIENCE,
            ScreeningQuestionType.SALARY,
            ScreeningQuestionType.NOTICE_PERIOD,
        ):
            value = answer.get("answer_number")
            if value is not None:
                minimum = scoring.get("min")
                maximum = scoring.get("max")
                satisfied = True
                if minimum is not None and float(value) < float(minimum):
                    satisfied = False
                if maximum is not None and float(value) > float(maximum):
                    satisfied = False
                # Partial credit for near-misses on a minimum, so "2.5 of 3 years" is not
                # scored identically to "no experience at all".
                if not satisfied and minimum is not None and float(minimum) > 0:
                    ratio = max(0.0, min(1.0, float(value) / float(minimum)))
                    awarded = round(possible * ratio * 0.5, 2)

        elif kind in (
            ScreeningQuestionType.SINGLE_CHOICE,
            ScreeningQuestionType.MULTIPLE_CHOICE,
        ):
            expected = {str(o) for o in (scoring.get("expected_options") or [])}
            selected = {str(o) for o in (answer.get("answer_options") or [])}
            if expected:
                overlap = len(expected & selected)
                satisfied = overlap == len(expected) and not (selected - expected)
                if not satisfied and overlap:
                    awarded = round(possible * overlap / len(expected) * 0.6, 2)

        elif kind == ScreeningQuestionType.TEXT:
            keywords = [str(k).lower() for k in (scoring.get("keywords") or [])]
            text = (answer.get("answer_text") or "").lower()
            if keywords:
                hits = sum(1 for k in keywords if k in text)
                satisfied = hits == len(keywords)
                if not satisfied and hits:
                    awarded = round(possible * hits / len(keywords), 2)

        if satisfied:
            awarded = possible

        knocked = question.is_knockout and not satisfied
        return awarded, possible, knocked

    # -------------------------------------------------------- screening rules
    async def evaluate_rules(
        self, application: Application, *, rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Evaluate configured screening rules and return the resulting recommendations.

        Adverse outcomes never reject: they route to manual review. Only advancing moves
        may be applied automatically, and even those are recorded as automation-assisted.
        """
        from app.modules.workflows.conditions import build_context, evaluate

        latest_score = None
        from app.models.ats import AtsScore

        latest_score = await self.session.scalar(
            select(AtsScore)
            .where(AtsScore.application_id == application.id)
            .order_by(AtsScore.created_at.desc())
            .limit(1)
        )

        context = build_context(
            application=application,
            candidate=application.candidate,
            job=application.job,
            ats_score=latest_score,
        )

        recommendations: list[dict[str, Any]] = []
        for rule in rules:
            outcome = evaluate(rule.get("conditions"), context)
            if not outcome.passed:
                continue

            target = rule.get("action", {}).get("status")
            adverse = target in (
                ApplicationStatus.REJECTED.value,
                ApplicationStatus.ON_HOLD.value,
            )
            recommendations.append(
                {
                    "rule": rule.get("name", "Unnamed rule"),
                    "matched_because": outcome.summary,
                    "recommended_status": (
                        "MANUAL_REVIEW" if adverse else target
                    ),
                    "auto_applicable": not adverse,
                    "note": (
                        "Adverse outcomes are routed to manual review rather than applied "
                        "automatically."
                        if adverse
                        else None
                    ),
                }
            )
        return recommendations

    async def get_answers(self, application_id: uuid.UUID) -> list[ScreeningAnswer]:
        result = await self.session.execute(
            select(ScreeningAnswer)
            .where(
                ScreeningAnswer.application_id == application_id,
                ScreeningAnswer.company_id == self.company_id,
            )
            .order_by(ScreeningAnswer.created_at)
        )
        return list(result.scalars().all())
