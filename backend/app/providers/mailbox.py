"""Mailbox provider abstraction for the recruitment inbox.

Reads recent messages from a recruiter's connected mailbox so candidate replies land
against the right application. Gmail and Microsoft Graph are implemented; when no
mailbox is connected the inbox simply shows the outbound messages HireHQ itself
recorded, which the UI states plainly rather than implying a sync happened.

Only OAuth tokens are ever used - HireHQ never asks for or stores a mailbox password.
"""

from __future__ import annotations

import base64
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from app.core.enums import IntegrationProvider
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Bound on a single sync pass, so a long-dormant mailbox cannot stall the worker.
MAX_MESSAGES_PER_SYNC = 50


@dataclass(slots=True)
class InboundMessage:
    external_id: str
    thread_id: str | None
    from_address: str
    from_name: str | None
    to_addresses: list[str]
    subject: str
    body_text: str | None
    body_html: str | None
    received_at: datetime
    labels: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SyncResult:
    messages: list[InboundMessage]
    #: Opaque provider cursor to resume from next time.
    cursor: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


_ADDRESS_RE = re.compile(r"(?:\"?([^\"<]*)\"?\s*)?<?([^\s<>]+@[^\s<>]+)>?")


def _parse_address(value: str) -> tuple[str | None, str]:
    """Split ``Name <a@b.com>`` into its parts, tolerating the many shapes it takes."""
    match = _ADDRESS_RE.search(value or "")
    if not match:
        return None, (value or "").strip()
    name = (match.group(1) or "").strip() or None
    return name, match.group(2).strip().lower()


class MailboxProvider(ABC):
    name: str = "abstract"
    can_sync: bool = False

    @abstractmethod
    async def fetch_recent(
        self, *, access_token: str, cursor: str | None = None
    ) -> SyncResult: ...


class UnconfiguredMailboxProvider(MailboxProvider):
    """Used when no mailbox is connected. Performs no work and says so."""

    name = "none"
    can_sync = False

    async def fetch_recent(
        self, *, access_token: str, cursor: str | None = None
    ) -> SyncResult:
        return SyncResult(
            messages=[],
            error=(
                "No mailbox is connected. The inbox shows messages HireHQ sent; incoming "
                "replies are not being synced."
            ),
        )


class GmailProvider(MailboxProvider):
    """Gmail via the Gmail API, using a user's OAuth access token."""

    name = "google"
    can_sync = True
    API = "https://gmail.googleapis.com/gmail/v1/users/me"

    async def fetch_recent(
        self, *, access_token: str, cursor: str | None = None
    ) -> SyncResult:
        headers = {"Authorization": f"Bearer {access_token}"}
        # `historyId` gives an incremental feed once we have synced at least once;
        # the first pass falls back to a bounded list of recent inbox messages.
        params: dict[str, str | int] = {"maxResults": MAX_MESSAGES_PER_SYNC}
        if cursor:
            params["q"] = f"after:{cursor}"
        params["labelIds"] = "INBOX"

        try:
            async with httpx.AsyncClient(timeout=45) as client:
                listing = await client.get(
                    f"{self.API}/messages", headers=headers, params=params
                )
                if listing.status_code >= 400:
                    return SyncResult([], error=f"Gmail list failed ({listing.status_code})")

                ids = [m["id"] for m in (listing.json().get("messages") or [])]
                messages: list[InboundMessage] = []
                for message_id in ids[:MAX_MESSAGES_PER_SYNC]:
                    detail = await client.get(
                        f"{self.API}/messages/{message_id}",
                        headers=headers,
                        params={"format": "full"},
                    )
                    if detail.status_code >= 400:
                        continue
                    parsed = self._to_message(detail.json())
                    if parsed:
                        messages.append(parsed)
        except Exception as exc:
            return SyncResult([], error=f"Gmail sync failed: {exc}"[:500])

        newest = max((m.received_at for m in messages), default=None)
        return SyncResult(
            messages=messages,
            cursor=str(int(newest.timestamp())) if newest else cursor,
        )

    def _to_message(self, payload: dict) -> InboundMessage | None:
        headers = {
            h["name"].lower(): h["value"]
            for h in payload.get("payload", {}).get("headers", [])
        }
        from_raw = headers.get("from")
        if not from_raw:
            return None
        name, address = _parse_address(from_raw)

        text, html = self._extract_body(payload.get("payload", {}))
        received_ms = int(payload.get("internalDate", "0") or 0)

        return InboundMessage(
            external_id=payload["id"],
            thread_id=payload.get("threadId"),
            from_address=address,
            from_name=name,
            to_addresses=[
                _parse_address(part)[1]
                for part in (headers.get("to", "").split(",") if headers.get("to") else [])
                if part.strip()
            ],
            subject=headers.get("subject", "(no subject)"),
            body_text=text,
            body_html=html,
            received_at=datetime.fromtimestamp(received_ms / 1000, tz=UTC),
            labels=payload.get("labelIds", []),
        )

    def _extract_body(self, part: dict) -> tuple[str | None, str | None]:
        """Walk the MIME tree for the text and HTML alternatives."""
        text: str | None = None
        html: str | None = None

        def decode(data: str) -> str:
            return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8", errors="replace"
            )

        def walk(node: dict) -> None:
            nonlocal text, html
            mime = node.get("mimeType", "")
            data = node.get("body", {}).get("data")
            if data:
                if mime == "text/plain" and text is None:
                    text = decode(data)
                elif mime == "text/html" and html is None:
                    html = decode(data)
            for child in node.get("parts", []) or []:
                walk(child)

        walk(part)
        return text, html


