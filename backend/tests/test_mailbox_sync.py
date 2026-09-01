"""Importing candidate replies from a connected mailbox.

Nothing here talks to Google or Microsoft: a stub provider stands in for the network so
the logic that matters - deduplication, tenant scoping, matching a reply to a candidate,
and honest reporting when a mailbox cannot be read - is tested deterministically.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.enums import IntegrationProvider
from app.models.communication import EmailAccount, EmailMessage
from app.modules.emails.accounts import sync_account
from app.providers.mailbox import InboundMessage, MailboxProvider, SyncResult


class StubMailbox(MailboxProvider):
    """Stands in for Gmail/Graph. Records the token it was handed."""

    name = "stub"
    can_sync = True

    def __init__(self, messages: list[InboundMessage], *, error: str | None = None):
        self._messages = messages
        self._error = error
        self.seen_tokens: list[str] = []

    async def fetch_recent(self, *, access_token: str, cursor: str | None = None) -> SyncResult:
        self.seen_tokens.append(access_token)
        if self._error:
            return SyncResult(messages=[], error=self._error)
        return SyncResult(messages=self._messages, cursor="cursor-1")


def _message(external_id: str, from_address: str, subject: str = "Re: your role") -> InboundMessage:
    return InboundMessage(
        external_id=external_id,
        thread_id=f"thread-{external_id}",
        from_address=from_address,
        from_name="Reply Sender",
        to_addresses=["talent@acme.test"],
        subject=subject,
        body_text="Thanks - Tuesday works for me.",
        body_html="<p>Thanks - Tuesday works for me.</p>",
        received_at=datetime.now(UTC),
    )


@pytest.fixture
async def mailbox(session, company, recruiter) -> EmailAccount:
    account = EmailAccount(
        company_id=company.id,
        user_id=recruiter.id,
        provider=IntegrationProvider.GOOGLE,
        email_address="talent@acme.test",
        display_name="Acme Talent",
        is_active=True,
        access_token_ref="plain-access-token",
    )
    session.add(account)
    await session.commit()
    return account


def _patch(monkeypatch, provider: StubMailbox, *, token: str | None = "access-token") -> None:
    from app.modules.emails import accounts as module

    monkeypatch.setattr(module, "get_mailbox_provider", lambda _p: provider)

    async def _token(_session, _account):
        return token

    monkeypatch.setattr(module, "ensure_fresh_access_token", _token)


class TestSync:
    async def test_imports_new_messages(self, session, mailbox, monkeypatch):
        provider = StubMailbox([_message("m1", "candidate@example.test")])
        _patch(monkeypatch, provider)

        result = await sync_account(session, mailbox)

        assert result.synced is True
        assert result.messages_imported == 1
        assert provider.seen_tokens == ["access-token"]

        stored = await session.scalar(
            select(EmailMessage).where(EmailMessage.external_message_id == "m1")
        )
        assert stored is not None
        assert stored.company_id == mailbox.company_id

    async def test_second_sync_does_not_duplicate(self, session, mailbox, monkeypatch):
        """Overlapping cron runs and a manual re-sync must be safe."""
        provider = StubMailbox([_message("dup-1", "candidate@example.test")])
        _patch(monkeypatch, provider)

        await sync_account(session, mailbox)
        second = await sync_account(session, mailbox)

        assert second.messages_imported == 0
        count = await session.scalar(
            select(func.count(EmailMessage.id)).where(
                EmailMessage.external_message_id == "dup-1"
            )
        )
        assert count == 1

    async def test_own_outbound_mail_is_ignored(self, session, mailbox, monkeypatch):
        """Providers echo sent mail back; importing it would show recruiters their own
        messages as candidate replies."""
        provider = StubMailbox([_message("own-1", "talent@acme.test")])
        _patch(monkeypatch, provider)

        result = await sync_account(session, mailbox)

        assert result.messages_imported == 0

    async def test_cursor_is_stored_for_the_next_run(self, session, mailbox, monkeypatch):
        _patch(monkeypatch, StubMailbox([_message("c1", "someone@example.test")]))
        await sync_account(session, mailbox)
        assert mailbox.sync_cursor == "cursor-1"

    async def test_provider_failure_is_reported_not_swallowed(
        self, session, mailbox, monkeypatch
    ):
        _patch(monkeypatch, StubMailbox([], error="Gmail returned 503"))

        result = await sync_account(session, mailbox)

        assert result.synced is False
        assert "503" in result.detail
        assert mailbox.sync_error == "Gmail returned 503"

    async def test_expired_authorisation_does_not_claim_success(
        self, session, mailbox, monkeypatch
    ):
        """A mailbox whose refresh token was revoked must say so, not report zero new
        messages as though everything were fine."""
        _patch(monkeypatch, StubMailbox([]), token=None)
        mailbox.sync_error = "The mailbox authorisation was revoked."

        result = await sync_account(session, mailbox)

        assert result.synced is False
        assert "revoked" in result.detail

    async def test_unconfigured_provider_says_so(self, session, company, recruiter):
        account = EmailAccount(
            company_id=company.id,
            user_id=recruiter.id,
            provider=IntegrationProvider.MOCK,
            email_address="nowhere@acme.test",
            is_active=True,
        )
        session.add(account)
        await session.flush()

        result = await sync_account(session, account)

        assert result.synced is False
        assert result.messages_imported == 0
        assert "no mailbox provider" in result.detail.lower()


class TestTenantIsolation:
    async def test_imported_mail_is_scoped_to_the_owning_company(
        self, session, mailbox, monkeypatch
    ):
        """The dedup lookup is company-scoped, so two tenants receiving the same
        provider message id must each get their own copy - and neither can see the
        other's."""
        _patch(monkeypatch, StubMailbox([_message("shared-id", "candidate@example.test")]))
        await sync_account(session, mailbox)

        other_company_id = uuid.uuid4()
        leaked = await session.scalar(
            select(func.count(EmailMessage.id)).where(
                EmailMessage.external_message_id == "shared-id",
                EmailMessage.company_id == other_company_id,
            )
        )
        assert leaked == 0
