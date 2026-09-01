"""Unit tests for application status transitions and screening scoring."""

from __future__ import annotations

import pytest

from app.core.enums import ApplicationStatus as S
from app.core.exceptions import InvalidStateTransition
from app.modules.applications.state_machine import (
    PIPELINE_ORDER,
    allowed_transitions,
    assert_transition,
    can_transition,
    candidate_label,
    is_terminal,
    reached_stage,
)


class TestTransitions:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (S.APPLIED, S.UNDER_REVIEW),
            (S.APPLIED, S.SHORTLISTED),
            (S.UNDER_REVIEW, S.SHORTLISTED),
            (S.SHORTLISTED, S.INTERVIEW),
            (S.INTERVIEW, S.OFFER),
            (S.OFFER, S.OFFER_ACCEPTED),
            (S.OFFER_ACCEPTED, S.HIRED),
        ],
    )
    def test_valid_forward_moves(self, current, target):
        assert can_transition(current, target)

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (S.HIRED, S.APPLIED),
            (S.REJECTED, S.SHORTLISTED),
            (S.WITHDRAWN, S.INTERVIEW),
            (S.APPLIED, S.HIRED),
            (S.APPLIED, S.OFFER),
        ],
    )
    def test_invalid_moves(self, current, target):
        assert not can_transition(current, target)

    def test_cannot_transition_to_itself(self):
        assert not can_transition(S.APPLIED, S.APPLIED)

    def test_terminal_states_are_final(self):
        for status in (S.HIRED, S.REJECTED, S.WITHDRAWN, S.OFFER_REJECTED):
            assert is_terminal(status)
            assert allowed_transitions(status) == []

    def test_on_hold_can_return_to_the_pipeline(self):
        """A paused application must be resumable, or ON_HOLD becomes a trap."""
        options = allowed_transitions(S.ON_HOLD)
        assert S.SHORTLISTED in options
        assert S.INTERVIEW in options

    def test_additional_interview_round_is_a_no_op_not_a_transition(self):
        """Scheduling round two keeps the status at INTERVIEW.

        Re-entering the same status is deliberately not a transition, so the pipeline
        does not record a spurious status-change event for every extra round. The
        interview service adds the round without touching status.
        """
        assert not can_transition(S.INTERVIEW, S.INTERVIEW)
        with pytest.raises(InvalidStateTransition, match="already"):
            assert_transition(S.INTERVIEW, S.INTERVIEW)
        # But a round can still conclude in either direction.
        assert can_transition(S.INTERVIEW, S.INTERVIEW_PASSED)
        assert can_transition(S.INTERVIEW_FAILED, S.INTERVIEW)

    def test_anything_live_can_be_withdrawn(self):
        for status in (S.APPLIED, S.UNDER_REVIEW, S.SHORTLISTED, S.INTERVIEW, S.OFFER):
            assert can_transition(status, S.WITHDRAWN)


class TestAssertTransition:
    def test_valid_transition_is_silent(self):
        assert assert_transition(S.APPLIED, S.SHORTLISTED) is None

    def test_same_status_explains_itself(self):
        with pytest.raises(InvalidStateTransition) as exc:
            assert_transition(S.APPLIED, S.APPLIED)
        assert "already" in exc.value.message.lower()

    def test_terminal_state_error_names_the_state(self):
        with pytest.raises(InvalidStateTransition) as exc:
            assert_transition(S.HIRED, S.INTERVIEW)
        assert "hired" in exc.value.message.lower()

    def test_error_lists_what_is_allowed(self):
        """A rejected move must tell the caller what it could have done instead."""
        with pytest.raises(InvalidStateTransition) as exc:
            assert_transition(S.APPLIED, S.HIRED)
        allowed = exc.value.details["allowed"]
        assert allowed and S.SHORTLISTED.value in allowed


class TestFunnel:
    def test_pipeline_order_is_monotonic(self):
        for index, stage in enumerate(PIPELINE_ORDER):
            assert reached_stage(stage, stage)
            for earlier in PIPELINE_ORDER[:index]:
                assert reached_stage(stage, earlier)

    def test_hired_counts_in_every_earlier_stage(self):
        """Funnel maths depends on this: a hire must appear in the interview bucket."""
        for stage in PIPELINE_ORDER:
            assert reached_stage(S.HIRED, stage)

    def test_side_states_map_to_their_implied_stage(self):
        assert reached_stage(S.INTERVIEW_PASSED, S.INTERVIEW)
        assert reached_stage(S.OFFER_ACCEPTED, S.OFFER)
        assert reached_stage(S.OFFER_REJECTED, S.SHORTLISTED)

    def test_applied_has_not_reached_later_stages(self):
        assert not reached_stage(S.APPLIED, S.INTERVIEW)
        assert not reached_stage(S.APPLIED, S.HIRED)


class TestCandidateLabels:
    def test_every_status_has_a_friendly_label(self):
        for status in S:
            label = candidate_label(status)
            assert label and label != status.value

    def test_internal_nuance_is_hidden_from_candidates(self):
        """A candidate must not see that they failed an interview round."""
        assert candidate_label(S.INTERVIEW_FAILED) == "Under review"
        assert candidate_label(S.REJECTED) == "Not progressing"
