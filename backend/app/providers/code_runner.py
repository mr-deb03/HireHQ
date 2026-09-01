"""Code execution for coding and SQL assessment questions.

Running untrusted candidate code is the single most dangerous thing this product could
do, so the default is to **not do it**: submissions are stored and routed to a human
grader, and the API says so rather than inventing a pass/fail.

Where a team does want automated grading, this abstraction lets them point HireHQ at a
sandbox they operate (Judge0, Piston, or an internal runner). Three properties are
non-negotiable for any implementation:

* execution happens **outside** this process and this network,
* every run is bounded in wall-clock time and memory,
* a failure to execute is reported as *not graded*, never as *failed*.

The SQL runner is different in kind: a query against a disposable in-memory SQLite
database is genuinely safe to run in-process, because SQLite can be opened read-only with
no filesystem, network, or extension access. That one is implemented here.
"""

from __future__ import annotations

import asyncio
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Hard ceilings applied to every run, whatever the provider.
DEFAULT_TIMEOUT_SECONDS = 10
MAX_OUTPUT_CHARS = 10_000


@dataclass(slots=True)
class TestCaseResult:
    #: Tells pytest this is a domain type, not a test class, despite the "Test" prefix.
    __test__ = False

    name: str
    passed: bool
    expected: str | None = None
    actual: str | None = None
    error: str | None = None
    duration_ms: int | None = None
    #: Hidden cases never expose their input or expected output to the candidate.
    is_hidden: bool = False

    def for_candidate(self) -> dict:
        """The candidate-safe view: pass/fail only for hidden cases."""
        if self.is_hidden:
            return {"name": self.name, "passed": self.passed, "hidden": True}
        return {
            "name": self.name,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "error": self.error,
        }


@dataclass(slots=True)
class ExecutionResult:
    #: False means "we could not run this", which is different from "it failed".
    executed: bool
    results: list[TestCaseResult] = field(default_factory=list)
    stdout: str | None = None
    stderr: str | None = None
    detail: str | None = None

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def score_fraction(self) -> float | None:
        """Fraction of cases passed, or ``None`` when nothing was executed."""
        if not self.executed or not self.results:
            return None
        return self.passed_count / len(self.results)


