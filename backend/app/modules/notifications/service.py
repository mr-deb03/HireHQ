"""Notification centre.

In-app notifications are created synchronously. Other channels (email, SMS, WhatsApp) go
through provider abstractions and record a per-channel delivery row, so an unconfigured
SMS provider is visible as ``NOT_CONFIGURED`` rather than silently dropping the message.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import NotificationChannel, NotificationType, RoleName
from app.core.logging import get_logger
from app.models.communication import Notification, NotificationDelivery
from app.models.user import User
from app.services.events import DomainEvent, Events
from app.utils.text import truncate

logger = get_logger(__name__)

#: Which event produces which notification, for whom, and what it says.
#: ``audience`` is resolved by ``_resolve_recipients``.
_EVENT_MAP: dict[str, dict] = {
    Events.APPLICATION_CREATED: {
        "type": NotificationType.NEW_APPLICATION,
        "audience": "job_team",
        "title": "New application received",
        "template": "{candidate_name} applied for {job_title}",
        "url": "/recruiter/jobs/{job_id}/applications",
    },
    Events.ATS_SCORE_GENERATED: {
        "type": NotificationType.ATS_COMPLETED,
        "audience": "job_team",
        "title": "ATS analysis complete",
        "template": "{candidate_name} scored {score}% for {job_title}",
        "url": "/recruiter/candidates/{candidate_id}",
        #: Only notify when the score is worth a recruiter's attention, otherwise every
        #: application would produce two notifications and the centre becomes noise.
        "min_score": 70,
    },
    Events.INTERVIEW_SCHEDULED: {
        "type": NotificationType.INTERVIEW_SCHEDULED,
        "audience": "interviewers",
        "title": "You have been assigned an interview",
        "template": "{interview_title} with {candidate_name}",
        "url": "/interviewer/interviews",
    },
    Events.FEEDBACK_SUBMITTED: {
        "type": NotificationType.FEEDBACK_PENDING,
        "audience": "job_team",
        "title": "Interview feedback submitted",
        "template": "{interviewer_name} submitted feedback for {candidate_name}",
        "url": "/recruiter/candidates/{candidate_id}",
    },
    Events.OFFER_ACCEPTED: {
        "type": NotificationType.OFFER_ACCEPTED,
        "audience": "job_team",
        "title": "Offer accepted",
        "template": "{candidate_name} accepted the offer for {job_title}",
        "url": "/recruiter/offers",
        "priority": "HIGH",
    },
    Events.OFFER_REJECTED: {
        "type": NotificationType.OFFER_REJECTED,
        "audience": "job_team",
        "title": "Offer declined",
        "template": "{candidate_name} declined the offer for {job_title}",
        "url": "/recruiter/offers",
        "priority": "HIGH",
    },
    Events.ASSESSMENT_SUBMITTED: {
        "type": NotificationType.ASSESSMENT_SUBMITTED,
        "audience": "job_team",
        "title": "Assessment submitted",
        "template": "{candidate_name} submitted {assessment_name}",
        "url": "/recruiter/candidates/{candidate_id}",
    },
    Events.EMAIL_RECEIVED: {
        "type": NotificationType.NEW_CANDIDATE_REPLY,
        "audience": "job_team",
        "title": "New candidate reply",
        "template": "{candidate_name} replied to your email",
        "url": "/recruiter/emails",
    },
}


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------- creation
    async def create(
        self,
        *,
        user_id: uuid.UUID,
        notification_type: NotificationType,
        title: str,
        body: str | None = None,
        company_id: uuid.UUID | None = None,
        action_url: str | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        priority: str = "NORMAL",
        meta: dict | None = None,
        channels: Sequence[NotificationChannel] = (NotificationChannel.IN_APP,),
    ) -> Notification:
        notification = Notification(
            user_id=user_id,
            company_id=company_id,
            notification_type=notification_type,
            title=truncate(title, 255),
            body=truncate(body, 1000) if body else None,
            action_url=action_url,
            entity_type=entity_type,
            entity_id=entity_id,
            priority=priority,
            meta=meta or {},
        )
        self.session.add(notification)
        await self.session.flush()

        for channel in channels:
            await self._deliver(notification, channel)
        return notification

    async def create_many(
        self,
        *,
        user_ids: Sequence[uuid.UUID],
        notification_type: NotificationType,
        title: str,
        **kwargs,
    ) -> list[Notification]:
        return [
            await self.create(
                user_id=user_id, notification_type=notification_type, title=title, **kwargs
            )
            for user_id in dict.fromkeys(user_ids)
        ]

    async def _deliver(
        self, notification: Notification, channel: NotificationChannel
    ) -> NotificationDelivery:
        """Record a per-channel outcome, telling the truth about unconfigured providers."""
        status = "DELIVERED"
        provider = "in_app"
        failure: str | None = None

        if channel == NotificationChannel.IN_APP:
            status, provider = "DELIVERED", "in_app"
        elif channel == NotificationChannel.EMAIL:
            from app.providers.email import get_email_provider

            email_provider = get_email_provider()
            provider = email_provider.name
            if not email_provider.transmits:
                status = "NOT_CONFIGURED"
                failure = "No email provider is configured; nothing was transmitted."
            else:
                status = "QUEUED"
        elif channel == NotificationChannel.SMS:
            provider = settings.SMS_PROVIDER
            if settings.SMS_PROVIDER == "none":
                status = "NOT_CONFIGURED"
                failure = "No SMS provider is configured on this server."
            else:
                status = "QUEUED"
        elif channel == NotificationChannel.WHATSAPP:
            provider = settings.WHATSAPP_PROVIDER
            if settings.WHATSAPP_PROVIDER == "none":
                status = "NOT_CONFIGURED"
                failure = "No WhatsApp provider is configured on this server."
            else:
                status = "QUEUED"

        delivery = NotificationDelivery(
            notification_id=notification.id,
            channel=channel,
            status=status,
            provider=provider,
            delivered_at=datetime.now(UTC) if status == "DELIVERED" else None,
            failure_reason=failure,
        )
        self.session.add(delivery)
        return delivery

    # --------------------------------------------------------------- reading
    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        unread_only: bool = False,
        limit: int = 30,
        offset: int = 0,
    ) -> tuple[list[Notification], int]:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))

        total = (
            await self.session.execute(
                select(func.count()).select_from(stmt.order_by(None).subquery())
            )
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def unread_count(self, user_id: uuid.UUID) -> int:
        return (
            await self.session.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            )
        ).scalar_one()

    async def mark_read(self, user_id: uuid.UUID, notification_ids: Sequence[uuid.UUID]) -> int:
        if not notification_ids:
            return 0
        result = await self.session.execute(
            update(Notification)
            .where(
                Notification.id.in_(notification_ids),
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True, read_at=datetime.now(UTC))
        )
        return result.rowcount or 0

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        result = await self.session.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True, read_at=datetime.now(UTC))
        )
        return result.rowcount or 0

    # ---------------------------------------------------------------- events
    async def handle_event(self, event: DomainEvent) -> None:
        rule = _EVENT_MAP.get(event.name)
        if rule is None:
            return

        minimum = rule.get("min_score")
        if minimum is not None:
            score = event.payload.get("score")
            if score is None or float(score) < minimum:
                return

        recipients = await self._resolve_recipients(event, rule["audience"])
        if not recipients:
            return

        payload = {k: ("" if v is None else v) for k, v in event.payload.items()}
        try:
            body = rule["template"].format(**payload)
        except KeyError as exc:
            logger.warning(
                "notification_template_missing_key",
                event_name=event.name,
                key=str(exc),
            )
            body = rule["title"]

        action_url = rule.get("url", "")
        for key, value in payload.items():
            action_url = action_url.replace(f"{{{key}}}", str(value))
        if "{" in action_url:
            action_url = ""

        await self.create_many(
            user_ids=recipients,
            notification_type=rule["type"],
            title=rule["title"],
            body=body,
            company_id=event.company_id,
            action_url=action_url or None,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            priority=rule.get("priority", "NORMAL"),
            meta={"event": event.name},
        )

    async def _resolve_recipients(self, event: DomainEvent, audience: str) -> list[uuid.UUID]:
        """Work out who should hear about this, without ever crossing a tenant boundary."""
        if event.company_id is None:
            return []

        if audience == "interviewers":
            ids = event.payload.get("interviewer_ids") or []
            return [uuid.UUID(str(i)) for i in ids]

        if audience == "job_team":
            recipients: list[uuid.UUID] = []
            # The people actually assigned to this job come first.
            job_id = event.payload.get("job_id")
            if job_id:
                from app.models.job import Job, JobHiringTeamMember

                team = (
                    (
                        await self.session.execute(
                            select(JobHiringTeamMember.user_id).where(
                                JobHiringTeamMember.job_id == uuid.UUID(str(job_id))
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                recipients.extend(team)

                job = await self.session.get(Job, uuid.UUID(str(job_id)))
                if job is not None:
                    if job.created_by_id:
                        recipients.append(job.created_by_id)
                    if job.hiring_manager_id:
                        recipients.append(job.hiring_manager_id)

            if assignee := event.payload.get("assigned_recruiter_id"):
                recipients.append(uuid.UUID(str(assignee)))

            if not recipients:
                # Fall back to every recruiter in the company so nothing goes unseen.
                recipients = await self._company_recruiters(event.company_id)

            # Never notify the person who caused the event about their own action.
            return [r for r in dict.fromkeys(recipients) if r != event.actor_id]

        return []

    async def _company_recruiters(self, company_id: uuid.UUID) -> list[uuid.UUID]:
        from app.models.user import Role, UserRole

        stmt = (
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                User.company_id == company_id,
                User.deleted_at.is_(None),
                Role.name.in_([RoleName.RECRUITER.value, RoleName.COMPANY_ADMIN.value]),
            )
            .limit(25)
        )
        return list((await self.session.execute(stmt)).scalars().all())
