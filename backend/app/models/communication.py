"""Email templates, threads, messages, connected mailboxes and notifications."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    EmailDeliveryStatus,
    EmailDirection,
    EmailFolder,
    EmailTemplateKey,
    IntegrationProvider,
    NotificationChannel,
    NotificationType,
)
from app.db.base import Base, TenantMixin, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType, StringArray, UTCDateTime

if TYPE_CHECKING:
    pass


class EmailTemplate(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """A customisable message template.

    ``company_id`` is required; the platform ships a default set which is copied into
    each company on creation, so editing one company's template never affects another.
    """

    __tablename__ = "email_templates"
    __table_args__ = (
        Index("ix_email_templates_company_key", "company_id", "template_key", unique=True),
    )

    template_key: Mapped[EmailTemplateKey] = mapped_column(
        SAEnum(EmailTemplateKey, native_enum=False, length=40), nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text)
    #: Variables this template may reference, e.g. ``{{candidate_name}}``. Rendering is
    #: restricted to this allow-list so a template can never read arbitrary context.
    available_variables: Mapped[list[str]] = mapped_column(
        StringArray(), default=list, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: A system template has not been edited by the company yet.
    is_system_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )


class EmailAccount(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """A recruiter's connected mailbox (Gmail / Microsoft Graph) via OAuth.

    Only OAuth tokens are stored, never passwords. Refresh tokens are held encrypted at
    rest by the secret provider; this row keeps the ciphertext reference, not plaintext.
    """

    __tablename__ = "email_accounts"
    __table_args__ = (Index("ix_email_accounts_user_provider", "user_id", "provider", unique=True),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[IntegrationProvider] = mapped_column(
        SAEnum(IntegrationProvider, native_enum=False, length=20), nullable=False
    )
    email_address: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(150))

    access_token_ref: Mapped[str | None] = mapped_column(String(512))
    refresh_token_ref: Mapped[str | None] = mapped_column(String(512))
    token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    scopes: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    sync_cursor: Mapped[str | None] = mapped_column(String(255))
    sync_error: Mapped[str | None] = mapped_column(String(500))


class EmailThread(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """A conversation, linked to the candidate/application it concerns."""

    __tablename__ = "email_threads"
    __table_args__ = (
        Index("ix_email_threads_company_updated", "company_id", "last_message_at"),
        Index("ix_email_threads_candidate", "candidate_id"),
    )

    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("email_accounts.id", ondelete="SET NULL")
    )
    #: Provider-side conversation id, used to attach inbound replies to this thread.
    external_thread_id: Mapped[str | None] = mapped_column(String(255), index=True)

    folder: Mapped[EmailFolder] = mapped_column(
        SAEnum(EmailFolder, native_enum=False, length=30),
        default=EmailFolder.SENT,
        nullable=False,
        index=True,
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_important: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)

    messages: Mapped[list[EmailMessage]] = relationship(
        back_populates="thread",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="EmailMessage.created_at",
    )


class EmailMessage(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """A single email. Outbound rows record their true delivery outcome.

    ``NOT_SENT_NO_PROVIDER`` means the message was rendered and stored but no transport
    was configured - the API reports that honestly instead of implying delivery.
    """

    __tablename__ = "email_messages"
    __table_args__ = (
        Index("ix_email_messages_thread_created", "thread_id", "created_at"),
        Index("ix_email_messages_company_status", "company_id", "delivery_status"),
        Index("ix_email_messages_application", "application_id"),
    )

    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("email_threads.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("applications.id", ondelete="SET NULL"), index=True
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="SET NULL"), index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("email_templates.id", ondelete="SET NULL")
    )
    sent_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )

    direction: Mapped[EmailDirection] = mapped_column(
        SAEnum(EmailDirection, native_enum=False, length=20), nullable=False, index=True
    )
    from_address: Mapped[str] = mapped_column(String(320), nullable=False)
    from_name: Mapped[str | None] = mapped_column(String(150))
    to_addresses: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)
    cc_addresses: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)
    bcc_addresses: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)

    delivery_status: Mapped[EmailDeliveryStatus] = mapped_column(
        SAEnum(EmailDeliveryStatus, native_enum=False, length=30),
        default=EmailDeliveryStatus.QUEUED,
        nullable=False,
        index=True,
    )
    #: Which transport actually handled it, e.g. ``smtp`` or ``console``. Recorded so the
    #: UI can badge messages that were never transmitted.
    transport: Mapped[str | None] = mapped_column(String(30))
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    external_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    is_automated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attachments: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)

    thread: Mapped[EmailThread | None] = relationship(back_populates="messages", lazy="noload")


class Notification(Base, UUIDMixin, TimestampMixin):
    """An in-app (and optionally multi-channel) notification for one user."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read_created", "user_id", "is_read", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    notification_type: Mapped[NotificationType] = mapped_column(
        SAEnum(NotificationType, native_enum=False, length=40), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    #: Deep link into the frontend, e.g. ``/recruiter/candidates/<id>``.
    action_url: Mapped[str | None] = mapped_column(String(512))
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    priority: Mapped[str] = mapped_column(String(20), default="NORMAL", nullable=False)
    meta: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)


class NotificationDelivery(Base, UUIDMixin, TimestampMixin):
    """Per-channel delivery record, so an unconfigured SMS provider is visible as such
    rather than silently swallowed."""

    __tablename__ = "notification_deliveries"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        SAEnum(NotificationChannel, native_enum=False, length=20), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(40))
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failure_reason: Mapped[str | None] = mapped_column(String(500))
