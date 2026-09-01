"""Signed OAuth ``state`` tokens.

The ``state`` parameter is the only thing standing between an OAuth callback and CSRF:
without it, an attacker can trick a signed-in user into completing *their* authorisation
flow, binding the attacker's mailbox or calendar to the victim's account.

Rather than persisting pending flows in a table, the state is a short-lived signed token
carrying the user and company it belongs to. That keeps the callback stateless (no
cleanup job for abandoned flows) while still being unforgeable and single-purpose.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.exceptions import InvalidToken

#: OAuth consent rarely takes more than a couple of minutes; a short window limits how
#: long a leaked state value is useful.
STATE_TTL_MINUTES = 15


@dataclass(slots=True)
class OAuthState:
    user_id: uuid.UUID
    company_id: uuid.UUID
    provider: str
    #: What the flow is for - ``calendar`` or ``email``. A state minted for one must not
    #: be replayable against the other.
    purpose: str
    redirect_to: str | None = None


def _sign(payload: bytes) -> str:
    digest = hmac.new(settings.JWT_SECRET.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def encode_state(state: OAuthState) -> str:
    """Mint a signed state token."""
    body = {
        "u": str(state.user_id),
        "c": str(state.company_id),
        "p": state.provider,
        "k": state.purpose,
        "r": state.redirect_to,
        "exp": int((datetime.now(UTC) + timedelta(minutes=STATE_TTL_MINUTES)).timestamp()),
        # A nonce so two flows started in the same second produce different tokens.
        "n": uuid.uuid4().hex[:12],
    }
    payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"{_b64encode(payload)}.{_sign(payload)}"


def decode_state(token: str, *, expected_purpose: str) -> OAuthState:
    """Verify and decode a state token, or raise ``InvalidToken``."""
    try:
        encoded, signature = token.split(".", 1)
        payload = _b64decode(encoded)
    except (ValueError, TypeError) as exc:
        raise InvalidToken("The OAuth state parameter is malformed") from exc

    if not hmac.compare_digest(_sign(payload), signature):
        raise InvalidToken("The OAuth state parameter failed verification")

    try:
        body = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise InvalidToken("The OAuth state parameter is malformed") from exc

    if body.get("exp", 0) < int(datetime.now(UTC).timestamp()):
        raise InvalidToken("This authorisation flow expired. Please start again.")

    if body.get("k") != expected_purpose:
        # A calendar state must never complete an email connection, or vice versa.
        raise InvalidToken("This authorisation link was issued for a different purpose")

    return OAuthState(
        user_id=uuid.UUID(body["u"]),
        company_id=uuid.UUID(body["c"]),
        provider=body["p"],
        purpose=body["k"],
        redirect_to=body.get("r"),
    )
