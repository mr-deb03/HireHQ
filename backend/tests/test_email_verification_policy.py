"""Email verification is only enforced when the link can actually be delivered.

Requiring a verified address is a real control, but it depends on something outside the
application: an email provider that transmits. With the console provider the verification
link is generated, recorded, and never sent - so nobody can ever satisfy the requirement.
Enforcing it there does not protect the system, it locks every user out of it, starting
with the first administrator to register.

So the requirement follows the provider's actual capability, and ``REQUIRE_EMAIL_
VERIFICATION`` overrides that in either direction for anyone who wants to decide
explicitly.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import EmailDeliveryStatus, UserStatus
from app.core.security import hash_password
from app.models.user import User
from app.providers.email import (
    DeliveryResult,
    SMTPEmailProvider,
    email_verification_required,
    reset_email_provider,
)

PASSWORD = "VerifyPolicy!2024"


@pytest.fixture(autouse=True)
def _restore_provider(monkeypatch):
    """Every test here changes provider configuration; none may leak into the next."""
    yield
    reset_email_provider()


def configure(monkeypatch, *, provider: str, host: str | None = None, require=None):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", provider)
    monkeypatch.setattr(settings, "SMTP_HOST", host)
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", require)

    # Selecting SMTP makes the provider genuinely transmitting, which is the point - but
    # these tests are about the verification policy, not about delivery, and nothing here
    # should open a socket to a real mail server. Stub the transmission and keep
    # ``transmits = True``, so the policy still sees a provider that can deliver.
    async def _no_network(self, message):
        return DeliveryResult(status=EmailDeliveryStatus.SENT, transport="smtp-stub")

    monkeypatch.setattr(SMTPEmailProvider, "send", _no_network)
    reset_email_provider()


class TestPolicy:
    def test_not_required_when_the_provider_cannot_transmit(self, monkeypatch):
        """The case that locked the first administrator out of production."""
        configure(monkeypatch, provider="console")
        assert email_verification_required() is False

    def test_required_when_smtp_can_deliver(self, monkeypatch):
        configure(monkeypatch, provider="smtp", host="smtp.example.com")
        assert email_verification_required() is True

    def test_smtp_without_a_host_does_not_count_as_deliverable(self, monkeypatch):
        """The provider downgrades itself to console, and the policy must follow the
        provider that is actually in use - not the one that was asked for."""
        configure(monkeypatch, provider="smtp", host=None)
        assert email_verification_required() is False

    def test_explicit_true_overrides_a_silent_provider(self, monkeypatch):
        configure(monkeypatch, provider="console", require=True)
        assert email_verification_required() is True

    def test_explicit_false_overrides_a_working_provider(self, monkeypatch):
        configure(monkeypatch, provider="smtp", host="smtp.example.com", require=False)
        assert email_verification_required() is False


async def _unverified_user(session: AsyncSession) -> User:
    user = User(
        email=f"pending-{uuid.uuid4().hex[:8]}@hirehq.test",
        hashed_password=hash_password(PASSWORD),
        first_name="Pending",
        last_name="Person",
        status=UserStatus.PENDING_VERIFICATION,
    )
    session.add(user)
    await session.commit()
    return user


class TestSignIn:
    async def test_unverified_account_can_sign_in_when_email_cannot_be_delivered(
        self, client: httpx.AsyncClient, session: AsyncSession, monkeypatch
    ):
        configure(monkeypatch, provider="console")
        user = await _unverified_user(session)

        response = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
        )

        assert response.status_code == 200, response.text
        assert response.json()["data"]["tokens"]["access_token"]

    async def test_signing_in_clears_a_verification_wait_that_will_never_end(
        self, client: httpx.AsyncClient, session: AsyncSession, monkeypatch
    ):
        """Accounts created before the policy changed must heal themselves, otherwise
        every admin view shows them as waiting on a candidate who has nothing to do."""
        configure(monkeypatch, provider="console")
        user = await _unverified_user(session)
        user_id, email = user.id, user.email

        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text

        session.expire_all()
        refreshed = await session.scalar(select(User).where(User.id == user_id))
        assert refreshed.status == UserStatus.ACTIVE

    async def test_unverified_account_is_refused_when_email_works(
        self, client: httpx.AsyncClient, session: AsyncSession, monkeypatch
    ):
        """The control still exists - this is a policy, not a removal."""
        configure(monkeypatch, provider="smtp", host="smtp.example.com")
        user = await _unverified_user(session)

        response = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"

    async def test_a_wrong_password_is_still_refused(
        self, client: httpx.AsyncClient, session: AsyncSession, monkeypatch
    ):
        """Relaxing verification must not relax authentication."""
        configure(monkeypatch, provider="console")
        user = await _unverified_user(session)

        response = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "WrongPassword!1"}
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"

    async def test_a_suspended_account_is_still_refused(
        self, client: httpx.AsyncClient, session: AsyncSession, monkeypatch
    ):
        configure(monkeypatch, provider="console")
        user = await _unverified_user(session)
        user.status = UserStatus.SUSPENDED
        await session.commit()

        response = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "ACCOUNT_INACTIVE"


class TestRegistration:
    async def test_new_accounts_are_active_when_nothing_will_verify_them(
        self, client: httpx.AsyncClient, session: AsyncSession, monkeypatch
    ):
        configure(monkeypatch, provider="console")
        email = f"newcandidate-{uuid.uuid4().hex[:8]}@hirehq.test"

        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "first_name": "New",
                "last_name": "Candidate",
                "accept_terms": True,
            },
        )
        assert response.status_code in (200, 201), response.text

        created = await session.scalar(select(User).where(User.email == email))
        assert created.status == UserStatus.ACTIVE

        # The response must not send them hunting for an email that was never required.
        message = response.json()["message"]
        assert "sign in now" in message.lower(), message
        assert "administrator" not in message.lower(), message

    async def test_new_accounts_await_verification_when_email_works(
        self, client: httpx.AsyncClient, session: AsyncSession, monkeypatch
    ):
        configure(monkeypatch, provider="smtp", host="smtp.example.com")
        email = f"newcandidate-{uuid.uuid4().hex[:8]}@hirehq.test"

        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "first_name": "New",
                "last_name": "Candidate",
                "accept_terms": True,
            },
        )
        assert response.status_code in (200, 201), response.text

        created = await session.scalar(select(User).where(User.email == email))
        assert created.status == UserStatus.PENDING_VERIFICATION