class MicrosoftMailProvider(MailboxProvider):
    """Outlook / Microsoft 365 mail via Microsoft Graph."""

    name = "microsoft"
    can_sync = True
    API = "https://graph.microsoft.com/v1.0/me"

    async def fetch_recent(
        self, *, access_token: str, cursor: str | None = None
    ) -> SyncResult:
        headers = {"Authorization": f"Bearer {access_token}"}
        params: dict[str, str | int] = {
            "$top": MAX_MESSAGES_PER_SYNC,
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,from,toRecipients,subject,body,receivedDateTime",
        }
        if cursor:
            params["$filter"] = f"receivedDateTime gt {cursor}"

        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.get(
                    f"{self.API}/mailFolders/inbox/messages", headers=headers, params=params
                )
            if response.status_code >= 400:
                return SyncResult([], error=f"Graph list failed ({response.status_code})")
            items = response.json().get("value", [])
        except Exception as exc:
            return SyncResult([], error=f"Microsoft mail sync failed: {exc}"[:500])

        messages: list[InboundMessage] = []
        for item in items:
            sender = (item.get("from") or {}).get("emailAddress") or {}
            address = (sender.get("address") or "").lower()
            if not address:
                continue
            body = item.get("body") or {}
            is_html = (body.get("contentType") or "").lower() == "html"
            messages.append(
                InboundMessage(
                    external_id=item["id"],
                    thread_id=item.get("conversationId"),
                    from_address=address,
                    from_name=sender.get("name"),
                    to_addresses=[
                        (r.get("emailAddress") or {}).get("address", "").lower()
                        for r in item.get("toRecipients", [])
                    ],
                    subject=item.get("subject") or "(no subject)",
                    body_text=None if is_html else body.get("content"),
                    body_html=body.get("content") if is_html else None,
                    received_at=datetime.fromisoformat(
                        item["receivedDateTime"].replace("Z", "+00:00")
                    ),
                )
            )

        newest = max((m.received_at for m in messages), default=None)
        return SyncResult(
            messages=messages,
            cursor=newest.isoformat().replace("+00:00", "Z") if newest else cursor,
        )


def get_mailbox_provider(provider: IntegrationProvider | None) -> MailboxProvider:
    if provider == IntegrationProvider.GOOGLE:
        return GmailProvider()
    if provider == IntegrationProvider.MICROSOFT:
        return MicrosoftMailProvider()
    return UnconfiguredMailboxProvider()
