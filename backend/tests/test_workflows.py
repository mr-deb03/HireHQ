"""Unit tests for the workflow condition grammar and the automation guardrails."""

from __future__ import annotations

import pytest

from app.core.enums import ApplicationStatus, WorkflowActionType
from app.modules.workflows.conditions import (
    ConditionError,
    describe_field_registry,
    evaluate,
    validate_conditions,
)
from app.modules.workflows.engine import (
    HUMAN_ONLY_STATUSES,
    WorkflowValidationError,
    validate_steps,
)


class TestConditionValidation:
    def test_valid_tree_passes(self):
        validate_conditions(
            {
                "op": "AND",
                "rules": [
                    {"field": "ats_score", "operator": "gte", "value": 80},
                    {"field": "experience_years", "operator": "gte", "value": 2},
                ],
            }
        )

    def test_empty_conditions_are_allowed(self):
        validate_conditions(None)
        validate_conditions({})

    def test_unknown_field_is_rejected(self):
        """Conditions are user input; only registry fields may be referenced."""
        with pytest.raises(ConditionError, match="Unknown field"):
            validate_conditions({"field": "__class__", "operator": "eq", "value": 1})

    def test_unknown_operator_is_rejected(self):
        with pytest.raises(ConditionError, match="Unknown operator"):
            validate_conditions({"field": "ats_score", "operator": "exec", "value": 1})

    def test_operator_must_suit_the_field_type(self):
        with pytest.raises(ConditionError, match="cannot be used with"):
            validate_conditions(
                {"field": "ats_score", "operator": "includes", "value": "x"}
            )

    def test_bad_group_operator_is_rejected(self):
        with pytest.raises(ConditionError, match="group operator"):
            validate_conditions({"op": "XOR", "rules": []})

    def test_rule_count_is_capped(self):
        with pytest.raises(ConditionError, match="at most"):
            validate_conditions(
                {
                    "op": "AND",
                    "rules": [
                        {"field": "ats_score", "operator": "gte", "value": i}
                        for i in range(30)
                    ],
                }
            )


class TestConditionEvaluation:
    def test_and_requires_all(self):
        tree = {
            "op": "AND",
            "rules": [
                {"field": "ats_score", "operator": "gte", "value": 80},
                {"field": "experience_years", "operator": "gte", "value": 2},
            ],
        }
        assert evaluate(tree, {"ats_score": 85, "experience_years": 3}).passed
        assert not evaluate(tree, {"ats_score": 85, "experience_years": 1}).passed

    def test_or_requires_any(self):
        tree = {
            "op": "OR",
            "rules": [
                {"field": "ats_score", "operator": "gte", "value": 90},
                {"field": "is_referral", "operator": "is_true"},
            ],
        }
        assert evaluate(tree, {"ats_score": 50, "is_referral": True}).passed
        assert not evaluate(tree, {"ats_score": 50, "is_referral": False}).passed

    def test_missing_context_value_fails_closed(self):
        """An absent field must not accidentally satisfy a rule."""
        outcome = evaluate({"field": "ats_score", "operator": "gte", "value": 80}, {})
        assert not outcome.passed

    def test_reason_explains_the_outcome(self):
        outcome = evaluate(
            {"field": "ats_score", "operator": "gte", "value": 80}, {"ats_score": 62}
        )
        assert not outcome.passed
        assert "62" in outcome.summary and "80" in outcome.summary

    def test_empty_tree_passes(self):
        assert evaluate({}, {}).passed
        assert evaluate(None, {}).passed

    @pytest.mark.parametrize(
        ("operator", "actual", "expected", "result"),
        [
            ("eq", 80, 80, True),
            ("neq", 80, 70, True),
            ("gt", 81, 80, True),
            ("gt", 80, 80, False),
            ("lte", 80, 80, True),
            ("contains", "Senior React Developer", "react", True),
            ("in", "LINKEDIN", ["LINKEDIN", "REFERRAL"], True),
            ("includes", ["React", "AWS"], "aws", True),
            ("includes_any", ["React"], ["AWS", "React"], True),
            ("includes_all", ["React", "AWS"], ["React", "AWS"], True),
            ("includes_all", ["React"], ["React", "AWS"], False),
            ("is_empty", [], None, True),
            ("is_not_empty", ["x"], None, True),
        ],
    )
    def test_operators(self, operator, actual, expected, result):
        outcome = evaluate(
            {"field": "candidate_skills", "operator": operator, "value": expected},
            {"candidate_skills": actual},
        )
        assert outcome.passed is result

    def test_nested_groups(self):
        tree = {
            "op": "AND",
            "rules": [
                {"field": "ats_score", "operator": "gte", "value": 70},
                {
                    "op": "OR",
                    "rules": [
                        {"field": "is_referral", "operator": "is_true"},
                        {"field": "experience_years", "operator": "gte", "value": 5},
                    ],
                },
            ],
        }
        assert evaluate(tree, {"ats_score": 75, "is_referral": False,
                               "experience_years": 6}).passed
        assert not evaluate(tree, {"ats_score": 75, "is_referral": False,
                                   "experience_years": 2}).passed


