"""Encryption for stored OAuth tokens.

``EmailAccount`` and ``CalendarAccount`` hold provider refresh tokens, which are
long-lived credentials to a person's mailbox and calendar. Storing them as plaintext
would make a database dump equivalent to handing over those accounts, so they are
encrypted at rest and only decrypted at the moment of use.

Encryption is AES-256-GCM when ``cryptography`` is available (authenticated, so tampering
is detected), falling back to an HMAC-authenticated XOR stream otherwise. The fallback is
weaker and says so loudly at startup - it exists so the product runs on a bare
installation, not because it is good enough for production.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from functools import lru_cache

from app.core.config import settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger

logger = get_logger(__name__)

_PREFIX_AESGCM = "v1.gcm."
_PREFIX_FALLBACK = "v1.xor."


@lru_cache(maxsize=1)
def _key() -> bytes:
    """Derive a 32-byte key from the application secret.

    A dedicated ``TOKEN_ENCRYPTION_KEY`` would be better practice, but deriving from
    ``JWT_SECRET`` with a distinct salt means there is no second secret to forget to set -
    and rotating ``JWT_SECRET`` correctly invalidates stored tokens along with sessions.
    """
    return hashlib.pbkdf2_hmac(
        "sha256", settings.JWT_SECRET.encode("utf-8"), b"hirehq.token-vault.v1", 200_000, 32
    )


@lru_cache(maxsize=1)
def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        return AESGCM(_key())
    except ImportError:
        logger.warning(
            "token_vault_degraded",
            detail=(
                "The 'cryptography' package is not installed, so OAuth tokens use the "
                "weaker built-in cipher. Install cryptography for AES-256-GCM."
            ),
        )
        return None


def encrypt(plaintext: str | None) -> str | None:
    """Encrypt a token for storage. ``None`` passes through unchanged."""
    if plaintext is None or plaintext == "":
        return plaintext

    raw = plaintext.encode("utf-8")
    cipher = _aesgcm()
    if cipher is not None:
        nonce = os.urandom(12)
        blob = nonce + cipher.encrypt(nonce, raw, None)
        return _PREFIX_AESGCM + base64.urlsafe_b64encode(blob).decode("ascii")

    # Fallback: keystream from the derived key, plus an HMAC so tampering is detected.
    nonce = os.urandom(16)
    stream = _keystream(nonce, len(raw))
    body = bytes(a ^ b for a, b in zip(raw, stream, strict=True))
    tag = hmac.new(_key(), nonce + body, hashlib.sha256).digest()[:16]
    return _PREFIX_FALLBACK + base64.urlsafe_b64encode(nonce + tag + body).decode("ascii")


def decrypt(ciphertext: str | None) -> str | None:
    """Decrypt a stored token. Raises if it has been tampered with."""
    if ciphertext is None or ciphertext == "":
        return ciphertext

    if ciphertext.startswith(_PREFIX_AESGCM):
        cipher = _aesgcm()
        if cipher is None:
            raise ExternalServiceError(
                "This token was encrypted with AES-GCM but 'cryptography' is not "
                "installed on this server",
                code="TOKEN_VAULT_UNAVAILABLE",
            )
        blob = base64.urlsafe_b64decode(ciphertext[len(_PREFIX_AESGCM) :])
        try:
            return cipher.decrypt(blob[:12], blob[12:], None).decode("utf-8")
        except Exception as exc:
            raise ExternalServiceError(
                "A stored OAuth token could not be decrypted", code="TOKEN_DECRYPT_FAILED"
            ) from exc

    if ciphertext.startswith(_PREFIX_FALLBACK):
        blob = base64.urlsafe_b64decode(ciphertext[len(_PREFIX_FALLBACK) :])
        nonce, tag, body = blob[:16], blob[16:32], blob[32:]
        expected = hmac.new(_key(), nonce + body, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, expected):
            raise ExternalServiceError(
                "A stored OAuth token failed its integrity check",
                code="TOKEN_DECRYPT_FAILED",
            )
        stream = _keystream(nonce, len(body))
        return bytes(a ^ b for a, b in zip(body, stream, strict=True)).decode("utf-8")

    # Written before encryption existed, or by an older deployment. Return as-is so the
    # integration keeps working; it will be re-encrypted on the next token refresh.
    logger.warning("token_vault_plaintext_encountered")
    return ciphertext


def _keystream(nonce: bytes, length: int) -> bytes:
    """Counter-mode keystream from SHA-256, for the no-dependency fallback."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(_key() + nonce + counter.to_bytes(4, "big")).digest()
        counter += 1
    return bytes(out[:length])


def reset() -> None:
    """Drop cached key material. Used by tests that change the secret."""
    _key.cache_clear()
    _aesgcm.cache_clear()
