"""Live-update fan-out.

The security property under test is that the hub is keyed by company, so there is no code
path - not even a bug in a caller - that can hand one tenant's event to another tenant's
browser (§46).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.api.v1.realtime import QUEUE_LIMIT, RealtimeHub, broadcast_domain_event, hub
from app.services.events import DomainEvent, Events


@pytest.fixture
def fresh_hub() -> RealtimeHub:
    return RealtimeHub()


class TestFanOut:
    def test_every_subscriber_of_a_company_receives_the_event(self, fresh_hub):
        company = uuid.uuid4()
        a = fresh_hub.subscribe(uuid.uuid4(), company)
        b = fresh_hub.subscribe(uuid.uuid4(), company)

        assert fresh_hub.publish(company, {"type": "PING"}) == 2
        assert a.queue.get_nowait() == {"type": "PING"}
        assert b.queue.get_nowait() == {"type": "PING"}

    def test_events_never_cross_tenants(self, fresh_hub):
        acme = uuid.uuid4()
        globex = uuid.uuid4()
        acme_sub = fresh_hub.subscribe(uuid.uuid4(), acme)
        globex_sub = fresh_hub.subscribe(uuid.uuid4(), globex)

        fresh_hub.publish(acme, {"type": "APPLICATION_CREATED"})

        assert acme_sub.queue.qsize() == 1
        assert globex_sub.queue.empty()

    def test_publishing_without_a_company_reaches_nobody(self, fresh_hub):
        """A domain event that lost its tenant must be dropped, not broadcast widely."""
        fresh_hub.subscribe(uuid.uuid4(), uuid.uuid4())
        assert fresh_hub.publish(None, {"type": "APPLICATION_CREATED"}) == 0

    def test_unsubscribe_removes_the_connection(self, fresh_hub):
        company = uuid.uuid4()
        subscriber = fresh_hub.subscribe(uuid.uuid4(), company)
        assert fresh_hub.connection_count == 1

        fresh_hub.unsubscribe(subscriber)

        assert fresh_hub.connection_count == 0
        assert fresh_hub.publish(company, {"type": "PING"}) == 0

    def test_a_stalled_client_is_dropped_not_allowed_to_grow(self, fresh_hub):
        """A tab that stopped reading must not consume unbounded memory, and must not
        block the request that published the event."""
        company = uuid.uuid4()
        subscriber = fresh_hub.subscribe(uuid.uuid4(), company)

        for _ in range(QUEUE_LIMIT + 25):
            fresh_hub.publish(company, {"type": "PING"})

        assert subscriber.queue.qsize() == QUEUE_LIMIT


class TestDomainEventBridge:
    async def test_only_display_safe_fields_are_broadcast(self):
        """The stream reaches a browser before any permission check on the payload, so it
        carries identifiers and a name - never scores, salaries or resume content."""
        company = uuid.uuid4()
        subscriber = hub.subscribe(uuid.uuid4(), company)
        try:
            await broadcast_domain_event(
                DomainEvent(
                    name=Events.APPLICATION_CREATED,
                    company_id=company,
                    entity_type="Application",
                    entity_id=uuid.uuid4(),
                    payload={
                        "job_id": "job-1",
                        "candidate_name": "Nina Analyst",
                        "ats_score": 93.27,
                        "expected_salary": 2500000,
                        "resume_text": "confidential",
                    },
                )
            )
            payload = subscriber.queue.get_nowait()
        finally:
            hub.unsubscribe(subscriber)

        assert payload["label"] == "New application received"
        assert payload["candidate_name"] == "Nina Analyst"
        assert set(payload) == {
            "type", "label", "entity_type", "entity_id", "at", "job_id", "candidate_name",
        }
        assert "93.27" not in str(payload)
        assert "confidential" not in str(payload)

    async def test_unlisted_events_are_not_broadcast(self):
        """Only events a dashboard should react to go out; the rest stay internal."""
        company = uuid.uuid4()
        subscriber = hub.subscribe(uuid.uuid4(), company)
        try:
            await broadcast_domain_event(
                DomainEvent(
                    name="AUDIT_LOG_WRITTEN",
                    company_id=company,
                    entity_type="AuditLog",
                    entity_id=uuid.uuid4(),
                    payload={},
                )
            )
            assert subscriber.queue.empty()
        finally:
            hub.unsubscribe(subscriber)

    async def test_a_slow_subscriber_cannot_block_the_publisher(self):
        """Publishing is synchronous inside an event handler, so it must never await a
        client - a hung browser would otherwise stall a workflow."""
        company = uuid.uuid4()
        local = RealtimeHub()
        local.subscribe(uuid.uuid4(), company)

        async def flood():
            for _ in range(QUEUE_LIMIT * 3):
                local.publish(company, {"type": "PING"})

        await asyncio.wait_for(flood(), timeout=2)


class TestStreamEndpoint:
    async def test_requires_authentication(self, client):
        response = await client.get("/api/v1/realtime/status")
        assert response.status_code == 401

    async def test_status_reports_the_transport(self, client, recruiter_token):
        from tests.conftest import auth

        response = await client.get("/api/v1/realtime/status", headers=auth(recruiter_token))

        assert response.status_code == 200
        assert response.json()["data"]["transport"] == "sse"
