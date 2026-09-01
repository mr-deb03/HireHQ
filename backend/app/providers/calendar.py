"""Calendar provider abstraction (Google Calendar / Microsoft Graph).

HireHQ's own ``calendar_events`` table is always the source of truth. A provider mirrors
an event outward and sends real invitations. When no provider is connected, the event is
still created and returned with ``sync_status=PENDING_NO_PROVIDER`` - the API never
claims an invitation was delivered to anyone's calendar (s69).

Both real providers speak OAuth. No password is ever stored.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

import httpx

from app.core.config import settings
from app.core.enums import IntegrationProvider
from app.core.exceptions import ExternalServiceError, ProviderNotConfigured
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class CalendarAttendee:
    email: str
    name: str | None = None
    optional: bool = False


@dataclass(slots=True)
class CalendarEventPayload:
    title: str
    start_at: datetime
    end_at: datetime
    timezone: str = "UTC"
    description: str | None = None
    location: str | None = None
    meeting_link: str | None = None
    attendees: list[CalendarAttendee] = field(default_factory=list)
    #: Ask the provider to mint a video-conference link (Meet / Teams).
    create_conference: bool = False


@dataclass(slots=True)
class CalendarSyncResult:
    #: SYNCED | PENDING_NO_PROVIDER | FAILED
    status: str
    provider: IntegrationProvider | None = None
    external_event_id: str | None = None
    meeting_link: str | None = None
    detail: str | None = None

    @property
    def synced(self) -> bool:
        return self.status == "SYNCED"


class CalendarProvider(ABC):
    name: str = "abstract"
    provider_enum: IntegrationProvider | None = None
    #: False means invitations are not actually delivered anywhere.
    delivers_invitations: bool = False

    @abstractmethod
    async def create_event(
        self, payload: CalendarEventPayload, *, access_token: str | None = None
    ) -> CalendarSyncResult: ...

    @abstractmethod
    async def update_event(
        self, external_event_id: str, payload: CalendarEventPayload, *, access_token: str | None = None
    ) -> CalendarSyncResult: ...

    @abstractmethod
    async def cancel_event(
        self, external_event_id: str, *, access_token: str | None = None
    ) -> CalendarSyncResult: ...

    def authorization_url(self, state: str) -> str:
        raise ProviderNotConfigured(self.name, hint="This provider has no OAuth flow.")


class UnconfiguredCalendarProvider(CalendarProvider):
    """Used when no calendar integration is connected.

    Not a fake: it performs no work and says so. Interviews still exist in HireHQ and
    candidates are still emailed by the email service; only the external calendar mirror
    is absent.
    """

    name = "none"
    delivers_invitations = False

    async def create_event(
        self, payload: CalendarEventPayload, *, access_token: str | None = None
    ) -> CalendarSyncResult:
        return CalendarSyncResult(
            status="PENDING_NO_PROVIDER",
            detail=(
                "No calendar provider is connected. The interview exists in HireHQ, but "
                "no external calendar event or invitation was created."
            ),
        )

    async def update_event(
        self, external_event_id: str, payload: CalendarEventPayload, *, access_token: str | None = None
    ) -> CalendarSyncResult:
        return await self.create_event(payload)

    async def cancel_event(
        self, external_event_id: str, *, access_token: str | None = None
    ) -> CalendarSyncResult:
        return CalendarSyncResult(
            status="PENDING_NO_PROVIDER", detail="No calendar provider is connected."
        )


class GoogleCalendarProvider(CalendarProvider):
    """Google Calendar via the v3 REST API using a user's OAuth access token."""

    name = "google"
    provider_enum = IntegrationProvider.GOOGLE
    delivers_invitations = True

    API_BASE = "https://www.googleapis.com/calendar/v3"
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SCOPES = ("https://www.googleapis.com/auth/calendar.events",)

    def __init__(self) -> None:
        if not (settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET):
            raise ProviderNotConfigured(
                "Google Calendar", hint="Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
            )

    def authorization_url(self, state: str) -> str:
        from urllib.parse import urlencode

        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI or "",
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
        if response.status_code >= 400:
            raise ExternalServiceError(f"Google token exchange failed: {response.text[:200]}")
        return response.json()

    def _to_google(self, payload: CalendarEventPayload) -> dict:
        body: dict = {
            "summary": payload.title,
            "description": payload.description or "",
            "start": {"dateTime": payload.start_at.isoformat(), "timeZone": payload.timezone},
            "end": {"dateTime": payload.end_at.isoformat(), "timeZone": payload.timezone},
            "attendees": [
                {"email": a.email, "displayName": a.name, "optional": a.optional}
                for a in payload.attendees
            ],
            "reminders": {"useDefault": True},
        }
        if payload.location:
            body["location"] = payload.location
        if payload.create_conference:
            body["conferenceData"] = {
                "createRequest": {
                    "requestId": f"hirehq-{int(payload.start_at.timestamp())}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
        return body

    async def _request(
        self, method: str, url: str, access_token: str | None, **kwargs
    ) -> CalendarSyncResult | dict:
        if not access_token:
            raise ProviderNotConfigured(
                "Google Calendar", hint="The user has not connected their Google account."
            )
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                **kwargs,
            )
        if response.status_code >= 400:
            logger.warning("google_calendar_error", status=response.status_code)
            return CalendarSyncResult(
                status="FAILED",
                provider=self.provider_enum,
                detail=f"Google Calendar returned {response.status_code}",
            )
        return response.json() if response.content else {}

    async def create_event(
        self, payload: CalendarEventPayload, *, access_token: str | None = None
    ) -> CalendarSyncResult:
        result = await self._request(
            "POST",
            f"{self.API_BASE}/calendars/primary/events",
            access_token,
            params={"sendUpdates": "all", "conferenceDataVersion": 1 if payload.create_conference else 0},
            json=self._to_google(payload),
        )
        if isinstance(result, CalendarSyncResult):
            return result
        link = result.get("hangoutLink") or payload.meeting_link
        return CalendarSyncResult(
            status="SYNCED",
            provider=self.provider_enum,
            external_event_id=result.get("id"),
            meeting_link=link,
        )

    async def update_event(
        self, external_event_id: str, payload: CalendarEventPayload, *, access_token: str | None = None
    ) -> CalendarSyncResult:
        result = await self._request(
            "PATCH",
            f"{self.API_BASE}/calendars/primary/events/{external_event_id}",
            access_token,
            params={"sendUpdates": "all"},
            json=self._to_google(payload),
        )
        if isinstance(result, CalendarSyncResult):
            return result
        return CalendarSyncResult(
            status="SYNCED",
            provider=self.provider_enum,
            external_event_id=result.get("id", external_event_id),
            meeting_link=result.get("hangoutLink"),
        )

    async def cancel_event(
        self, external_event_id: str, *, access_token: str | None = None
    ) -> CalendarSyncResult:
        result = await self._request(
            "DELETE",
            f"{self.API_BASE}/calendars/primary/events/{external_event_id}",
            access_token,
            params={"sendUpdates": "all"},
        )
        if isinstance(result, CalendarSyncResult):
            return result
        return CalendarSyncResult(status="SYNCED", provider=self.provider_enum)


class MicrosoftCalendarProvider(CalendarProvider):
    """Outlook / Microsoft 365 calendar via Microsoft Graph."""

    name = "microsoft"
    provider_enum = IntegrationProvider.MICROSOFT
    delivers_invitations = True

    API_BASE = "https://graph.microsoft.com/v1.0"
    SCOPES = ("Calendars.ReadWrite", "offline_access", "User.Read")

    def __init__(self) -> None:
        if not (settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET):
            raise ProviderNotConfigured(
                "Microsoft Calendar",
                hint="Set MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET.",
            )
        self.tenant = settings.MICROSOFT_TENANT_ID

    @property
    def auth_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/authorize"

    @property
    def token_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token"

    def authorization_url(self, state: str) -> str:
        from urllib.parse import urlencode

        params = {
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.MICROSOFT_REDIRECT_URI or "",
            "response_mode": "query",
            "scope": " ".join(self.SCOPES),
            "state": state,
        }
        return f"{self.auth_url}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.token_url,
                data={
                    "client_id": settings.MICROSOFT_CLIENT_ID,
                    "client_secret": settings.MICROSOFT_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
                    "grant_type": "authorization_code",
                    "scope": " ".join(self.SCOPES),
                },
            )
        if response.status_code >= 400:
            raise ExternalServiceError(f"Microsoft token exchange failed: {response.text[:200]}")
        return response.json()

    def _to_graph(self, payload: CalendarEventPayload) -> dict:
        body: dict = {
            "subject": payload.title,
            "body": {"contentType": "HTML", "content": payload.description or ""},
            "start": {"dateTime": payload.start_at.isoformat(), "timeZone": payload.timezone},
            "end": {"dateTime": payload.end_at.isoformat(), "timeZone": payload.timezone},
            "attendees": [
                {
                    "emailAddress": {"address": a.email, "name": a.name or a.email},
                    "type": "optional" if a.optional else "required",
                }
                for a in payload.attendees
            ],
        }
        if payload.location:
            body["location"] = {"displayName": payload.location}
        if payload.create_conference:
            body["isOnlineMeeting"] = True
            body["onlineMeetingProvider"] = "teamsForBusiness"
        return body

    async def _request(self, method: str, url: str, access_token: str | None, **kwargs):
        if not access_token:
            raise ProviderNotConfigured(
                "Microsoft Calendar", hint="The user has not connected their Microsoft account."
            )
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method, url, headers={"Authorization": f"Bearer {access_token}"}, **kwargs
            )
        if response.status_code >= 400:
            logger.warning("microsoft_calendar_error", status=response.status_code)
            return CalendarSyncResult(
                status="FAILED",
                provider=self.provider_enum,
                detail=f"Microsoft Graph returned {response.status_code}",
            )
        return response.json() if response.content else {}

    async def create_event(
        self, payload: CalendarEventPayload, *, access_token: str | None = None
    ) -> CalendarSyncResult:
        result = await self._request(
            "POST", f"{self.API_BASE}/me/events", access_token, json=self._to_graph(payload)
        )
        if isinstance(result, CalendarSyncResult):
            return result
        link = (result.get("onlineMeeting") or {}).get("joinUrl") or payload.meeting_link
        return CalendarSyncResult(
            status="SYNCED",
            provider=self.provider_enum,
            external_event_id=result.get("id"),
            meeting_link=link,
        )

    async def update_event(
        self, external_event_id: str, payload: CalendarEventPayload, *, access_token: str | None = None
    ) -> CalendarSyncResult:
        result = await self._request(
            "PATCH",
            f"{self.API_BASE}/me/events/{external_event_id}",
            access_token,
            json=self._to_graph(payload),
        )
        if isinstance(result, CalendarSyncResult):
            return result
        return CalendarSyncResult(
            status="SYNCED",
            provider=self.provider_enum,
            external_event_id=external_event_id,
            meeting_link=(result.get("onlineMeeting") or {}).get("joinUrl"),
        )

    async def cancel_event(
        self, external_event_id: str, *, access_token: str | None = None
    ) -> CalendarSyncResult:
        result = await self._request(
            "DELETE", f"{self.API_BASE}/me/events/{external_event_id}", access_token
        )
        if isinstance(result, CalendarSyncResult):
            return result
        return CalendarSyncResult(status="SYNCED", provider=self.provider_enum)


@lru_cache(maxsize=1)
def get_calendar_provider() -> CalendarProvider:
    try:
        if settings.CALENDAR_PROVIDER == "google":
            return GoogleCalendarProvider()
        if settings.CALENDAR_PROVIDER == "microsoft":
            return MicrosoftCalendarProvider()
    except ProviderNotConfigured as exc:
        logger.warning("calendar_provider_unavailable", detail=exc.message)
    return UnconfiguredCalendarProvider()


def reset_calendar_provider() -> None:
    get_calendar_provider.cache_clear()
