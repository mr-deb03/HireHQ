"""Email service: template management, rendering, sending and thread tracking.

Every outbound message is persisted **before** transmission is attempted and updated
with the true outcome afterwards. A message whose transport did not deliver is stored as
``NOT_SENT_NO_PROVIDER`` or ``FAILED`` and reported that way through the API - the system
never implies an email reached a candidate when it did not (s69).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import (
    EmailDeliveryStatus,
    EmailDirection,
    EmailFolder,
    EmailTemplateKey,
)
from app.core.exceptions import ResourceNotFound, ValidationError
from app.core.logging import get_logger
from app.models.application import Application
from app.models.communication import EmailMessage, EmailTemplate, EmailThread
from app.modules.emails.templates import (
    DEFAULT_TEMPLATES,
    TEMPLATES_BY_KEY,
    TemplateRenderError,
    plain_text_preview,
    render_template,
    validate_template_source,
)
from app.providers.email import OutgoingEmail, get_email_provider
from app.utils.text import truncate

logger = get_logger(__name__)


class EmailService:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID) -> None:
        self.session = session
        self.company_id = company_id

    # ------------------------------------------------------------- templates
    async def ensure_default_templates(self) -> int:
        """Copy the platform's default templates into this company if absent.

        Each company owns its own copies so edits are tenant-local. Idempotent, so it is
        safe to call on company creation and again after a platform upgrade adds a key.
        """
        existing = set(
            (
                await self.session.execute(
                    select(EmailTemplate.template_key).where(
                        EmailTemplate.company_id == self.company_id
                    )
                )
            ).scalars()
        )
        created = 0
        for definition in DEFAULT_TEMPLATES:
            if definition.key in existing:
                continue
            self.session.add(
                EmailTemplate(
                    company_id=self.company_id,
                    template_key=definition.key,
                    name=definition.name,
                    subject=definition.subject,
                    body_html=definition.body_html,
                    body_text=plain_text_preview(definition.body_html),
                    available_variables=list(definition.variables),
                    is_system_default=True,
                    is_active=True,
                )
            )
            created += 1
        if created:
            await self.session.flush()
        return created

    async def get_template(self, key: EmailTemplateKey) -> EmailTemplate:
        template = await self.session.scalar(
            select(EmailTemplate).where(
                EmailTemplate.company_id == self.company_id,
                EmailTemplate.template_key == key,
            )
        )
        if template is None:
            # Self-heal rather than failing a candidate-facing email because a template
            # row is missing (e.g. a company created before this key existed).
            await self.ensure_default_templates()
            template = await self.session.scalar(
                select(EmailTemplate).where(
                    EmailTemplate.company_id == self.company_id,
                    EmailTemplate.template_key == key,
                )
            )
        if template is None:
            raise ResourceNotFound("Email template", key.value)
        return template

    async def list_templates(self) -> list[EmailTemplate]:
        result = await self.session.execute(
            select(EmailTemplate)
            .where(EmailTemplate.company_id == self.company_id)
            .order_by(EmailTemplate.name)
        )
        return list(result.scalars())

    async def update_template(
        self,
        key: EmailTemplateKey,
        *,
        subject: str | None = None,
        body_html: str | None = None,
        name: str | None = None,
        is_active: bool | None = None,
        updated_by_id: uuid.UUID | None = None,
    ) -> EmailTemplate:
        template = await self.get_template(key)

        for source, label in ((subject, "subject"), (body_html, "body")):
            if source is None:
                continue
            try:
                unknown = validate_template_source(source)
            except TemplateRenderError as exc:
                raise ValidationError(f"The {label} template is invalid: {exc}") from exc
            if unknown:
                raise ValidationError(
                    f"The {label} template uses unknown variables: {', '.join(unknown)}",
                    details={"unknown_variables": unknown, "allowed": sorted(
                        TEMPLATES_BY_KEY[key].variables
                    )},
                )

        if subject is not None:
            template.subject = subject
        if body_html is not None:
            template.body_html = body_html
            template.body_text = plain_text_preview(body_html)
        if name is not None:
            template.name = name
        if is_active is not None:
            template.is_active = is_active
        template.is_system_default = False
        template.updated_by_id = updated_by_id
        await self.session.flush()
        return template

    async def reset_template(self, key: EmailTemplateKey) -> EmailTemplate:
        template = await self.get_template(key)
        definition = TEMPLATES_BY_KEY[key]
        template.subject = definition.subject
        template.body_html = definition.body_html
        template.body_text = plain_text_preview(definition.body_html)
        template.name = definition.name
        template.is_system_default = True
        await self.session.flush()
        return template

    def preview(self, template: EmailTemplate, variables: dict[str, Any]) -> tuple[str, str]:
        return (
            render_template(template.subject, variables),
            render_template(template.body_html, variables),
        )

    # ---------------------------------------------------------------- sending
    async def send_templated(
        self,
        *,
        key: EmailTemplateKey,
        to: list[str],
        variables: dict[str, Any],
        application_id: uuid.UUID | None = None,
        candidate_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
        sent_by_id: uuid.UUID | None = None,
        is_automated: bool = False,
        cc: list[str] | None = None,
        reply_to: str | None = None,
    ) -> EmailMessage:
        template = await self.get_template(key)
        if not template.is_active:
            logger.info("email_template_disabled", template=key.value)
            return await self._record_message(
                subject=template.subject,
                body_html=template.body_html,
                to=to,
                cc=cc or [],
                status=EmailDeliveryStatus.FAILED,
                transport="none",
                failure_reason="The template is disabled for this company",
                template_id=template.id,
                application_id=application_id,
                candidate_id=candidate_id,
                job_id=job_id,
                sent_by_id=sent_by_id,
                is_automated=is_automated,
            )

        try:
            subject = render_template(template.subject, variables)
            body_html = render_template(template.body_html, variables)
        except TemplateRenderError as exc:
            logger.error("email_render_failed", template=key.value, error=str(exc))
            return await self._record_message(
                subject=truncate(template.subject, 300),
                body_html=template.body_html,
                to=to,
                cc=cc or [],
                status=EmailDeliveryStatus.FAILED,
                transport="none",
                failure_reason=f"Template render failed: {exc}",
                template_id=template.id,
                application_id=application_id,
                candidate_id=candidate_id,
                job_id=job_id,
                sent_by_id=sent_by_id,
                is_automated=is_automated,
            )

        return await self.send_raw(
            to=to,
            subject=subject,
            body_html=body_html,
            cc=cc,
            reply_to=reply_to,
            template_id=template.id,
            application_id=application_id,
            candidate_id=candidate_id,
            job_id=job_id,
            sent_by_id=sent_by_id,
            is_automated=is_automated,
        )

    async def send_raw(
        self,
        *,
        to: list[str],
        subject: str,
        body_html: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        template_id: uuid.UUID | None = None,
        application_id: uuid.UUID | None = None,
        candidate_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
        sent_by_id: uuid.UUID | None = None,
        is_automated: bool = False,
        thread_id: uuid.UUID | None = None,
    ) -> EmailMessage:
        recipients = [address.strip() for address in to if address and address.strip()]
        if not recipients:
            raise ValidationError("At least one recipient is required")

        provider = get_email_provider()
        result = await provider.send(
            OutgoingEmail(
                to=recipients,
                subject=subject,
                body_html=body_html,
                body_text=plain_text_preview(body_html),
                cc=cc or [],
                bcc=bcc or [],
                reply_to=reply_to,
            )
        )

        return await self._record_message(
            subject=subject,
            body_html=body_html,
            to=recipients,
            cc=cc or [],
            bcc=bcc or [],
            status=result.status,
            transport=result.transport,
            failure_reason=result.detail if not result.was_transmitted else None,
            external_message_id=result.message_id,
            template_id=template_id,
            application_id=application_id,
            candidate_id=candidate_id,
            job_id=job_id,
            sent_by_id=sent_by_id,
            is_automated=is_automated,
            thread_id=thread_id,
        )

    async def _record_message(
        self,
        *,
        subject: str,
        body_html: str,
        to: list[str],
        cc: list[str],
        status: EmailDeliveryStatus,
        transport: str,
        bcc: list[str] | None = None,
        failure_reason: str | None = None,
        external_message_id: str | None = None,
        template_id: uuid.UUID | None = None,
        application_id: uuid.UUID | None = None,
        candidate_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
        sent_by_id: uuid.UUID | None = None,
        is_automated: bool = False,
        thread_id: uuid.UUID | None = None,
    ) -> EmailMessage:
        if thread_id is None:
            thread = await self._resolve_thread(
                subject=subject,
                candidate_id=candidate_id,
                application_id=application_id,
                job_id=job_id,
            )
            thread_id = thread.id
        else:
            thread = await self.session.get(EmailThread, thread_id)

        message = EmailMessage(
            company_id=self.company_id,
            thread_id=thread_id,
            application_id=application_id,
            candidate_id=candidate_id,
            template_id=template_id,
            sent_by_id=sent_by_id,
            direction=EmailDirection.OUTBOUND,
            from_address=settings.EMAIL_FROM_ADDRESS,
            from_name=settings.EMAIL_FROM_NAME,
            to_addresses=to,
            cc_addresses=cc,
            bcc_addresses=bcc or [],
            subject=truncate(subject, 300),
            body_html=body_html,
            body_text=plain_text_preview(body_html),
            delivery_status=status,
            transport=transport,
            sent_at=datetime.now(UTC) if status == EmailDeliveryStatus.SENT else None,
            failure_reason=truncate(failure_reason, 500) if failure_reason else None,
            attempts=1,
            external_message_id=external_message_id,
            is_automated=is_automated,
        )
        self.session.add(message)

        if thread is not None:
            thread.message_count += 1
            thread.last_message_at = datetime.now(UTC)

        await self.session.flush()
        logger.info(
            "email_recorded",
            status=status.value,
            transport=transport,
            automated=is_automated,
            recipients=len(to),
        )
        return message

    async def _resolve_thread(
        self,
        *,
        subject: str,
        candidate_id: uuid.UUID | None,
        application_id: uuid.UUID | None,
        job_id: uuid.UUID | None,
    ) -> EmailThread:
        """Reuse the application's existing thread so a candidate's correspondence stays
        in one conversation instead of fragmenting per message."""
        if application_id is not None:
            existing = await self.session.scalar(
                select(EmailThread).where(
                    EmailThread.company_id == self.company_id,
                    EmailThread.application_id == application_id,
                )
            )
            if existing is not None:
                return existing

        thread = EmailThread(
            company_id=self.company_id,
            subject=truncate(subject, 300),
            candidate_id=candidate_id,
            application_id=application_id,
            job_id=job_id,
            folder=EmailFolder.SENT,
            last_message_at=datetime.now(UTC),
        )
        self.session.add(thread)
        await self.session.flush()
        return thread

    # ---------------------------------------------------------------- inbound
    async def record_inbound(
        self,
        *,
        from_address: str,
        to_addresses: list[str],
        subject: str,
        body_html: str | None,
        body_text: str | None,
        external_message_id: str | None = None,
        external_thread_id: str | None = None,
        account_id: uuid.UUID | None = None,
        received_at: datetime | None = None,
    ) -> EmailMessage:
        """Store an inbound message and attach it to the right candidate/application.

        Matching is by sender address against candidate records in this company; an
        unmatched message still lands in the inbox rather than being dropped.
        """
        from app.models.candidate import Candidate

        candidate = await self.session.scalar(
            select(Candidate).where(
                Candidate.company_id == self.company_id,
                Candidate.email == from_address.strip().lower(),
                Candidate.deleted_at.is_(None),
            )
        )
        application_id = None
        job_id = None
        if candidate is not None:
            application = await self.session.scalar(
                select(Application)
                .where(Application.candidate_id == candidate.id)
                .order_by(Application.created_at.desc())
                .limit(1)
            )
            if application is not None:
                application_id = application.id
                job_id = application.job_id

        thread: EmailThread | None = None
        if external_thread_id:
            thread = await self.session.scalar(
                select(EmailThread).where(
                    EmailThread.company_id == self.company_id,
                    EmailThread.external_thread_id == external_thread_id,
                )
            )
        if thread is None and application_id is not None:
            thread = await self.session.scalar(
                select(EmailThread).where(
                    EmailThread.company_id == self.company_id,
                    EmailThread.application_id == application_id,
                )
            )
        if thread is None:
            thread = EmailThread(
                company_id=self.company_id,
                subject=truncate(subject, 300),
                candidate_id=candidate.id if candidate else None,
                application_id=application_id,
                job_id=job_id,
                account_id=account_id,
                external_thread_id=external_thread_id,
                folder=EmailFolder.CANDIDATE_REPLIES if candidate else EmailFolder.INCOMING,
            )
            self.session.add(thread)
            await self.session.flush()

        thread.is_read = False
        thread.folder = EmailFolder.CANDIDATE_REPLIES if candidate else EmailFolder.INCOMING
        thread.message_count += 1
        thread.last_message_at = received_at or datetime.now(UTC)

        message = EmailMessage(
            company_id=self.company_id,
            thread_id=thread.id,
            application_id=application_id,
            candidate_id=candidate.id if candidate else None,
            direction=EmailDirection.INBOUND,
            from_address=from_address,
            to_addresses=to_addresses,
            subject=truncate(subject, 300),
            body_html=body_html,
            body_text=body_text,
            delivery_status=EmailDeliveryStatus.RECEIVED,
            transport="inbound",
            sent_at=received_at or datetime.now(UTC),
            external_message_id=external_message_id,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    # ---------------------------------------------------------------- context
    @staticmethod
    def build_variables(
        *,
        candidate: Any = None,
        job: Any = None,
        application: Any = None,
        company: Any = None,
        recruiter: Any = None,
        interview: Any = None,
        offer: Any = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble the allow-listed variable context from domain objects."""
        variables: dict[str, Any] = {"current_year": datetime.now(UTC).year}

        if candidate is not None:
            variables.update(
                candidate_name=candidate.full_name,
                candidate_first_name=candidate.first_name,
                candidate_email=candidate.email,
            )
        if job is not None:
            variables.update(
                job_title=job.title,
                job_location=job.location_text or "",
                job_reference=job.reference_code,
            )
        if company is not None:
            variables.update(
                company_name=company.name,
                company_website=company.website or "",
            )
        if recruiter is not None:
            variables.update(
                recruiter_name=recruiter.full_name,
                recruiter_email=recruiter.email,
            )
        if application is not None:
            variables.update(
                application_reference=application.reference_code,
                application_status=application.status.value.replace("_", " ").title(),
                application_url=(
                    f"{settings.FRONTEND_BASE_URL}/candidate/applications/{application.id}"
                ),
            )
        if interview is not None:
            local_start = interview.scheduled_start
            variables.update(
                interview_date=local_start.strftime("%A, %d %B %Y"),
                interview_time=local_start.strftime("%I:%M %p").lstrip("0"),
                interview_timezone=interview.timezone,
                interview_type=interview.interview_type.value.replace("_", " ").title(),
                interview_round=interview.round_name or f"Round {interview.round_number}",
                meeting_link=interview.meeting_link or "",
                interview_location=interview.location or "",
            )
        if offer is not None:
            variables.update(
                offer_position=offer.position_title,
                offer_salary=f"{offer.currency} {offer.base_salary:,.0f}",
                offer_expiry=(
                    offer.expires_at.strftime("%d %B %Y") if offer.expires_at else "not specified"
                ),
                joining_date=(
                    offer.joining_date.strftime("%d %B %Y") if offer.joining_date else "to be agreed"
                ),
                offer_url=f"{settings.FRONTEND_BASE_URL}/candidate/offers/{offer.id}",
            )

        variables.setdefault("portal_url", f"{settings.FRONTEND_BASE_URL}/candidate/dashboard")
        variables.setdefault("custom_message", "")
        if extra:
            variables.update(extra)
        return variables
