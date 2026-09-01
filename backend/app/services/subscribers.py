"""Wiring between domain events and the systems that react to them.

Registered once at startup. Each subscriber opens its own session because it runs
*after* the originating request's transaction has committed - reusing that session would
mean writing into a closed unit of work.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.services.events import DomainEvent, Events, event_bus

logger = get_logger(__name__)

_registered = False


async def _run_workflows(event: DomainEvent) -> None:
    """Hand the event to the workflow engine if it maps to a trigger."""
    if event.workflow_trigger is None or event.company_id is None:
        return
    from app.db.session import session_scope
    from app.modules.workflows.engine import WorkflowEngine

    async with session_scope() as session:
        engine = WorkflowEngine(session, event.company_id)
        await engine.handle_event(event)


async def _dispatch_notifications(event: DomainEvent) -> None:
    """Raise in-app notifications for the people who need to act on this event."""
    from app.db.session import session_scope
    from app.modules.notifications.service import NotificationService

    async with session_scope() as session:
        service = NotificationService(session)
        await service.handle_event(event)


def register_subscribers() -> None:
    global _registered
    if _registered:
        return

    workflow_events = [
        Events.APPLICATION_CREATED,
        Events.ATS_SCORE_GENERATED,
        Events.APPLICATION_STATUS_CHANGED,
        Events.INTERVIEW_SCHEDULED,
        Events.INTERVIEW_COMPLETED,
        Events.FEEDBACK_SUBMITTED,
        Events.OFFER_ACCEPTED,
        Events.ASSESSMENT_SUBMITTED,
    ]
    for name in workflow_events:
        event_bus.subscribe(name, _run_workflows)

    event_bus.subscribe_all(_dispatch_notifications)

    # Mirrors selected events to connected browsers over SSE. Registered last so a slow
    # or disconnected client can never delay a workflow or a notification.
    from app.api.v1.realtime import broadcast_domain_event

    event_bus.subscribe_all(broadcast_domain_event)

    _registered = True
    logger.info("event_subscribers_registered", workflow_events=len(workflow_events))


def reset_subscribers() -> None:
    """Used by tests that need a clean bus."""
    global _registered
    event_bus.clear()
    _registered = False
