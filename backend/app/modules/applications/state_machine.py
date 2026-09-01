"""Application status transitions.

Centralising this means every path that moves an application - a recruiter dragging a
Kanban card, a bulk action, a workflow, the offer service - obeys the same rules, and
those rules are unit-testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import (
    APPLICATION_TRANSITIONS,
    TERMINAL_APPLICATION_STATUSES,
    ApplicationStatus,
)
from app.core.exceptions import InvalidStateTransition

#: Pipeline order used for Kanban columns and funnel analytics. Statuses outside this
#: list (ON_HOLD, WITHDRAWN, ...) are side states, shown separately.
PIPELINE_ORDER: tuple[ApplicationStatus, ...] = (
    ApplicationStatus.APPLIED,
    ApplicationStatus.UNDER_REVIEW,
    ApplicationStatus.SCREENING,
    ApplicationStatus.SHORTLISTED,
    ApplicationStatus.ASSESSMENT,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
    ApplicationStatus.HIRED,
)

#: What the candidate is shown, so internal nuance stays internal.
CANDIDATE_FACING_STATUS: dict[ApplicationStatus, str] = {
    ApplicationStatus.APPLIED: "Application received",
    ApplicationStatus.UNDER_REVIEW: "Under review",
    ApplicationStatus.SCREENING: "In screening",
    ApplicationStatus.SHORTLISTED: "Shortlisted",
    ApplicationStatus.ASSESSMENT: "Assessment stage",
    ApplicationStatus.INTERVIEW: "Interview stage",
    ApplicationStatus.INTERVIEW_PASSED: "Interview stage",
    ApplicationStatus.INTERVIEW_FAILED: "Under review",
    ApplicationStatus.OFFER: "Offer extended",
    ApplicationStatus.OFFER_ACCEPTED: "Offer accepted",
    ApplicationStatus.OFFER_REJECTED: "Offer declined",
    ApplicationStatus.HIRED: "Hired",
    ApplicationStatus.REJECTED: "Not progressing",
    ApplicationStatus.ON_HOLD: "On hold",
    ApplicationStatus.WITHDRAWN: "Withdrawn",
}


@dataclass(frozen=True, slots=True)
class TransitionEffect:
    """Side effects a status change implies, so callers apply them consistently."""

    stamps_shortlisted: bool = False
    stamps_interviewed: bool = False
    stamps_offered: bool = False
    stamps_hired: bool = False
    notifies_candidate: bool = False
    #: The default email template key, when the caller has not chosen one.
    email_template: str | None = None


_EFFECTS: dict[ApplicationStatus, TransitionEffect] = {
    ApplicationStatus.SHORTLISTED: TransitionEffect(
        stamps_shortlisted=True, notifies_candidate=True, email_template="SHORTLISTED"
    ),
    ApplicationStatus.SCREENING: TransitionEffect(
        notifies_candidate=True, email_template="SCREENING_INVITATION"
    ),
    ApplicationStatus.INTERVIEW: TransitionEffect(stamps_interviewed=True),
    ApplicationStatus.INTERVIEW_PASSED: TransitionEffect(stamps_interviewed=True),
    ApplicationStatus.OFFER: TransitionEffect(
        stamps_offered=True, notifies_candidate=True, email_template="OFFER"
    ),
    ApplicationStatus.HIRED: TransitionEffect(stamps_hired=True),
    ApplicationStatus.REJECTED: TransitionEffect(
        notifies_candidate=True, email_template="REJECTED"
    ),
    ApplicationStatus.ON_HOLD: TransitionEffect(
        notifies_candidate=True, email_template="ON_HOLD"
    ),
}


def can_transition(current: ApplicationStatus, target: ApplicationStatus) -> bool:
    if current == target:
        return False
    return target in APPLICATION_TRANSITIONS.get(current, frozenset())


def allowed_transitions(current: ApplicationStatus) -> list[ApplicationStatus]:
    return sorted(APPLICATION_TRANSITIONS.get(current, frozenset()), key=lambda s: s.value)


def assert_transition(current: ApplicationStatus, target: ApplicationStatus) -> None:
    """Raise a descriptive error if this move is not allowed."""
    if current == target:
        raise InvalidStateTransition(
            f"The application is already {target.value.replace('_', ' ').lower()}",
            details={"current_status": current.value},
        )
    if current in TERMINAL_APPLICATION_STATUSES:
        raise InvalidStateTransition(
            f"This application is {current.value.replace('_', ' ').lower()} and can no "
            "longer be moved",
            details={"current_status": current.value, "allowed": []},
        )
    if not can_transition(current, target):
        allowed = [s.value for s in allowed_transitions(current)]
        raise InvalidStateTransition(
            f"Cannot move from {current.value} to {target.value}",
            details={"current_status": current.value, "allowed": allowed},
        )


def effects_for(status: ApplicationStatus) -> TransitionEffect:
    return _EFFECTS.get(status, TransitionEffect())


def is_terminal(status: ApplicationStatus) -> bool:
    return status in TERMINAL_APPLICATION_STATUSES


def pipeline_index(status: ApplicationStatus) -> int:
    """Position in the funnel, or -1 for side states."""
    try:
        return PIPELINE_ORDER.index(status)
    except ValueError:
        return -1


def reached_stage(status: ApplicationStatus, stage: ApplicationStatus) -> bool:
    """Whether an application in ``status`` has got at least as far as ``stage``.

    Used by funnel analytics: a HIRED application must count in the "interviewed" bucket
    even though its current status is not INTERVIEW.
    """
    current_index = pipeline_index(status)
    stage_index = pipeline_index(stage)
    if stage_index < 0:
        return status == stage
    if current_index >= 0:
        return current_index >= stage_index
    # Side states are judged by the furthest point they imply.
    implied = {
        ApplicationStatus.INTERVIEW_PASSED: ApplicationStatus.INTERVIEW,
        ApplicationStatus.INTERVIEW_FAILED: ApplicationStatus.INTERVIEW,
        ApplicationStatus.OFFER_ACCEPTED: ApplicationStatus.OFFER,
        ApplicationStatus.OFFER_REJECTED: ApplicationStatus.OFFER,
    }.get(status)
    return pipeline_index(implied) >= stage_index if implied else False


def candidate_label(status: ApplicationStatus) -> str:
    return CANDIDATE_FACING_STATUS.get(status, status.value.replace("_", " ").title())
