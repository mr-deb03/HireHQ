"""Interview calendar views and provider (OAuth) integration."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import IntegrationProvider
from app.core.exceptions import InvalidToken, ProviderNotConfigured, ValidationError
from app.core.logging import get_logger
from app.core.permissions import Perm
from app.core.responses import SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.calendar import CalendarAccount, CalendarEvent
from app.modules.interviews.schemas import CalendarEventOut, CalendarView
from app.providers.calendar import get_calendar_provider
from app.services.oauth_state import OAuthState, decode_state, encode_state
from app.services.token_vault import encrypt as encrypt_token

logger = get_logger(__name__)

router = APIRouter(prefix="/calendar", tags=["Calendar"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class CalendarAccountOut(BaseModel):
    id: uuid.UUID
    provider: str
    account_email: str
    is_active: bool
    last_synced_at: datetime | None = None
    sync_error: str | None = None


class ConnectResponse(BaseModel):
    authorization_url: str
    provider: str
    state: str
    instructions: str


class ProviderStatusOut(BaseModel):
    provider: str
    delivers_invitations: bool
    connected_account: CalendarAccountOut | None = None
    message: str


def _range_for(view: str, anchor: date) -> tuple[datetime, datetime]:
    """Resolve a view name and anchor date into an inclusive UTC range."""
    start_of_day = datetime.combine(anchor, time.min, tzinfo=UTC)
    if view == "day":
        return start_of_day, start_of_day + timedelta(days=1)
    if view == "week":
        monday = anchor - timedelta(days=anchor.weekday())
        start = datetime.combine(monday, time.min, tzinfo=UTC)
        return start, start + timedelta(days=7)
    if view == "month":
        first = anchor.replace(day=1)
        next_month = (first + timedelta(days=32)).replace(day=1)
        return (
            datetime.combine(first, time.min, tzinfo=UTC),
            datetime.combine(next_month, time.min, tzinfo=UTC),
        )
    if view == "agenda":
        return start_of_day, start_of_day + timedelta(days=30)
    raise ValidationError("view must be one of: day, week, month, agenda")


@router.get(
    "/events",
    response_model=SuccessResponse[CalendarView],
    summary="Calendar view of interviews",
    description=(
        "Day, week, month or agenda view. `provider_status` reports whether an external "
        "calendar is connected - when it is not, events exist in HireHQ only."
    ),
    dependencies=[Depends(require_permission(Perm.CALENDAR_READ))],
)
async def calendar_events(
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
    view: Annotated[str, Query(description="day | week | month | agenda")] = "week",
    anchor: Annotated[date | None, Query(description="Date the view centres on")] = None,
    mine_only: Annotated[bool, Query(description="Only events I organise or attend")] = False,
) -> SuccessResponse[CalendarView]:
    start, end = _range_for(view, anchor or date.today())

    stmt = select(CalendarEvent).where(
        CalendarEvent.company_id == company_id,
        CalendarEvent.start_at >= start,
        CalendarEvent.start_at < end,
        CalendarEvent.status != "CANCELLED",
    )
    if mine_only or not principal.has(Perm.CALENDAR_MANAGE):
        from app.models.interview import InterviewParticipant

        stmt = stmt.where(
            (CalendarEvent.organiser_id == principal.id)
            | (
                CalendarEvent.interview_id.in_(
                    select(InterviewParticipant.interview_id).where(
                        InterviewParticipant.user_id == principal.id
                    )
                )
            )
        )

    events = (
        (await session.execute(stmt.order_by(CalendarEvent.start_at))).scalars().all()
    )

    provider = get_calendar_provider()
    provider_status = (
        f"{provider.name} connected"
        if provider.delivers_invitations
        else (
            "No calendar provider connected - events exist in HireHQ only and no "
            "external invitations are sent."
        )
    )

    return SuccessResponse(
        data=CalendarView(
            view=view,
            start=start,
            end=end,
            events=[CalendarEventOut.model_validate(e) for e in events],
            total=len(events),
            provider_status=provider_status,
        )
    )


@router.get(
    "/status",
    response_model=SuccessResponse[ProviderStatusOut],
    summary="Calendar integration status",
    dependencies=[Depends(require_permission(Perm.CALENDAR_READ))],
)
async def provider_status(
    principal: CurrentUser, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[ProviderStatusOut]:
    provider = get_calendar_provider()
    account = await session.scalar(
        select(CalendarAccount).where(
            CalendarAccount.user_id == principal.id,
            CalendarAccount.company_id == company_id,
            CalendarAccount.is_active.is_(True),
        )
    )
    message = (
        f"Connected to {account.provider.value} as {account.account_email}"
        if account
        else (
            f"No account connected. The server is configured for "
            f"'{settings.CALENDAR_PROVIDER}'."
            if provider.delivers_invitations
            else (
                "No calendar provider is configured on this server. Interviews are "
                "created in HireHQ and candidates are emailed, but no calendar "
                "invitations are sent."
            )
        )
    )
    return SuccessResponse(
        data=ProviderStatusOut(
            provider=provider.name,
            delivers_invitations=provider.delivers_invitations,
            connected_account=(
                CalendarAccountOut(
                    id=account.id,
                    provider=account.provider.value,
                    account_email=account.account_email,
                    is_active=account.is_active,
                    last_synced_at=account.last_synced_at,
                    sync_error=account.sync_error,
                )
                if account
                else None
            ),
            message=message,
        )
    )


@router.post(
    "/connect",
    response_model=SuccessResponse[ConnectResponse],
    summary="Start calendar OAuth",
    description=(
        "Returns the provider's consent URL. HireHQ stores OAuth tokens only - never a "
        "password. Fails clearly when no provider is configured rather than pretending."
    ),
    dependencies=[Depends(require_permission(Perm.CALENDAR_MANAGE))],
)
async def connect_calendar(
    principal: CurrentUser, company_id: CompanyScope
) -> SuccessResponse[ConnectResponse]:
    provider = get_calendar_provider()
    if not provider.delivers_invitations:
        raise ProviderNotConfigured(
            "Calendar",
            hint=(
                "Set CALENDAR_PROVIDER to google or microsoft and supply the matching "
                "client id and secret."
            ),
        )

    # A signed state binds the callback to this user, so a completed flow can never
    # attach someone else's calendar to their account.
    state = encode_state(
        OAuthState(
            user_id=principal.id,
            company_id=company_id,
            provider=provider.name,
            purpose="calendar",
        )
    )
    url = provider.authorization_url(state)
    return SuccessResponse(
        data=ConnectResponse(
            authorization_url=url,
            provider=provider.name,
            state=state,
            instructions=(
                "Send the user to authorization_url. The provider redirects back to "
                f"{settings.BACKEND_BASE_URL}{settings.API_V1_PREFIX}/calendar/callback "
                "with a code and this state, which completes the connection."
            ),
        )
    )


@router.get(
    "/callback",
    summary="Calendar OAuth callback",
    description=(
        "Where the provider redirects after consent. Exchanges the authorisation code "
        "for tokens, stores them encrypted, and redirects the user back to the app.\n\n"
        "Unauthenticated by design - the signed `state` parameter carries and proves the "
        "identity, because the provider redirects the browser here without our header."
    ),
    include_in_schema=True,
)
async def calendar_callback(
    session: DbSession,
    state: Annotated[str, Query(description="Signed state issued by /calendar/connect")],
    code: Annotated[str | None, Query(description="Authorisation code")] = None,
    error: Annotated[str | None, Query(description="Provider error, if consent failed")] = None,
) -> RedirectResponse:
    settings_url = f"{settings.FRONTEND_BASE_URL}/recruiter/calendar"

    if error:
        logger.info("calendar_oauth_declined", provider_error=error)
        return RedirectResponse(f"{settings_url}?connected=0&reason={quote(error)}", 303)
    if not code:
        return RedirectResponse(f"{settings_url}?connected=0&reason=missing_code", 303)

    try:
        decoded = decode_state(state, expected_purpose="calendar")
    except InvalidToken as exc:
        logger.warning("calendar_oauth_bad_state", detail=exc.message)
        return RedirectResponse(f"{settings_url}?connected=0&reason=invalid_state", 303)

    provider = get_calendar_provider()
    exchange = getattr(provider, "exchange_code", None)
    if exchange is None:
        return RedirectResponse(f"{settings_url}?connected=0&reason=provider_unavailable", 303)

    try:
        tokens = await exchange(code)
    except Exception as exc:
        logger.warning("calendar_oauth_exchange_failed", error=str(exc)[:200])
        return RedirectResponse(f"{settings_url}?connected=0&reason=exchange_failed", 303)

    account_email = await _fetch_account_email(provider.name, tokens.get("access_token", ""))

    existing = await session.scalar(
        select(CalendarAccount).where(
            CalendarAccount.user_id == decoded.user_id,
            CalendarAccount.company_id == decoded.company_id,
            CalendarAccount.provider == IntegrationProvider(provider.name.upper()),
        )
    )
    expires_at = (
        datetime.now(UTC) + timedelta(seconds=int(tokens["expires_in"]))
        if tokens.get("expires_in")
        else None
    )

    if existing is None:
        existing = CalendarAccount(
            company_id=decoded.company_id,
            user_id=decoded.user_id,
            provider=IntegrationProvider(provider.name.upper()),
            account_email=account_email or "unknown",
        )
        session.add(existing)

    existing.access_token_ref = encrypt_token(tokens.get("access_token"))
    # Providers omit refresh_token on re-consent; keep the one we already hold.
    if tokens.get("refresh_token"):
        existing.refresh_token_ref = encrypt_token(tokens["refresh_token"])
    existing.token_expires_at = expires_at
    existing.scopes = (tokens.get("scope") or "").split()
    existing.is_active = True
    existing.sync_error = None
    existing.last_synced_at = datetime.now(UTC)
    if account_email:
        existing.account_email = account_email

    await session.flush()
    logger.info(
        "calendar_connected", provider=provider.name, user_id=str(decoded.user_id)
    )
    return RedirectResponse(f"{settings_url}?connected=1", 303)


async def _fetch_account_email(provider_name: str, access_token: str) -> str | None:
    """Read the connected account's address so the UI can show what is linked."""
    if not access_token:
        return None
    import httpx

    endpoints = {
        "google": ("https://www.googleapis.com/oauth2/v2/userinfo", "email"),
        "microsoft": ("https://graph.microsoft.com/v1.0/me", "mail"),
    }
    endpoint = endpoints.get(provider_name)
    if endpoint is None:
        return None

    url, field = endpoint
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )
        if response.status_code >= 400:
            return None
        body = response.json()
        return body.get(field) or body.get("userPrincipalName")
    except Exception:
        # Cosmetic only - a missing address must not fail the connection.
        return None


