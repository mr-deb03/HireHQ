"""Calendar accounts and events (internal source of truth + external sync state)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import IntegrationProvider
from app.db.base import Base, TenantMixin, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType, StringArray, UTCDateTime


class CalendarAccount(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """OAuth-connected Google / Microsoft calendar for one user."""

    __tablename__ = "calendar_accounts"
    __table_args__ = (
        Index("ix_calendar_accounts_user_provider", "user_id", "provider", unique=True),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[IntegrationProvider] = mapped_column(
        SAEnum(IntegrationProvider, native_enum=False, length=20), nullable=False
    )
    account_email: Mapped[str] = mapped_column(String(320), nullable=False)
    calendar_id: Mapped[str | None] = mapped_column(String(255))

    access_token_ref: Mapped[str | None] = mapped_column(String(512))
    refresh_token_ref: Mapped[str | None] = mapped_column(String(512))
    token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    scopes: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    sync_error: Mapped[str | None] = mapped_column(String(500))


class CalendarEvent(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """HireHQ's own event record.

    This is authoritative regardless of whether an external provider is connected. When
    one is, ``sync_status`` tracks the mirror; ``PENDING_NO_PROVIDER`` means the event
    exists in HireHQ only and no invitation was pushed anywhere.
    """

    __tablename__ = "calendar_events"
    __table_args__ = (
        Index("ix_calendar_events_company_start", "company_id", "start_at"),
        Index("ix_calendar_events_organiser_start", "organiser_id", "start_at"),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255))
    meeting_link: Mapped[str | None] = mapped_column(String(512))

    start_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    organiser_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    interview_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("interviews.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("calendar_accounts.id", ondelete="SET NULL")
    )

    provider: Mapped[IntegrationProvider | None] = mapped_column(
        SAEnum(IntegrationProvider, native_enum=False, length=20)
    )
    external_event_id: Mapped[str | None] = mapped_column(String(255), index=True)
    #: SYNCED | PENDING | FAILED | PENDING_NO_PROVIDER
    sync_status: Mapped[str] = mapped_column(
        String(30), default="PENDING_NO_PROVIDER", nullable=False, index=True
    )
    sync_error: Mapped[str | None] = mapped_column(String(500))
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    status: Mapped[str] = mapped_column(String(20), default="CONFIRMED", nullable=False)
    #: ``[{"email": ..., "name": ..., "type": "CANDIDATE|INTERVIEWER", "response": ...}]``
    attendees: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
