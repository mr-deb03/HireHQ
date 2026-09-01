"""Workflow condition grammar and evaluation.

A condition tree is JSON authored by recruiters:

    {"op": "AND", "rules": [
        {"field": "ats_score",             "operator": "gte", "value": 80},
        {"field": "experience_years",      "operator": "gte", "value": 2},
        {"field": "required_skills_match", "operator": "gte", "value": 70}
    ]}

Fields come from a fixed registry, not from attribute lookup on a model. That is
deliberate: a workflow is user-supplied configuration, so letting it name arbitrary
attributes would be an injection vector into the ORM. Anything not in ``FIELD_REGISTRY``
is rejected when the workflow is saved.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class FieldSpec:
    key: str
    label: str
    type: str  # number | string | boolean | enum | list | date
    description: str
    options: tuple[str, ...] = ()


FIELD_REGISTRY: dict[str, FieldSpec] = {
    "ats_score": FieldSpec(
        "ats_score", "ATS score", "number", "Overall ATS score, 0-100."
    ),
    "skills_score": FieldSpec("skills_score", "Skills match", "number", "Skills component, 0-100."),
    "experience_score": FieldSpec(
        "experience_score", "Experience match", "number", "Experience component, 0-100."
    ),
    "education_score": FieldSpec(
        "education_score", "Education match", "number", "Education component, 0-100."
    ),
    "semantic_score": FieldSpec(
        "semantic_score", "Semantic match", "number", "Semantic similarity component, 0-100."
    ),
    "required_skills_match": FieldSpec(
        "required_skills_match",
        "Required skills matched",
        "number",
        "Percentage of the job's required skills evidenced by the candidate.",
    ),
    "experience_years": FieldSpec(
        "experience_years", "Years of experience", "number", "Candidate's total experience."
    ),
    "screening_score": FieldSpec(
        "screening_score", "Screening score", "number", "Percentage score on screening questions."
    ),
    "assessment_score": FieldSpec(
        "assessment_score", "Assessment score", "number", "Latest assessment percentage."
    ),
    "notice_period_days": FieldSpec(
        "notice_period_days", "Notice period (days)", "number", "Candidate's notice period."
    ),
    "expected_salary": FieldSpec(
        "expected_salary", "Expected salary", "number", "Candidate's expected salary."
    ),
    "application_status": FieldSpec(
        "application_status", "Application status", "string", "Current pipeline status."
    ),
    "new_status": FieldSpec(
        "new_status", "New status", "string", "The status just moved into."
    ),
    "previous_status": FieldSpec(
        "previous_status", "Previous status", "string", "The status moved out of."
    ),
    "source": FieldSpec("source", "Application source", "string", "Where the application came from."),
    "job_title": FieldSpec("job_title", "Job title", "string", "Title of the job applied for."),
    "job_id": FieldSpec("job_id", "Job", "string", "The job's identifier."),
    "department": FieldSpec("department", "Department", "string", "Department of the job."),
    "employment_type": FieldSpec(
        "employment_type", "Employment type", "string", "Full-time, internship, etc."
    ),
    "candidate_location": FieldSpec(
        "candidate_location", "Candidate location", "string", "Candidate's stated location."
    ),
    "candidate_skills": FieldSpec(
        "candidate_skills", "Candidate skills", "list", "All skills on the candidate profile."
    ),
    "missing_skills": FieldSpec(
        "missing_skills", "Missing skills", "list", "Required skills with no evidence."
    ),
    "email_verified": FieldSpec(
        "email_verified", "Email verified", "boolean", "Whether the candidate verified their email."
    ),
    "has_resume": FieldSpec("has_resume", "Has resume", "boolean", "A resume has been uploaded."),
    "review_flags": FieldSpec(
        "review_flags", "Review flags", "list", "Signals raised for human review."
    ),
    "knockout_triggered": FieldSpec(
        "knockout_triggered",
        "Knockout answer given",
        "boolean",
        "A knockout screening question was answered outside the expected range.",
    ),
    "interview_recommendation": FieldSpec(
        "interview_recommendation",
        "Interview recommendation",
        "enum",
        "The interviewer's recommendation.",
        options=("STRONG_HIRE", "HIRE", "MAYBE", "NO_HIRE"),
    ),
    "interview_rating": FieldSpec(
        "interview_rating", "Interview rating", "number", "Overall interview rating, 1-5."
    ),
    "is_internal": FieldSpec(
        "is_internal", "Internal applicant", "boolean", "Applicant is an existing employee."
    ),
    "is_referral": FieldSpec("is_referral", "Referral", "boolean", "Came through a referral."),
    "days_in_status": FieldSpec(
        "days_in_status", "Days in current status", "number", "How long since the last move."
    ),
}


def _as_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).lower() for v in value]
    return [str(value).lower()]


def _compare_numeric(actual: Any, expected: Any, comparison: Callable[[float, float], bool]) -> bool:
    left, right = _as_number(actual), _as_number(expected)
    if left is None or right is None:
        return False
    return comparison(left, right)


OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda a, b: (
        _compare_numeric(a, b, lambda x, y: x == y)
        if _as_number(b) is not None and _as_number(a) is not None
        else str(a).strip().lower() == str(b).strip().lower()
    ),
    "neq": lambda a, b: not OPERATORS["eq"](a, b),
    "gt": lambda a, b: _compare_numeric(a, b, lambda x, y: x > y),
    "gte": lambda a, b: _compare_numeric(a, b, lambda x, y: x >= y),
    "lt": lambda a, b: _compare_numeric(a, b, lambda x, y: x < y),
    "lte": lambda a, b: _compare_numeric(a, b, lambda x, y: x <= y),
    "contains": lambda a, b: str(b).strip().lower() in str(a).strip().lower(),
    "not_contains": lambda a, b: str(b).strip().lower() not in str(a).strip().lower(),
    "in": lambda a, b: str(a).strip().lower() in _as_list(b),
    "not_in": lambda a, b: str(a).strip().lower() not in _as_list(b),
    "includes": lambda a, b: str(b).strip().lower() in _as_list(a),
    "not_includes": lambda a, b: str(b).strip().lower() not in _as_list(a),
    "includes_any": lambda a, b: bool(set(_as_list(a)) & set(_as_list(b))),
    "includes_all": lambda a, b: set(_as_list(b)).issubset(set(_as_list(a))),
    "is_true": lambda a, _b: bool(a) is True,
    "is_false": lambda a, _b: bool(a) is False,
    "is_empty": lambda a, _b: not a,
    "is_not_empty": lambda a, _b: bool(a),
}

#: Which operators make sense for which field type - used to validate on save and to
#: drive the workflow builder UI.
OPERATORS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "number": ("eq", "neq", "gt", "gte", "lt", "lte"),
    "string": ("eq", "neq", "contains", "not_contains", "in", "not_in", "is_empty", "is_not_empty"),
    "enum": ("eq", "neq", "in", "not_in"),
    "boolean": ("is_true", "is_false", "eq"),
    "list": ("includes", "not_includes", "includes_any", "includes_all", "is_empty", "is_not_empty"),
    "date": ("gt", "gte", "lt", "lte"),
}


class ConditionError(ValueError):
    """Raised when a condition tree is malformed or references an unknown field."""


@dataclass(slots=True)
class Evaluation:
    passed: bool
    #: Human-readable trace, e.g. ``"ats_score 62 >= 80 -> false"``. Surfaced in the UI
    #: so a recruiter can see exactly why a workflow did or did not fire.
    reasons: list[str]

    @property
    def summary(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "no conditions"


def validate_conditions(node: dict | None) -> None:
    """Validate a condition tree, raising ``ConditionError`` on any problem."""
    if not node:
        return
    if not isinstance(node, dict):
        raise ConditionError("A condition group must be an object")

    if "rules" in node:
        operator = str(node.get("op", "AND")).upper()
        if operator not in ("AND", "OR"):
            raise ConditionError(f"Unknown group operator {operator!r}; use AND or OR")
        rules = node.get("rules")
        if not isinstance(rules, list):
            raise ConditionError("'rules' must be a list")
        if len(rules) > 25:
            raise ConditionError("A condition group may contain at most 25 rules")
        for rule in rules:
            validate_conditions(rule)
        return

    field = node.get("field")
    if field not in FIELD_REGISTRY:
        raise ConditionError(
            f"Unknown field {field!r}. Allowed fields: {', '.join(sorted(FIELD_REGISTRY))}"
        )
    operator = node.get("operator")
    if operator not in OPERATORS:
        raise ConditionError(
            f"Unknown operator {operator!r}. Allowed: {', '.join(sorted(OPERATORS))}"
        )
    spec = FIELD_REGISTRY[field]
    allowed = OPERATORS_BY_TYPE.get(spec.type, ())
    if allowed and operator not in allowed:
        raise ConditionError(
            f"Operator {operator!r} cannot be used with {spec.label} "
            f"({spec.type}). Allowed: {', '.join(allowed)}"
        )


def evaluate(node: dict | None, context: dict[str, Any]) -> Evaluation:
    """Evaluate a condition tree against a workflow context."""
    if not node:
        return Evaluation(True, [])

    if "rules" in node:
        operator = str(node.get("op", "AND")).upper()
        rules = node.get("rules") or []
        if not rules:
            return Evaluation(True, [])
        results = [evaluate(rule, context) for rule in rules]
        reasons = [reason for result in results for reason in result.reasons]
        passed = (
            all(r.passed for r in results) if operator == "AND" else any(r.passed for r in results)
        )
        return Evaluation(passed, reasons)

    field = node.get("field")
    operator = node.get("operator")
    expected = node.get("value")

    if field not in FIELD_REGISTRY or operator not in OPERATORS:
        return Evaluation(False, [f"invalid rule ({field} {operator})"])

    actual = context.get(field)
    try:
        passed = OPERATORS[operator](actual, expected)
    except Exception:
        passed = False

    rendered_actual = (
        ", ".join(str(v) for v in actual[:5]) if isinstance(actual, list) else actual
    )
    reason = (
        f"{field} ({rendered_actual}) {operator}"
        + ("" if operator.startswith("is_") else f" {expected}")
        + f" -> {'pass' if passed else 'fail'}"
    )
    return Evaluation(passed, [reason])


def build_context(
    *,
    application: Any = None,
    candidate: Any = None,
    job: Any = None,
    ats_score: Any = None,
    event_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the flat context that conditions are evaluated against.

    Everything a condition can reference is materialised here, so evaluation itself needs
    no database access and is trivially unit-testable.
    """
    context: dict[str, Any] = {}

    if application is not None:
        context.update(
            application_status=application.status.value,
            source=application.source.value,
            notice_period_days=application.notice_period_days,
            expected_salary=(
                float(application.expected_salary) if application.expected_salary else None
            ),
            screening_score=(
                float(application.screening_score) if application.screening_score is not None else None
            ),
            ats_score=float(application.ats_score) if application.ats_score is not None else None,
            has_resume=application.resume_id is not None,
            is_referral=application.referral_id is not None,
            job_id=str(application.job_id),
        )
        if application.status_changed_at:
            delta = datetime.now(UTC) - application.status_changed_at
            context["days_in_status"] = round(delta.total_seconds() / 86400, 2)

    if candidate is not None:
        context.update(
            experience_years=float(candidate.total_experience_years or 0),
            candidate_location=candidate.location or "",
            candidate_skills=[s.name for s in candidate.skills],
            email_verified=candidate.email_verified,
            review_flags=[f.get("code", "") for f in (candidate.review_flags or [])],
            is_internal=candidate.is_internal_employee,
        )

    if job is not None:
        context.update(
            job_title=job.title,
            employment_type=job.employment_type.value,
            job_id=str(job.id),
        )

    if ats_score is not None:
        required_total = (ats_score.explanation or {}).get("components", {}).get(
            "skills", {}
        ).get("details", {}).get("required_total", 0)
        required_matched = (ats_score.explanation or {}).get("components", {}).get(
            "skills", {}
        ).get("details", {}).get("required_matched", 0)
        context.update(
            ats_score=float(ats_score.overall_score),
            skills_score=float(ats_score.skills_score),
            experience_score=float(ats_score.experience_score),
            education_score=float(ats_score.education_score),
            semantic_score=float(ats_score.semantic_score),
            missing_skills=ats_score.missing_skills,
            required_skills_match=(
                round(required_matched / required_total * 100, 2) if required_total else 100.0
            ),
        )

    if event_payload:
        for key in ("new_status", "previous_status", "interview_recommendation", "interview_rating",
                    "assessment_score", "knockout_triggered"):
            if key in event_payload:
                context[key] = event_payload[key]

    return context


def describe_field_registry() -> list[dict[str, Any]]:
    """Serialise the registry for the workflow-builder UI."""
    return [
        {
            "key": spec.key,
            "label": spec.label,
            "type": spec.type,
            "description": spec.description,
            "options": list(spec.options),
            "operators": list(OPERATORS_BY_TYPE.get(spec.type, ())),
        }
        for spec in sorted(FIELD_REGISTRY.values(), key=lambda s: s.label)
    ]