class TestAutomationGuardrails:
    """The rule that automation may advance a candidate but never reject one."""

    def test_auto_shortlist_is_allowed(self):
        validate_steps(
            [
                {
                    "action_type": WorkflowActionType.CHANGE_STATUS.value,
                    "config": {"status": ApplicationStatus.SHORTLISTED.value},
                }
            ],
            requires_human_approval=False,
        )

    @pytest.mark.parametrize("status", sorted(s.value for s in HUMAN_ONLY_STATUSES))
    def test_consequential_status_needs_human_approval(self, status):
        with pytest.raises(WorkflowValidationError, match="human approval"):
            validate_steps(
                [
                    {
                        "action_type": WorkflowActionType.CHANGE_STATUS.value,
                        "config": {"status": status},
                    }
                ],
                requires_human_approval=False,
            )

    @pytest.mark.parametrize("status", sorted(s.value for s in HUMAN_ONLY_STATUSES))
    def test_consequential_status_is_allowed_with_approval(self, status):
        validate_steps(
            [
                {
                    "action_type": WorkflowActionType.CHANGE_STATUS.value,
                    "config": {"status": status},
                }
            ],
            requires_human_approval=True,
        )

    def test_reject_is_in_the_protected_set(self):
        assert ApplicationStatus.REJECTED in HUMAN_ONLY_STATUSES

    def test_invalid_status_is_rejected(self):
        with pytest.raises(WorkflowValidationError, match="not a valid"):
            validate_steps(
                [
                    {
                        "action_type": WorkflowActionType.CHANGE_STATUS.value,
                        "config": {"status": "NONSENSE"},
                    }
                ],
                requires_human_approval=True,
            )

    def test_unknown_email_template_is_rejected(self):
        with pytest.raises(WorkflowValidationError, match="unknown email template"):
            validate_steps(
                [
                    {
                        "action_type": WorkflowActionType.SEND_EMAIL.value,
                        "config": {"template_key": "MADE_UP"},
                    }
                ],
                requires_human_approval=False,
            )

    def test_step_count_is_capped(self):
        with pytest.raises(WorkflowValidationError, match="at most"):
            validate_steps(
                [
                    {
                        "action_type": WorkflowActionType.ADD_TAG.value,
                        "config": {"tag": f"t{i}"},
                    }
                    for i in range(30)
                ],
                requires_human_approval=False,
            )

    def test_delay_bounds(self):
        with pytest.raises(WorkflowValidationError, match="delay"):
            validate_steps(
                [
                    {
                        "action_type": WorkflowActionType.DELAY.value,
                        "config": {},
                        "delay_minutes": 0,
                    }
                ],
                requires_human_approval=False,
            )


class TestFieldRegistry:
    def test_registry_is_serialisable_for_the_builder_ui(self):
        fields = describe_field_registry()
        assert fields
        for field in fields:
            assert field["key"] and field["label"] and field["type"]
            assert field["operators"], f"{field['key']} must offer operators"