class CodeRunner(ABC):
    name: str = "abstract"
    #: False means submissions must be graded by a person.
    executes: bool = False
    languages: tuple[str, ...] = ()

    @abstractmethod
    async def run(
        self,
        *,
        language: str,
        source: str,
        test_cases: list[dict],
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> ExecutionResult: ...


class ManualReviewRunner(CodeRunner):
    """The default. Stores the submission for a human and grades nothing."""

    name = "manual"
    executes = False

    async def run(
        self, *, language: str, source: str, test_cases: list[dict], timeout_seconds: int = 10
    ) -> ExecutionResult:
        return ExecutionResult(
            executed=False,
            detail=(
                "No code execution sandbox is configured, so this submission has been "
                "stored for review by the hiring team rather than graded automatically."
            ),
        )


class SqliteQueryRunner(CodeRunner):
    """Runs SQL answers against a disposable in-memory database.

    Safe to do in-process: the database is created per run from the question's own schema,
    lives only in memory, is dropped immediately afterwards, and the connection is opened
    with no extension loading. A runaway query is bounded by a progress handler rather
    than a thread that cannot be killed.
    """

    name = "sqlite"
    executes = True
    languages = ("sql", "sqlite")

    async def run(
        self,
        *,
        language: str,
        source: str,
        test_cases: list[dict],
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> ExecutionResult:
        if language.lower() not in self.languages:
            return ExecutionResult(
                executed=False,
                detail=f"The SQL runner cannot execute '{language}' submissions.",
            )
        return await asyncio.to_thread(self._run_sync, source, test_cases, timeout_seconds)

    @staticmethod
    def _make_guard(limit: int):
        """Build a progress handler that aborts a query once it exceeds its step budget.

        Bounding total work is more reliable than a wall-clock timeout here: SQLite runs
        inside this thread and cannot be interrupted from outside, but the progress
        handler fires every N VM instructions and can return non-zero to abort.
        """
        budget = {"steps": 0}

        def guard() -> int:
            budget["steps"] += 1000
            return 1 if budget["steps"] > limit else 0

        return guard

    def _run_sync(
        self, source: str, test_cases: list[dict], timeout_seconds: int
    ) -> ExecutionResult:
        results: list[TestCaseResult] = []
        step_limit = timeout_seconds * 2_000_000

        for index, case in enumerate(test_cases):
            schema = case.get("schema") or case.get("input") or ""
            expected = (case.get("expected_output") or "").strip()
            name = case.get("name") or f"Case {index + 1}"

            connection = sqlite3.connect(":memory:")
            try:
                # A fresh budget per case, so one slow query cannot exhaust the next one's.
                connection.set_progress_handler(self._make_guard(step_limit), 1000)

                if schema:
                    connection.executescript(schema)
                cursor = connection.execute(source)
                rows = cursor.fetchmany(1000)
                actual = "\n".join(
                    "|".join("" if v is None else str(v) for v in row) for row in rows
                ).strip()

                results.append(
                    TestCaseResult(
                        name=name,
                        passed=_normalise(actual) == _normalise(expected),
                        expected=expected[:MAX_OUTPUT_CHARS],
                        actual=actual[:MAX_OUTPUT_CHARS],
                        is_hidden=bool(case.get("is_hidden")),
                    )
                )
            except sqlite3.Error as exc:
                results.append(
                    TestCaseResult(
                        name=name,
                        passed=False,
                        expected=expected[:MAX_OUTPUT_CHARS],
                        error=str(exc)[:500],
                        is_hidden=bool(case.get("is_hidden")),
                    )
                )
            finally:
                connection.close()

        return ExecutionResult(executed=True, results=results)


class RemoteSandboxRunner(CodeRunner):
    """Delegates to an external execution sandbox over HTTP.

    Targets the Judge0-compatible shape, which Piston and most self-hosted runners also
    expose. Nothing is executed inside the HireHQ process or network.
    """

    name = "remote"
    executes = True
    languages = (
        "python", "javascript", "typescript", "java", "c", "cpp", "csharp",
        "go", "ruby", "php", "rust", "kotlin", "swift",
    )

    def __init__(self) -> None:
        if not settings.CODE_RUNNER_URL:
            from app.core.exceptions import ProviderNotConfigured

            raise ProviderNotConfigured(
                "Code runner", hint="Set CODE_RUNNER_URL to your sandbox endpoint."
            )
        self.endpoint = settings.CODE_RUNNER_URL.rstrip("/")

    async def run(
        self,
        *,
        language: str,
        source: str,
        test_cases: list[dict],
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> ExecutionResult:
        import httpx

        headers = {"Content-Type": "application/json"}
        if settings.CODE_RUNNER_TOKEN:
            headers["Authorization"] = f"Bearer {settings.CODE_RUNNER_TOKEN}"

        results: list[TestCaseResult] = []
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds * len(test_cases) + 30) as client:
                for index, case in enumerate(test_cases):
                    response = await client.post(
                        f"{self.endpoint}/submissions?wait=true",
                        headers=headers,
                        json={
                            "language": language,
                            "source_code": source,
                            "stdin": case.get("input", ""),
                            "expected_output": case.get("expected_output", ""),
                            "cpu_time_limit": timeout_seconds,
                        },
                    )
                    name = case.get("name") or f"Case {index + 1}"
                    if response.status_code >= 400:
                        results.append(
                            TestCaseResult(
                                name=name,
                                passed=False,
                                error=f"Sandbox returned {response.status_code}",
                                is_hidden=bool(case.get("is_hidden")),
                            )
                        )
                        continue

                    body = response.json()
                    actual = (body.get("stdout") or "").strip()
                    expected = (case.get("expected_output") or "").strip()
                    results.append(
                        TestCaseResult(
                            name=name,
                            passed=_normalise(actual) == _normalise(expected),
                            expected=expected[:MAX_OUTPUT_CHARS],
                            actual=actual[:MAX_OUTPUT_CHARS],
                            error=(body.get("stderr") or body.get("compile_output") or None),
                            duration_ms=int(float(body.get("time") or 0) * 1000),
                            is_hidden=bool(case.get("is_hidden")),
                        )
                    )
        except Exception as exc:
            logger.warning("code_runner_failed", error=str(exc)[:300])
            # Unreachable sandbox means "not graded", never "failed".
            return ExecutionResult(
                executed=False,
                detail=(
                    f"The code execution sandbox could not be reached ({exc}). This "
                    "submission has been stored for manual review."
                )[:500],
            )

        return ExecutionResult(executed=True, results=results)


def _normalise(value: str) -> str:
    """Compare outputs ignoring trailing whitespace, which is never the point of a test."""
    return "\n".join(line.rstrip() for line in (value or "").strip().splitlines())


@lru_cache(maxsize=1)
def get_code_runner() -> CodeRunner:
    if settings.CODE_RUNNER == "remote":
        try:
            runner = RemoteSandboxRunner()
            logger.info("code_runner_selected", runner="remote", endpoint=runner.endpoint)
            return runner
        except Exception as exc:
            logger.warning("code_runner_unavailable", detail=str(exc)[:200])
            return ManualReviewRunner()
    if settings.CODE_RUNNER == "sqlite":
        logger.info("code_runner_selected", runner="sqlite", note="SQL questions only")
        return SqliteQueryRunner()
    logger.info(
        "code_runner_selected",
        runner="manual",
        note="Coding submissions are stored for human grading.",
    )
    return ManualReviewRunner()


def get_runner_for_language(language: str | None) -> CodeRunner:
    """Pick the runner able to handle one submission.

    SQL is always safe to run locally even when no external sandbox is configured, so a
    SQL question is graded automatically while a Python question in the same assessment
    still routes to a human.
    """
    configured = get_code_runner()
    normalised = (language or "").lower()

    if normalised in SqliteQueryRunner.languages:
        if configured.executes and normalised in configured.languages:
            return configured
        return SqliteQueryRunner()

    if configured.executes and normalised in configured.languages:
        return configured

    # The configured runner cannot handle this language. Fall back to human grading, so
    # the candidate is told their answer is awaiting review rather than being handed an
    # internal message about which runner was tried.
    return ManualReviewRunner()


def reset_code_runner() -> None:
    get_code_runner.cache_clear()