@router.delete(
    "/disconnect",
    response_model=SuccessResponse[dict],
    summary="Disconnect the calendar",
    description="Removes the stored tokens. Existing HireHQ events are unaffected.",
    dependencies=[Depends(require_permission(Perm.CALENDAR_MANAGE))],
)
async def disconnect_calendar(
    principal: CurrentUser, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[dict]:
    account = await session.scalar(
        select(CalendarAccount).where(
            CalendarAccount.user_id == principal.id,
            CalendarAccount.company_id == company_id,
        )
    )
    if account is None:
        return SuccessResponse(
            data={"disconnected": False}, message="No calendar account was connected"
        )

    await session.delete(account)
    await session.flush()
    return SuccessResponse(
        data={"disconnected": True}, message="Calendar disconnected"
    )


@router.get(
    "/events/{event_id}",
    response_model=SuccessResponse[CalendarEventOut],
    summary="Get a calendar event",
    dependencies=[Depends(require_permission(Perm.CALENDAR_READ))],
)
async def get_event(
    event_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[CalendarEventOut]:
    from app.core.exceptions import ResourceNotFound

    event = await session.scalar(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id, CalendarEvent.company_id == company_id
        )
    )
    if event is None:
        raise ResourceNotFound("Calendar event", event_id)
    return SuccessResponse(data=CalendarEventOut.model_validate(event))
