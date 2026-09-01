"""Assessment auto-grading, including executed coding and SQL answers.

The rule under test throughout: HireHQ grades what it can genuinely verify and reports
everything else as awaiting a human. It never converts "we could not run this" into a
zero, and it never lets a hidden test case leak its inputs to the candidate.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.enums import AssessmentAttemptStatus, AssessmentQuestionType
from app.models.assessment import (
    Assessment,
    AssessmentAnswer,
    AssessmentAttempt,
    AssessmentQuestion,
)
from app.modules.assessments.service import AssessmentService

SCHEMA = """
CREATE TABLE employees (id INTEGER, name TEXT, dept TEXT, salary INTEGER);
INSERT INTO employees VALUES (1, 'Asha', 'Eng', 120), (2, 'Ravi', 'Eng', 90),
                            (3, 'Meera', 'Sales', 80);
"""
TOP_EARNER_SQL = "SELECT name FROM employees WHERE dept='Eng' ORDER BY salary DESC LIMIT 1"


@pytest.fixture
async def application(session, company, recruiter):
    """A minimal job + candidate + application to hang an attempt off."""
    from app.core.enums import (
        ApplicationSource,
        ApplicationStatus,
        EmploymentType,
        JobStatus,
    )
    from app.models.application import Application
    from app.models.candidate import Candidate
    from app.models.job import Job

    job = Job(
        company_id=company.id,
        title="Data Analyst",
        slug=f"data-analyst-{company.id.hex[:6]}",
        reference_code=f"JOB-{company.id.hex[:6].upper()}",
        description="Analysis",
        employment_type=EmploymentType.FULL_TIME,
        status=JobStatus.PUBLISHED,
        created_by_id=recruiter.id,
    )
    candidate = Candidate(
        company_id=company.id,
        first_name="Nina",
        last_name="Analyst",
        email=f"nina-{company.id.hex[:6]}@example.test",
    )
    session.add_all([job, candidate])
    await session.flush()

    record = Application(
        company_id=company.id,
        reference_code=f"APP-{company.id.hex[:8].upper()}",
        job_id=job.id,
        candidate_id=candidate.id,
        status=ApplicationStatus.APPLIED,
        source=ApplicationSource.DIRECT,
    )
    session.add(record)
    await session.commit()
    return record


async def _assessment(session, company, *, questions: list[AssessmentQuestion]) -> Assessment:
    record = Assessment(
        company_id=company.id, title="Screen", category="MIXED", duration_minutes=45
    )
    session.add(record)
    await session.flush()
    for index, question in enumerate(questions, start=1):
        question.assessment_id = record.id
        question.display_order = index
    session.add_all(questions)
    await session.flush()
    return record


async def _attempt(session, company, application, assessment) -> AssessmentAttempt:
    record = AssessmentAttempt(
        company_id=company.id,
        assessment_id=assessment.id,
        application_id=application.id,
        candidate_id=application.candidate_id,
        status=AssessmentAttemptStatus.IN_PROGRESS,
    )
    session.add(record)
    await session.flush()
    return record


def _sql_question(points: float = 10, *, hidden_case: bool = False) -> AssessmentQuestion:
    cases = [{"name": "top earner", "schema": SCHEMA, "expected_output": "Asha"}]
    if hidden_case:
        cases.append(
            {
                "name": "secret",
                "schema": SCHEMA,
                "expected_output": "Meera",
                "is_hidden": True,
            }
        )
    return AssessmentQuestion(
        question_type=AssessmentQuestionType.SQL,
        prompt="Highest paid engineer",
        points=points,
        test_cases=cases,
    )


def _coding_question(points: float = 10) -> AssessmentQuestion:
    return AssessmentQuestion(
        question_type=AssessmentQuestionType.CODING,
        prompt="Reverse a string",
        points=points,
        test_cases=[{"name": "basic", "input": "abc", "expected_output": "cba"}],
    )


async def _answers(session, attempt) -> dict[str, AssessmentAnswer]:
    rows = (
        await session.execute(
            select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt.id)
        )
    ).scalars().all()
    return {str(row.question_id): row for row in rows}


class TestSqlGrading:
    async def test_correct_sql_is_scored_automatically(
        self, session, company, application
    ):
        question = _sql_question()
        assessment = await _assessment(session, company, questions=[question])
        attempt = await _attempt(session, company, application, assessment)

        result = await AssessmentService(session, company.id).submit(
            attempt,
            [{"question_id": str(question.id), "language": "sql",
              "code_submission": TOP_EARNER_SQL}],
        )

        assert float(result.score) == 10.0
        assert result.pending_manual_review == []
        assert result.passed is True

        answer = (await _answers(session, attempt))[str(question.id)]
        assert answer.is_correct is True
        assert answer.test_results[0]["passed"] is True

    async def test_wrong_sql_scores_zero_not_pending(self, session, company, application):
        """A query that ran and produced the wrong answer *is* a fail - that is a real
        verified result, unlike a submission that could not be executed."""
        question = _sql_question()
        assessment = await _assessment(session, company, questions=[question])
        attempt = await _attempt(session, company, application, assessment)

        result = await AssessmentService(session, company.id).submit(
            attempt,
            [{"question_id": str(question.id), "language": "sql",
              "code_submission": "SELECT name FROM employees LIMIT 1 OFFSET 2"}],
        )

        assert float(result.score) == 0.0
        assert result.pending_manual_review == []
        assert result.passed is False

    async def test_partial_credit_reflects_cases_passed(
        self, session, company, application
    ):
        question = _sql_question(points=10, hidden_case=True)
        assessment = await _assessment(session, company, questions=[question])
        attempt = await _attempt(session, company, application, assessment)

        result = await AssessmentService(session, company.id).submit(
            attempt,
            [{"question_id": str(question.id), "language": "sql",
              "code_submission": TOP_EARNER_SQL}],
        )

        assert float(result.score) == 5.0  # one of two cases

    async def test_hidden_case_detail_is_not_stored_on_the_answer(
        self, session, company, application
    ):
        """``test_results`` is served to the candidate, so it must carry only pass/fail
        for hidden cases - never their expected output."""
        question = _sql_question(hidden_case=True)
        assessment = await _assessment(session, company, questions=[question])
        attempt = await _attempt(session, company, application, assessment)

        await AssessmentService(session, company.id).submit(
            attempt,
            [{"question_id": str(question.id), "language": "sql",
              "code_submission": TOP_EARNER_SQL}],
        )

        answer = (await _answers(session, attempt))[str(question.id)]
        hidden = [r for r in answer.test_results if r.get("hidden")]
        assert len(hidden) == 1
        assert "expected" not in hidden[0]
        assert "Meera" not in str(answer.test_results)


class TestUngradableSubmissions:
    async def test_coding_without_a_sandbox_awaits_review(
        self, session, company, application
    ):
        """No score is invented, and crucially no zero is recorded."""
        question = _coding_question()
        assessment = await _assessment(session, company, questions=[question])
        attempt = await _attempt(session, company, application, assessment)

        result = await AssessmentService(session, company.id).submit(
            attempt,
            [{"question_id": str(question.id), "language": "python",
              "code_submission": "def r(s): return s[::-1]"}],
        )

        assert result.pending_manual_review == [str(question.id)]
        answer = (await _answers(session, attempt))[str(question.id)]
        assert answer.points_awarded is None
        assert answer.is_correct is None
        assert answer.code_submission == "def r(s): return s[::-1]"

    async def test_pending_review_withholds_the_pass_verdict(
        self, session, company, application
    ):
        """Passing must not be declared while part of the assessment is ungraded."""
        sql, coding = _sql_question(), _coding_question()
        assessment = await _assessment(session, company, questions=[sql, coding])
        attempt = await _attempt(session, company, application, assessment)

        result = await AssessmentService(session, company.id).submit(
            attempt,
            [
                {"question_id": str(sql.id), "language": "sql",
                 "code_submission": TOP_EARNER_SQL},
                {"question_id": str(coding.id), "language": "python",
                 "code_submission": "def r(s): return s[::-1]"},
            ],
        )

        assert result.passed is None
        assert len(result.pending_manual_review) == 1
        # The percentage covers only the graded half, and says so via pending_manual_review.
        assert float(result.percentage) == 100.0
        assert float(result.score) == 10.0
        assert float(result.max_score) == 20.0

    async def test_question_without_test_cases_awaits_review(
        self, session, company, application
    ):
        question = AssessmentQuestion(
            question_type=AssessmentQuestionType.SQL,
            prompt="Explain your indexing strategy",
            points=5,
            test_cases=[],
        )
        assessment = await _assessment(session, company, questions=[question])
        attempt = await _attempt(session, company, application, assessment)

        result = await AssessmentService(session, company.id).submit(
            attempt,
            [{"question_id": str(question.id), "language": "sql",
              "code_submission": "SELECT 1"}],
        )

        assert result.pending_manual_review == [str(question.id)]

    async def test_empty_submission_is_not_marked_wrong(
        self, session, company, application
    ):
        """An unanswered coding question goes to a human, who can see it was left blank."""
        question = _coding_question()
        assessment = await _assessment(session, company, questions=[question])
        attempt = await _attempt(session, company, application, assessment)

        result = await AssessmentService(session, company.id).submit(
            attempt, [{"question_id": str(question.id), "language": "python"}]
        )

        assert result.pending_manual_review == [str(question.id)]
        assert (await _answers(session, attempt))[str(question.id)].points_awarded is None
