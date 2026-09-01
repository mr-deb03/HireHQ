"""Connecting a recruiter's mailbox, and syncing candidate replies from it."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import IntegrationProvider
from app.core.exceptions import InvalidToken, ProviderNotConfigured, ResourceNotFound
from app.core.logging import get_logger
from app.core.permissions import Perm
from app.core.responses import SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.communication import EmailAccount, EmailMessage
from app.providers.mailbox import get_mailbox_provider
from app.services.oauth_state import OAuthState, decode_state, encode_state
from app.services.oauth_tokens import ensure_fresh_access_token
from app.services.token_vault import encrypt as encrypt_token

logger = get_logger(__name__)

router = APIRouter(prefix="/emails/accounts", tags=["Emails"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

#: Read-only mail scopes. HireHQ reads candidate replies; it does not need send access,
#: because outbound mail goes through the company's own SMTP transport.
GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
)
MICROSOFT_SCOPES = ("Mail.Read", "User.Read", "offline_access")


class EmailAccountOut(BaseModel):
    id: uuid.UUID
    provider: str
    email_address: str
    display_name: str | None = None
    is_active: bool
    last_synced_at: datetime | None = None
    sync_error: str | None = None


class ConnectResponse(BaseModel):
    authorization_url: str
    provider: str
    instructions: str


class SyncResultOut(BaseModel):
    synced: bool
    messages_imported: int
    matched_to_candidates: int
    last_synced_at: datetime | None = None
    detail: str


def _provider_for(name: str) -> IntegrationProvider:
    try:
        return IntegrationProvider(name.upper())
    except ValueError as exc:
        raise ProviderNotConfigured(name, hint="Use 'google' or 'microsoft'.") from exc


def _authorization_url(provider: IntegrationProvider, state: str) -> str:
    if provider == IntegrationProvider.GOOGLE:
        if not settings.GOOGLE_CLIENT_ID:
            raise ProviderNotConfigured("Gmail", hint="Set GOOGLE_CLIENT_ID and secret.")
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "redirect_uri": f"{settings.BACKEND_BASE_URL}{settings.API_V1_PREFIX}/emails/accounts/callback",
                "response_type": "code",
                "scope": " ".join(GOOGLE_SCOPES),
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
        )

    if not settings.MICROSOFT_CLIENT_ID:
        raise ProviderNotConfigured("Outlook", hint="Set MICROSOFT_CLIENT_ID and secret.")
    return (
        f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize?"
        + urlencode(
            {
                "client_id": settings.MICROSOFT_CLIENT_ID,
                "redirect_uri": f"{settings.BACKEND_BASE_URL}{settings.API_V1_PREFIX}/emails/accounts/callback",
                "response_type": "code",
                "response_mode": "query",
                "scope": " ".join(MICROSOFT_SCOPES),
                "state": state,
            }
        )
    )


async def _exchange_code(provider: IntegrationProvider, code: str) -> dict:
    import httpx

    redirect = f"{settings.BACKEND_BASE_URL}{settings.API_V1_PREFIX}/emails/accounts/callback"
    if provider == IntegrationProvider.GOOGLE:
        url = "https://oauth2.googleapis.com/token"
        data = {
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
        }
    else:
        url = f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/token"
        data = {
            "code": code,
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "client_secret": settings.MICROSOFT_CLIENT_SECRET,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
            "scope": " ".join(MICROSOFT_SCOPES),
        }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, data=data)
    if response.status_code >= 400:
        raise InvalidToken(f"Token exchange failed ({response.status_code})")
    return response.json()


async def _fetch_address(provider: IntegrationProvider, access_token: str) -> tuple[str, str | None]:
    import httpx

    url, address_field, name_field = (
        ("https://www.googleapis.com/oauth2/v2/userinfo", "email", "name")
        if provider == IntegrationProvider.GOOGLE
        else ("https://graph.microsoft.com/v1.0/me", "mail", "displayName")
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )
        body = response.json() if response.status_code < 400 else {}
    except Exception:
        body = {}
    address = body.get(address_field) or body.get("userPrincipalName") or "unknown"
    return address, body.get(name_field)


# ------------------------------------------------------------------- routes
@router.get(
    "",
    response_model=SuccessResponse[list[EmailAccountOut]],
    summary="List connected mailboxes",
    dependencies=[Depends(require_permission(Perm.EMAIL_READ))],
)
async def list_accounts(
    principal: CurrentUser, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[EmailAccountOut]]:
    rows = (
        (
            await session.execute(
                select(EmailAccount).where(
                    EmailAccount.company_id == company_id,
                    EmailAccount.user_id == principal.id,
                )
            )
        )
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=[
            EmailAccountOut(
                id=a.id,
                provider=a.provider.value,
                email_address=a.email_address,
                display_name=a.display_name,
                is_active=a.is_active,
                last_synced_at=a.last_synced_at,
                sync_error=a.sync_error,
            )
            for a in rows
        ]
    )


@router.post(
    "/connect",
    response_model=SuccessResponse[ConnectResponse],
    summary="Start mailbox OAuth",
    description=(
        "Returns the provider's consent URL for read-only mailbox access. HireHQ stores "
        "OAuth tokens encrypted at rest and never asks for a mailbox password."
    ),
    dependencies=[Depends(require_permission(Perm.EMAIL_ACCOUNT_CONNECT))],
)
async def connect_mailbox(
    principal: CurrentUser,
    company_id: CompanyScope,
    provider: Annotated[str, Query(description="google | microsoft")] = "google",
) -> SuccessResponse[ConnectResponse]:
    resolved = _provider_for(provider)
    state = encode_state(
        OAuthState(
            user_id=principal.id,
            company_id=company_id,
            provider=resolved.value.lower(),
            purpose="email",
        )
    )
    return SuccessResponse(
        data=ConnectResponse(
            authorization_url=_authorization_url(resolved, state),
            provider=resolved.value.lower(),
            instructions=(
                "Send the user to authorization_url. After consent the provider "
                "redirects back and the mailbox begins syncing candidate replies."
            ),
        )
    )


@router.get(
    "/callback",
    summary="Mailbox OAuth callback",
    description=(
        "Where the provider redirects after consent. Unauthenticated by design - the "
        "signed `state` carries and proves the identity."
    ),
)
async def mailbox_callback(
    session: DbSession,
    state: Annotated[str, Query()],
    code: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    inbox_url = f"{settings.FRONTEND_BASE_URL}/recruiter/emails"

    if error or not code:
        return RedirectResponse(
            f"{inbox_url}?connected=0&reason={quote(error or 'missing_code')}", 303
        )

    try:
        decoded = decode_state(state, expected_purpose="email")
    except InvalidToken:
        return RedirectResponse(f"{inbox_url}?connected=0&reason=invalid_state", 303)

    resolved = _provider_for(decoded.provider)
    try:
        tokens = await _exchange_code(resolved, code)
    except Exception as exc:
        logger.warning("mailbox_oauth_exchange_failed", error=str(exc)[:200])
        return RedirectResponse(f"{inbox_url}?connected=0&reason=exchange_failed", 303)

    access_token = tokens.get("access_token", "")
    address, display_name = await _fetch_address(resolved, access_token)

    account = await session.scalar(
        select(EmailAccount).where(
            EmailAccount.company_id == decoded.company_id,
            EmailAccount.user_id == decoded.user_id,
            EmailAccount.provider == resolved,
        )
    )
    if account is None:
        account = EmailAccount(
            company_id=decoded.company_id,
            user_id=decoded.user_id,
            provider=resolved,
            email_address=address,
        )
        session.add(account)

    account.email_address = address
    account.display_name = display_name
    account.access_token_ref = encrypt_token(access_token)
    if tokens.get("refresh_token"):
        account.refresh_token_ref = encrypt_token(tokens["refresh_token"])
    if tokens.get("expires_in"):
        account.token_expires_at = datetime.now(UTC) + timedelta(
            seconds=int(tokens["expires_in"])
        )
    account.scopes = (tokens.get("scope") or "").split()
    account.is_active = True
    account.sync_error = None
    await session.flush()

    logger.info("mailbox_connected", provider=resolved.value, address=address)
    return RedirectResponse(f"{inbox_url}?connected=1", 303)


@router.post(
    "/{account_id}/sync",
    response_model=SuccessResponse[SyncResultOut],
    summary="Sync a mailbox now",
    description=(
        "Pulls recent messages and attaches candidate replies to the right application. "
        "Runs automatically every few minutes when a worker is configured."
    ),
    dependencies=[Depends(require_permission(Perm.EMAIL_ACCOUNT_CONNECT))],
)
async def sync_now(
    account_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[SyncResultOut]:
    account = await session.scalar(
        select(EmailAccount).where(
            EmailAccount.id == account_id, EmailAccount.company_id == company_id
        )
    )
    if account is None:
        raise ResourceNotFound("Email account", account_id)

    result = await sync_account(session, account)
    return SuccessResponse(data=result, message=result.detail)


@router.delete(
    "/{account_id}",
    response_model=SuccessResponse[dict],
    summary="Disconnect a mailbox",
    dependencies=[Depends(require_permission(Perm.EMAIL_ACCOUNT_CONNECT))],
)
async def disconnect(
    account_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[dict]:
    account = await session.scalar(
        select(EmailAccount).where(
            EmailAccount.id == account_id, EmailAccount.company_id == company_id
        )
    )
    if account is None:
        raise ResourceNotFound("Email account", account_id)
    await session.delete(account)
    await session.flush()
    return SuccessResponse(data={"disconnected": True}, message="Mailbox disconnected")


# -------------------------------------------------------------------- sync
async def sync_account(session: AsyncSession, account: EmailAccount) -> SyncResultOut:
    """Import recent messages from one mailbox.

    Idempotent: a message already stored (by provider id) is skipped, so overlapping
    runs and re-syncs cannot duplicate a candidate's reply in the inbox.
    """
    from app.modules.emails.service import EmailService
    from app.services.events import DomainEvent, Events, event_bus

    provider = get_mailbox_provider(account.provider)
    if not provider.can_sync:
        detail = "No mailbox provider is available for this account."
        account.sync_error = detail
        await session.flush()
        return SyncResultOut(
            synced=False, messages_imported=0, matched_to_candidates=0, detail=detail
        )

    access_token = await ensure_fresh_access_token(session, account)
    if not access_token:
        detail = account.sync_error or "The mailbox authorisation is no longer valid."
        return SyncResultOut(
            synced=False,
            messages_imported=0,
            matched_to_candidates=0,
            last_synced_at=account.last_synced_at,
            detail=detail,
        )

    result = await provider.fetch_recent(access_token=access_token, cursor=account.sync_cursor)
    if not result.ok:
        account.sync_error = result.error
        await session.flush()
        logger.warning("mailbox_sync_failed", detail=result.error)
        return SyncResultOut(
            synced=False,
            messages_imported=0,
            matched_to_candidates=0,
            last_synced_at=account.last_synced_at,
            detail=result.error or "Sync failed",
        )

    service = EmailService(session, account.company_id)
    imported = 0
    matched = 0
    events: list[DomainEvent] = []

    for message in result.messages:
        # Skip our own outbound mail echoed back by the provider, and anything already
        # imported by a previous run.
        if message.from_address == account.email_address.lower():
            continue
        already = await session.scalar(
            select(EmailMessage.id).where(
                EmailMessage.company_id == account.company_id,
                EmailMessage.external_message_id == message.external_id,
            )
        )
        if already:
            continue

        stored = await service.record_inbound(
            from_address=message.from_address,
            to_addresses=message.to_addresses,
            subject=message.subject,
            body_html=message.body_html,
            body_text=message.body_text,
            external_message_id=message.external_id,
            external_thread_id=message.thread_id,
            account_id=account.id,
            received_at=message.received_at,
        )
        imported += 1
        if stored.candidate_id:
            matched += 1
            events.append(
                DomainEvent(
                    name=Events.EMAIL_RECEIVED,
                    company_id=account.company_id,
                    entity_type="EmailMessage",
                    entity_id=stored.id,
                    payload={
                        "candidate_id": str(stored.candidate_id),
                        "candidate_name": message.from_name or message.from_address,
                        "job_id": None,
                    },
                )
            )

    account.sync_cursor = result.cursor
    account.last_synced_at = datetime.now(UTC)
    account.sync_error = None
    await session.flush()
    await session.commit()

    # Published after commit so a notification never references an uncommitted message.
    for event in events:
        await event_bus.publish(event)

    logger.info(
        "mailbox_synced",
        provider=account.provider.value,
        imported=imported,
        matched=matched,
    )
    return SyncResultOut(
        synced=True,
        messages_imported=imported,
        matched_to_candidates=matched,
        last_synced_at=account.last_synced_at,
        detail=(
            f"Imported {imported} message(s); {matched} matched to a candidate."
            if imported
            else "No new messages."
        ),
    )
