"""Password hashing, JWT issuance/verification and signed-URL helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh"]

#: Work factor. 12 is the current sensible default: ~250ms per hash on commodity
#: hardware, which is slow enough to matter to an attacker and fast enough for login.
BCRYPT_ROUNDS = 12


# --------------------------------------------------------------------- passwords
def _prehash(plain: str) -> bytes:
    """SHA-256 then base64, so the value handed to bcrypt is always 44 bytes.

    bcrypt silently truncates input beyond 72 bytes. Without pre-hashing, two long
    passphrases sharing a 72-byte prefix would be interchangeable at login. Base64
    (rather than raw digest bytes) avoids embedded NULs, which bcrypt also truncates on.
    """
    return base64.b64encode(hashlib.sha256(plain.encode("utf-8")).digest())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_prehash(plain), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(plain), hashed.encode("ascii"))
    except (ValueError, TypeError):
        # A malformed stored hash must fail closed, not raise into the request.
        return False


def password_strength_errors(password: str) -> list[str]:
    """Return human-readable reasons a password is unacceptable (empty list = OK)."""
    errors: list[str] = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        errors.append(f"must be at least {settings.PASSWORD_MIN_LENGTH} characters")
    if not any(c.islower() for c in password):
        errors.append("must contain a lowercase letter")
    if not any(c.isupper() for c in password):
        errors.append("must contain an uppercase letter")
    if not any(c.isdigit() for c in password):
        errors.append("must contain a digit")
    if password.isalnum():
        errors.append("must contain a symbol")
    return errors


# ------------------------------------------------------------------------- jwt
def create_token(
    *,
    subject: str,
    token_type: TokenType,
    company_id: str | None = None,
    roles: list[str] | None = None,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """Issue a JWT.

    Returns ``(encoded_token, jti, expires_at)``. The ``jti`` is what the refresh-token
    store persists so a token can be revoked individually (rotation, logout, password
    change) without invalidating every session.
    """
    now = datetime.now(UTC)
    if expires_delta is None:
        expires_delta = (
            timedelta(minutes=settings.JWT_ACCESS_EXPIRE_MINUTES)
            if token_type == "access"
            else timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS)
        )
    expires_at = now + expires_delta
    jti = str(uuid.uuid4())

    payload: dict[str, Any] = {
        "sub": subject,
        "typ": token_type,
        "jti": jti,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": settings.APP_NAME,
    }
    if company_id:
        payload["cid"] = company_id
    if roles:
        payload["roles"] = roles
    if extra_claims:
        payload.update(extra_claims)

    encoded = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded, jti, expires_at


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    """Decode and validate a JWT. Raises ``jwt.PyJWTError`` subclasses on failure."""
    payload = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        issuer=settings.APP_NAME,
        options={"require": ["exp", "sub", "typ", "jti"]},
    )
    if expected_type is not None and payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError(
            f"expected a {expected_type} token, got {payload.get('typ')!r}"
        )
    return payload


# ------------------------------------------------------------- opaque secrets
def generate_url_token() -> str:
    """A single-use token for email verification / password reset links."""
    return secrets.token_urlsafe(48)


def hash_url_token(token: str) -> str:
    """Store only the digest, so a database leak does not yield usable reset links."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


# ---------------------------------------------------------------- signed URLs
def sign_storage_path(object_key: str, expires_at: int) -> str:
    """HMAC signature binding an object key to an expiry, for the local storage backend.

    S3-compatible storage uses the provider's own presigning; this exists so the local
    development backend still refuses unauthenticated/expired file access rather than
    serving private resumes from a public path.
    """
    message = f"{object_key}:{expires_at}".encode()
    digest = hmac.new(settings.JWT_SECRET.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_storage_signature(object_key: str, expires_at: int, signature: str) -> bool:
    if expires_at < int(datetime.now(UTC).timestamp()):
        return False
    return hmac.compare_digest(sign_storage_path(object_key, expires_at), signature)
