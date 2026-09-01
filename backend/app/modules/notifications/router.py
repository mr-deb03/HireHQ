"""Notification centre endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import NotificationType
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CurrentUser
from app.modules.notifications.service import NotificationService
from app.schemas.common import CountResponse, ORMModel, PaginationParams, pagination

router = APIRouter(prefix="/notifications", tags=["Notifications"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class NotificationOut(ORMModel):
    id: uuid.UUID
    notification_type: NotificationType
    title: str
    body: str | None = None
    action_url: str | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    is_read: bool
    read_at: datetime | None = None
    priority: str
    meta: dict = Field(default_factory=dict)
    created_at: datetime


class MarkReadRequest(BaseModel):
    notification_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class PreferencesUpdate(BaseModel):
    """Per-channel opt-in by notification type.

    Shape: ``{"NEW_APPLICATION": {"IN_APP": true, "EMAIL": false}, ...}``
    """

    preferences: dict[str, dict[str, bool]]


@router.get(
    "",
    response_model=SuccessResponse[Page[NotificationOut]],
    summary="List your notifications",
)
async def list_notifications(
    principal: CurrentUser,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    unread_only: Annotated[bool, Query()] = False,
) -> SuccessResponse[Page[NotificationOut]]:
    service = NotificationService(session)
    items, total = await service.list_for_user(
        principal.id,
        unread_only=unread_only,
        limit=page_params.page_size,
        offset=page_params.offset,
    )
    return SuccessResponse(
        data=Page.build(
            [NotificationOut.model_validate(n) for n in items],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


@router.get(
    "/unread-count",
    response_model=SuccessResponse[CountResponse],
    summary="Count unread notifications",
    description="Cheap enough to poll for the header badge.",
)
async def unread_count(
    principal: CurrentUser, session: DbSession
) -> SuccessResponse[CountResponse]:
    count = await NotificationService(session).unread_count(principal.id)
    return SuccessResponse(data=CountResponse(count=count))


@router.post(
    "/mark-read",
    response_model=SuccessResponse[CountResponse],
    summary="Mark notifications as read",
)
async def mark_read(
    payload: MarkReadRequest, principal: CurrentUser, session: DbSession
) -> SuccessResponse[CountResponse]:
    updated = await NotificationService(session).mark_read(
        principal.id, payload.notification_ids
    )
    return SuccessResponse(
        data=CountResponse(count=updated), message=f"{updated} marked as read"
    )


@router.post(
    "/mark-all-read",
    response_model=SuccessResponse[CountResponse],
    summary="Mark every notification as read",
)
async def mark_all_read(
    principal: CurrentUser, session: DbSession
) -> SuccessResponse[CountResponse]:
    updated = await NotificationService(session).mark_all_read(principal.id)
    return SuccessResponse(
        data=CountResponse(count=updated), message=f"{updated} marked as read"
    )


@router.get(
    "/preferences",
    response_model=SuccessResponse[dict],
    summary="Get your notification preferences",
)
async def get_preferences(principal: CurrentUser) -> SuccessResponse[dict]:
    from app.core.config import settings
    from app.core.enums import NotificationChannel

    # Report which channels the server can actually deliver on, so the UI does not offer
    # an SMS toggle on a deployment with no SMS provider.
    from app.providers.email import get_email_provider

    available = {
        NotificationChannel.IN_APP.value: True,
        NotificationChannel.EMAIL.value: get_email_provider().transmits,
        NotificationChannel.SMS.value: settings.SMS_PROVIDER != "none",
        NotificationChannel.WHATSAPP.value: settings.WHATSAPP_PROVIDER != "none",
    }
    return SuccessResponse(
        data={
            "preferences": principal.user.notification_preferences or {},
            "available_channels": available,
            "notification_types": [t.value for t in NotificationType],
        }
    )


@router.put(
    "/preferences",
    response_model=SuccessResponse[dict],
    summary="Update your notification preferences",
)
async def update_preferences(
    payload: PreferencesUpdate, principal: CurrentUser, session: DbSession
) -> SuccessResponse[dict]:
    from app.core.enums import NotificationChannel
    from app.core.exceptions import ValidationError

    valid_types = {t.value for t in NotificationType}
    valid_channels = {c.value for c in NotificationChannel}

    for notification_type, channels in payload.preferences.items():
        if notification_type not in valid_types:
            raise ValidationError(f"Unknown notification type '{notification_type}'")
        unknown = set(channels) - valid_channels
        if unknown:
            raise ValidationError(f"Unknown channels: {', '.join(sorted(unknown))}")

    principal.user.notification_preferences = payload.preferences
    await session.flush()
    return SuccessResponse(
        data={"preferences": payload.preferences}, message="Preferences updated"
    )
