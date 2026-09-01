"""Domain event bus.

Business services publish facts ("an application was created", "an ATS score was
generated"). Subscribers - the workflow engine, the notification service, the real-time
dispatcher - react to them. This keeps the pipeline service from importing the workflow
engine, which would otherwise create a cycle and make either impossible to test alone.

Events are dispatched *after commit*: a subscriber must never act on a transaction that
later rolls back (an email about a shortlisting that never happened cannot be recalled).
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.enums import WorkflowTrigger
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class DomainEvent:
    name: str
    company_id: uuid.UUID | None
    entity_type: str
    entity_id: uuid.UUID
    payload: dict[str, Any] = field(default_factory=dict)
    actor_id: uuid.UUID | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def workflow_trigger(self) -> WorkflowTrigger | None:
        try:
            return WorkflowTrigger(self.name)
        except ValueError:
            return None

    def idempotency_key(self, workflow_id: uuid.UUID) -> str:
        """Stable key so a redelivered event cannot run the same workflow twice.

        Includes a discriminator from the payload where one exists (e.g. the new status),
        so a status change to SHORTLISTED and a later one to INTERVIEW are distinct
        occurrences of the same trigger on the same entity.
        """
        discriminator = (
            self.payload.get("new_status")
            or self.payload.get("score_id")
            or self.payload.get("interview_id")
            or self.payload.get("feedback_id")
            or ""
        )
        return f"{workflow_id}:{self.entity_id}:{self.name}:{discriminator}"


Subscriber = Callable[[DomainEvent], Awaitable[None]]


class EventBus:
    """In-process publish/subscribe with after-commit delivery."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)
        self._wildcard: list[Subscriber] = []

    def subscribe(self, event_name: str, handler: Subscriber) -> None:
        self._subscribers[event_name].append(handler)

    def subscribe_all(self, handler: Subscriber) -> None:
        self._wildcard.append(handler)

    def clear(self) -> None:
        self._subscribers.clear()
        self._wildcard.clear()

    async def publish(self, event: DomainEvent) -> None:
        """Deliver to every subscriber.

        Handlers run sequentially and their failures are contained: a broken workflow
        must not prevent a notification, and neither must fail the request that already
        committed the underlying change.
        """
        handlers = [*self._subscribers.get(event.name, []), *self._wildcard]
        if not handlers:
            return
        logger.debug("event_published", event_name=event.name, handlers=len(handlers))
        for handler in handlers:
            try:
                await handler(event)
            except Exception as exc:
                logger.error(
                    "event_handler_failed",
                    event_name=event.name,
                    handler=getattr(handler, "__name__", repr(handler)),
                    error=str(exc),
                    exc_info=True,
                )


event_bus = EventBus()


class EventCollector:
    """Buffers events raised during a unit of work, for release after commit.

    Services call ``collect``; the request lifecycle (or the worker) calls ``flush`` once
    the transaction has committed.
    """

    def __init__(self) -> None:
        self._pending: list[DomainEvent] = []

    def collect(self, event: DomainEvent) -> None:
        self._pending.append(event)

    def discard(self) -> None:
        self._pending.clear()

    @property
    def pending(self) -> list[DomainEvent]:
        return list(self._pending)

    async def flush(self) -> None:
        pending, self._pending = self._pending, []
        for event in pending:
            await event_bus.publish(event)

    def flush_in_background(self) -> asyncio.Task | None:
        """Fire-and-forget delivery for request paths that must not wait on side effects."""
        if not self._pending:
            return None
        pending, self._pending = self._pending, []

        async def _run() -> None:
            for event in pending:
                await event_bus.publish(event)

        return asyncio.create_task(_run())


# ---------------------------------------------------------------- event names
class Events:
    """Canonical event names.

    Names matching a ``WorkflowTrigger`` member drive the workflow engine directly; the
    rest are internal-only.
    """

    APPLICATION_CREATED = "APPLICATION_CREATED"
    APPLICATION_STATUS_CHANGED = "APPLICATION_STATUS_CHANGED"
    ATS_SCORE_GENERATED = "ATS_SCORE_GENERATED"
    RESUME_PARSED = "RESUME_PARSED"
    RESUME_FAILED = "RESUME_FAILED"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    INTERVIEW_RESCHEDULED = "INTERVIEW_RESCHEDULED"
    INTERVIEW_CANCELLED = "INTERVIEW_CANCELLED"
    INTERVIEW_COMPLETED = "INTERVIEW_COMPLETED"
    FEEDBACK_SUBMITTED = "FEEDBACK_SUBMITTED"
    ASSESSMENT_SUBMITTED = "ASSESSMENT_SUBMITTED"
    OFFER_SENT = "OFFER_SENT"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    OFFER_REJECTED = "OFFER_REJECTED"
    CANDIDATE_HIRED = "CANDIDATE_HIRED"
    EMAIL_RECEIVED = "EMAIL_RECEIVED"
    JOB_PUBLISHED = "JOB_PUBLISHED"
