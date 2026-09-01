"""OAuth access-token refresh, shared by the calendar and email integrations.

Both ``CalendarAccount`` and ``EmailAccount`` store the same shape of credential, so the
refresh logic lives here rather than being duplicated (and drifting) in two services.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import IntegrationProvider
from app.core.logging import get_logger
from app.services.token_vault import decrypt, encrypt

logger = get_logger(__name__)

#: Refresh this long before actual expiry, so a token cannot lapse mid-request.
REFRESH_SKEW = timedelta(minutes=5)


class OAuthAccount(Protocol):
    """The fields both account models share."""

    provider: IntegrationProvider
    access_token_ref: str | None
    refresh_token_ref: str | None
    token_expires_at: datetime | None
    is_active: bool
    sync_error: str | None


def _token_endpoint(provider: IntegrationProvider) -> tuple[str, dict[str, str]] | None:
    if provider == IntegrationProvider.GOOGLE:
        if not (settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET):
            return None
        return (
            "https://oauth2.googleapis.com/token",
            {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
            },
        )
    if provider == IntegrationProvider.MICROSOFT:
        if not (settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET):
            return None
        return (
            f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/token",
            {
                "client_id": settings.MICROSOFT_CLIENT_ID,
                "client_secret": settings.MICROSOFT_CLIENT_SECRET,
            },
        )
    return None


async def ensure_fresh_access_token(
    session: AsyncSession, account: Any
) -> str | None:
    """Return a usable access token, refreshing it first if it is expired or about to be.

    Returns ``None`` when the account cannot produce one - the caller then behaves as if
    no integration were connected, which is the honest outcome rather than an exception
    in the middle of scheduling an interview.
    """
    if not account.is_active:
        return None

    expires_at = account.token_expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    still_valid = expires_at is None or expires_at - REFRESH_SKEW > datetime.now(UTC)
    if still_valid and account.access_token_ref:
        return decrypt(account.access_token_ref)

    refresh_token = decrypt(account.refresh_token_ref) if account.refresh_token_ref else None
    if not refresh_token:
        account.sync_error = (
            "The stored authorisation has expired and no refresh token is available. "
            "Reconnect the account."
        )
        account.is_active = False
        await session.flush()
        logger.warning("oauth_refresh_unavailable", provider=account.provider.value)
        return None

    endpoint = _token_endpoint(account.provider)
    if endpoint is None:
        account.sync_error = "The provider is no longer configured on this server."
        await session.flush()
        return None

    url, credentials = endpoint
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                data={
                    **credentials,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
    except Exception as exc:
        account.sync_error = f"Could not reach the token endpoint: {exc}"[:500]
        await session.flush()
        logger.warning("oauth_refresh_unreachable", error=str(exc)[:200])
        return None

    if response.status_code >= 400:
        # A 400 here usually means the user revoked access; deactivate so the UI prompts
        # them to reconnect instead of retrying forever.
        account.sync_error = (
            f"The provider rejected the refresh ({response.status_code}). Reconnect the account."
        )
        account.is_active = response.status_code >= 500
        await session.flush()
        logger.warning("oauth_refresh_rejected", status=response.status_code)
        return None

    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        account.sync_error = "The provider returned no access token."
        await session.flush()
        return None

    account.access_token_ref = encrypt(access_token)
    if payload.get("refresh_token"):
        # Providers may rotate the refresh token; store the new one or the next refresh
        # fails.
        account.refresh_token_ref = encrypt(payload["refresh_token"])
    if payload.get("expires_in"):
        account.token_expires_at = datetime.now(UTC) + timedelta(
            seconds=int(payload["expires_in"])
        )
    account.sync_error = None
    await session.flush()

    logger.info("oauth_token_refreshed", provider=account.provider.value)
    return access_token
