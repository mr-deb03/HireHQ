"""Server-sent events for live dashboard updates.

SSE rather than WebSockets: the traffic is entirely server-to-client (a new application
arrived, a score finished), it survives proxies that mangle upgrades, and browsers
reconnect on their own. A WebSocket would add a second protocol for no benefit here.

Delivery is best-effort and per-process. Clients treat an event as a hint to refetch, not
as the source of truth, so a missed event during a reconnect costs a slightly stale
number rather than a wrong one.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.core.logging import get_logger
from app.dependencies.auth import CurrentUser
from app.services.events import DomainEvent

logger = get_logger(__name__)

router = APIRouter(prefix="/realtime", tags=["Health"])

#: Dropped once a subscriber is this far behind - a stalled tab must not grow unbounded.
QUEUE_LIMIT = 64
HEARTBEAT_SECONDS = 25


@dataclass(slots=True, eq=False)
class Subscriber:
    """One live connection.

    ``eq=False`` keeps identity-based equality and hashing: two tabs opened by the same
    user are distinct connections, and subscribers are held in a set.
    """

    user_id: uuid.UUID
    company_id: uuid.UUID | None
    queue: asyncio.Queue


class RealtimeHub:
    """Fan-out of domain events to connected browsers, scoped by tenant."""

    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[Subscriber]] = defaultdict(set)

    def subscribe(self, user_id: uuid.UUID, company_id: uuid.UUID | None) -> Subscriber:
        subscriber = Subscriber(
            user_id=user_id, company_id=company_id, queue=asyncio.Queue(maxsize=QUEUE_LIMIT)
        )
        # Keyed by company so a broadcast never has to scan every connection - and so
        # there is no code path that could deliver one tenant's event to another.
        key = company_id or user_id
        self._subscribers[key].add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        key = subscriber.company_id or subscriber.user_id
        self._subscribers[key].discard(subscriber)
        if not self._subscribers[key]:
            self._subscribers.pop(key, None)

    def publish(self, company_id: uuid.UUID | None, payload: dict[str, Any]) -> int:
        """Queue a payload for every subscriber of one company. Never blocks."""
        if company_id is None:
            return 0
        delivered = 0
        for subscriber in list(self._subscribers.get(company_id, ())):
            try:
                subscriber.queue.put_nowait(payload)
                delivered += 1
            except asyncio.QueueFull:
                # The client is not draining; drop the event rather than stall the
                # publisher. Their next poll will reconcile.
                logger.debug("realtime_subscriber_lagging", user_id=str(subscriber.user_id))
        return delivered

    @property
    def connection_count(self) -> int:
        return sum(len(subs) for subs in self._subscribers.values())


hub = RealtimeHub()


#: Events worth waking a dashboard for, and the label the UI shows.
_BROADCAST: dict[str, str] = {
    "APPLICATION_CREATED": "New application received",
    "ATS_SCORE_GENERATED": "ATS analysis completed",
    "APPLICATION_STATUS_CHANGED": "Application moved",
    "INTERVIEW_SCHEDULED": "Interview scheduled",
    "FEEDBACK_SUBMITTED": "Interview feedback submitted",
    "OFFER_ACCEPTED": "Offer accepted",
    "OFFER_REJECTED": "Offer declined",
    "EMAIL_RECEIVED": "New candidate reply",
}


async def broadcast_domain_event(event: DomainEvent) -> None:
    """Event-bus subscriber that mirrors selected domain events to connected browsers."""
    label = _BROADCAST.get(event.name)
    if label is None:
        return
    hub.publish(
        event.company_id,
        {
            "type": event.name,
            "label": label,
            "entity_type": event.entity_type,
            "entity_id": str(event.entity_id),
            "at": datetime.now(UTC).isoformat(),
            # Only display-safe fields; never scores or personal detail beyond a name.
            "job_id": event.payload.get("job_id"),
            "candidate_name": event.payload.get("candidate_name"),
        },
    )


@router.get(
    "/stream",
    summary="Live update stream (SSE)",
    description=(
        "Server-sent events for the signed-in user's company: new applications, "
        "completed ATS analyses, pipeline moves, interviews, feedback and offers.\n\n"
        "Each event is a hint to refetch, not authoritative data. Browsers reconnect "
        "automatically; a heartbeat every 25s keeps proxies from closing the connection."
    ),
)
async def stream(
    request: Request,
    principal: CurrentUser,
    since: Annotated[str | None, Query(description="Ignored; reserved for replay")] = None,
) -> EventSourceResponse:
    subscriber = hub.subscribe(principal.id, principal.company_id)

    async def publisher():
        try:
            yield {
                "event": "connected",
                "data": json.dumps(
                    {
                        "company_id": str(principal.company_id) if principal.company_id else None,
                        "at": datetime.now(UTC).isoformat(),
                    }
                ),
            }
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(
                        subscriber.queue.get(), timeout=HEARTBEAT_SECONDS
                    )
                except TimeoutError:
                    # A comment-only heartbeat: keeps the connection warm without the
                    # client having to handle a synthetic event type.
                    yield {"event": "ping", "data": "{}"}
                    continue
                yield {"event": "update", "data": json.dumps(payload)}
        finally:
            hub.unsubscribe(subscriber)

    return EventSourceResponse(publisher())


@router.get(
    "/status",
    summary="Realtime connection status",
    description="How many live streams this process is serving. Useful for diagnostics.",
)
async def realtime_status(principal: CurrentUser) -> dict:
    from app.core.responses import ok

    return ok(
        {
            "connections": hub.connection_count,
            "transport": "sse",
            "note": (
                "Connections are per-process. Behind multiple workers each process "
                "serves its own subscribers, which is fine because events are hints to "
                "refetch rather than authoritative state."
            ),
        }
    )
