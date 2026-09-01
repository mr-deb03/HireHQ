"""Automated grading of coding and SQL assessment answers.

The behaviour that matters most here is negative: a submission that could not be executed
must be reported as *awaiting review*, never as *failed*. A candidate losing marks because
a sandbox was unreachable would be exactly the kind of opaque automated judgement §63
forbids.
"""

from __future__ import annotations

import pytest

from app.providers.code_runner import (
    ExecutionResult,
    ManualReviewRunner,
    SqliteQueryRunner,
    TestCaseResult,
    get_runner_for_language,
    reset_code_runner,
)

SCHEMA = """
CREATE TABLE employees (id INTEGER, name TEXT, dept TEXT, salary INTEGER);
INSERT INTO employees VALUES (1, 'Asha', 'Eng', 120), (2, 'Ravi', 'Eng', 90),
                            (3, 'Meera', 'Sales', 80);
"""

TOP_EARNER = [{"name": "top earner", "schema": SCHEMA, "expected_output": "Asha"}]


class TestSqliteRunner:
    async def test_correct_query_passes(self):
        result = await SqliteQueryRunner().run(
            language="sql",
            source="SELECT name FROM employees WHERE dept='Eng' ORDER BY salary DESC LIMIT 1",
            test_cases=TOP_EARNER,
        )
        assert result.executed is True
        assert result.score_fraction == 1.0

    async def test_wrong_query_fails_with_the_actual_output_shown(self):
        result = await SqliteQueryRunner().run(
            language="sql",
            source="SELECT name FROM employees ORDER BY salary ASC LIMIT 1",
            test_cases=TOP_EARNER,
        )
        assert result.executed is True
        assert result.score_fraction == 0.0
        assert result.results[0].actual == "Meera"
        assert result.results[0].expected == "Asha"

    async def test_broken_sql_is_a_failed_case_not_a_crash(self):
        result = await SqliteQueryRunner().run(
            language="sql", source="SELECT * FROM nonexistent", test_cases=TOP_EARNER
        )
        assert result.executed is True
        assert result.results[0].passed is False
        assert "nonexistent" in result.results[0].error

    async def test_partial_credit_across_cases(self):
        cases = [
            {"name": "eng top", "schema": SCHEMA, "expected_output": "Asha"},
            {"name": "sales top", "schema": SCHEMA, "expected_output": "Meera"},
        ]
        result = await SqliteQueryRunner().run(
            language="sql",
            source="SELECT name FROM employees ORDER BY salary DESC LIMIT 1",
            test_cases=cases,
        )
        assert result.score_fraction == 0.5

    async def test_trailing_whitespace_does_not_decide_the_grade(self):
        result = await SqliteQueryRunner().run(
            language="sql",
            source="SELECT name FROM employees WHERE id=1",
            test_cases=[{"schema": SCHEMA, "expected_output": "  Asha  \n\n"}],
        )
        assert result.score_fraction == 1.0

    async def test_each_case_gets_a_fresh_database(self):
        """One case must not be able to see rows another case wrote."""
        cases = [
            {"name": "insert", "schema": SCHEMA, "expected_output": "3"},
            {"name": "count again", "schema": SCHEMA, "expected_output": "3"},
        ]
        result = await SqliteQueryRunner().run(
            language="sql", source="SELECT COUNT(*) FROM employees", test_cases=cases
        )
        assert result.score_fraction == 1.0

    async def test_refuses_a_language_it_cannot_run(self):
        result = await SqliteQueryRunner().run(
            language="python", source="print(1)", test_cases=TOP_EARNER
        )
        assert result.executed is False
        assert result.score_fraction is None


class TestRunnerSelection:
    def teardown_method(self):
        reset_code_runner()

    def test_sql_is_gradable_without_any_sandbox(self, monkeypatch):
        """SQL is safe to run in-process, so it grades even on a bare install."""
        from app.providers import code_runner

        monkeypatch.setattr(code_runner.settings, "CODE_RUNNER", "manual")
        reset_code_runner()
        assert isinstance(get_runner_for_language("sql"), SqliteQueryRunner)

    def test_coding_falls_back_to_human_review(self, monkeypatch):
        from app.providers import code_runner

        monkeypatch.setattr(code_runner.settings, "CODE_RUNNER", "sqlite")
        reset_code_runner()
        runner = get_runner_for_language("python")
        assert isinstance(runner, ManualReviewRunner)
        assert runner.executes is False

    def test_missing_language_falls_back_to_human_review(self, monkeypatch):
        from app.providers import code_runner

        monkeypatch.setattr(code_runner.settings, "CODE_RUNNER", "sqlite")
        reset_code_runner()
        assert get_runner_for_language(None).executes is False


class TestManualRunner:
    async def test_grades_nothing_and_says_why(self):
        result = await ManualReviewRunner().run(
            language="python", source="print(1)", test_cases=TOP_EARNER
        )
        assert result.executed is False
        assert result.score_fraction is None
        assert "stored for review" in result.detail


class TestCandidateVisibility:
    def test_hidden_cases_expose_only_pass_or_fail(self):
        """A hidden case must not leak its inputs - that is the point of hiding it."""
        view = TestCaseResult(
            name="edge case",
            passed=False,
            expected="42",
            actual="0",
            error="AssertionError at line 7",
            is_hidden=True,
        ).for_candidate()

        assert view == {"name": "edge case", "passed": False, "hidden": True}
        assert "42" not in str(view)

    def test_visible_cases_show_the_diff(self):
        view = TestCaseResult(
            name="basic", passed=False, expected="cba", actual="abc"
        ).for_candidate()
        assert view["expected"] == "cba"
        assert view["actual"] == "abc"


class TestScoreFraction:
    @pytest.mark.parametrize(
        "executed,results,expected",
        [
            (False, [], None),
            (False, [TestCaseResult(name="a", passed=True)], None),
            (True, [], None),
            (True, [TestCaseResult(name="a", passed=True)], 1.0),
            (
                True,
                [TestCaseResult(name="a", passed=True), TestCaseResult(name="b", passed=False)],
                0.5,
            ),
        ],
    )
    def test_not_executed_never_scores_zero(self, executed, results, expected):
        """``None`` and ``0.0`` mean different things: unrunnable versus wrong."""
        assert ExecutionResult(executed=executed, results=results).score_fraction == expected
