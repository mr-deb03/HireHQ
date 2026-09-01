"""OAuth state signing and token-at-rest encryption.

These two pieces carry the whole security weight of the calendar and mailbox
integrations: the state token is what proves a callback belongs to the user who started
the flow, and the vault is what stops a database dump from yielding usable Google
credentials. Both are tested for the failure cases, not just the happy path.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import ExternalServiceError, InvalidToken
from app.services.oauth_state import OAuthState, decode_state, encode_state
from app.services.token_vault import decrypt, encrypt


def _state(**overrides) -> OAuthState:
    defaults = {
        "user_id": uuid.uuid4(),
        "company_id": uuid.uuid4(),
        "provider": "google",
        "purpose": "calendar",
    }
    return OAuthState(**{**defaults, **overrides})


class TestOAuthState:
    def test_roundtrip_preserves_identity(self):
        original = _state()
        decoded = decode_state(encode_state(original), expected_purpose="calendar")

        assert decoded.user_id == original.user_id
        assert decoded.company_id == original.company_id
        assert decoded.provider == "google"

    def test_tampered_payload_is_rejected(self):
        """The signature must cover the payload, not merely accompany it."""
        token = encode_state(_state())
        payload, signature = token.rsplit(".", 1)
        forged = payload[:-4] + ("AAAA" if not payload.endswith("AAAA") else "BBBB")

        with pytest.raises(InvalidToken):
            decode_state(f"{forged}.{signature}", expected_purpose="calendar")

    def test_signature_from_another_token_is_rejected(self):
        a = encode_state(_state())
        b = encode_state(_state())
        payload_a = a.rsplit(".", 1)[0]
        signature_b = b.rsplit(".", 1)[1]

        with pytest.raises(InvalidToken):
            decode_state(f"{payload_a}.{signature_b}", expected_purpose="calendar")

    def test_purpose_is_enforced(self):
        """A calendar consent must not be replayable to connect a mailbox.

        Both flows use the same Google app and the same signing key, so without a
        purpose check a user could be walked through a calendar authorisation and have
        the resulting code redeemed against the inbox endpoint instead.
        """
        calendar_state = encode_state(_state(purpose="calendar"))
        email_state = encode_state(_state(purpose="email"))

        with pytest.raises(InvalidToken):
            decode_state(calendar_state, expected_purpose="email")
        with pytest.raises(InvalidToken):
            decode_state(email_state, expected_purpose="calendar")

        # ...while each still works for the flow it was minted for.
        assert decode_state(calendar_state, expected_purpose="calendar").purpose == "calendar"
        assert decode_state(email_state, expected_purpose="email").purpose == "email"

    def test_malformed_tokens_fail_closed(self):
        for bad in ("", "no-dot", "a.b.c.d.e", "....", "!!!.???"):
            with pytest.raises(InvalidToken):
                decode_state(bad, expected_purpose="calendar")

    def test_expired_state_is_rejected(self, monkeypatch):
        from app.services import oauth_state as module

        # Mint with a negative lifetime rather than sleeping for the real TTL.
        monkeypatch.setattr(module, "STATE_TTL_MINUTES", -1)
        token = encode_state(_state())
        monkeypatch.undo()

        with pytest.raises(InvalidToken):
            decode_state(token, expected_purpose="calendar")

    def test_redirect_target_survives(self):
        token = encode_state(_state(redirect_to="/recruiter/calendar?tab=connected"))
        assert decode_state(token, expected_purpose="calendar").redirect_to == (
            "/recruiter/calendar?tab=connected"
        )


class TestTokenVault:
    def test_roundtrip(self):
        secret = "ya29.a0AfH6SM" + "x" * 120
        assert decrypt(encrypt(secret)) == secret

    def test_ciphertext_does_not_contain_the_plaintext(self):
        secret = "refresh-token-value-12345"
        assert secret not in encrypt(secret)

    def test_same_plaintext_encrypts_differently(self):
        """A fresh nonce per encryption, so equal tokens are not visibly equal at rest."""
        assert encrypt("same-value") != encrypt("same-value")

    def test_tampered_ciphertext_is_rejected(self):
        """Authenticated encryption: a flipped byte must fail, not decrypt to garbage."""
        token = encrypt("sensitive")
        prefix, body = token.rsplit(".", 1)
        mutated = body[:-2] + ("AA" if not body.endswith("AA") else "BB")

        with pytest.raises(ExternalServiceError):
            decrypt(f"{prefix}.{mutated}")

    def test_wrong_key_cannot_decrypt(self, monkeypatch):
        """Rotating JWT_SECRET must invalidate stored tokens rather than silently
        yielding wrong bytes - the operator has to reconnect the integration."""
        from app.services import token_vault

        token = encrypt("provider-refresh-token")
        monkeypatch.setattr(
            token_vault.settings, "JWT_SECRET", "a-completely-different-secret-value-0987654321"
        )
        token_vault.reset()
        try:
            with pytest.raises(ExternalServiceError):
                decrypt(token)
        finally:
            monkeypatch.undo()
            token_vault.reset()

    def test_none_and_empty_roundtrip_safely(self):
        assert encrypt(None) is None
        assert decrypt(None) is None
        assert encrypt("") == ""
        assert decrypt("") == ""

    def test_legacy_plaintext_passes_through(self):
        """Rows written before encryption existed must keep working, not raise - they
        are re-encrypted on the next token refresh."""
        assert decrypt("ya29.legacy-plaintext-token") == "ya29.legacy-plaintext-token"
