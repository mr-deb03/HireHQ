"""Email template management, sending and the recruitment inbox."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    EmailDeliveryStatus,
    EmailDirection,
    EmailFolder,
    EmailTemplateKey,
)
from app.core.exceptions import ResourceNotFound
from app.core.permissions import Perm
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.application import Application
from app.models.communication import EmailMessage, EmailThread
from app.models.company import Company
from app.modules.emails.service import EmailService
from app.modules.emails.templates import ALLOWED_VARIABLES
from app.providers.email import get_email_provider
from app.schemas.common import ORMModel, PaginationParams, pagination

router = APIRouter(prefix="/emails", tags=["Emails"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class TemplateOut(ORMModel):
    id: uuid.UUID
    template_key: EmailTemplateKey
    name: str
    subject: str
    body_html: str
    body_text: str | None = None
    available_variables: list[str] = Field(default_factory=list)
    is_active: bool
    is_system_default: bool
    updated_at: datetime


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    subject: str | None = Field(default=None, min_length=1, max_length=300)
    body_html: str | None = Field(default=None, min_length=1, max_length=100_000)
    is_active: bool | None = None


class PreviewRequest(BaseModel):
    variables: dict = Field(
        default_factory=dict, description="Sample values; unknown keys are ignored"
    )


class PreviewResponse(BaseModel):
    subject: str
    body_html: str


class SendEmailRequest(BaseModel):
    to: list[EmailStr] = Field(min_length=1, max_length=50)
    subject: str = Field(min_length=1, max_length=300)
    body_html: str = Field(min_length=1, max_length=100_000)
    cc: list[EmailStr] = Field(default_factory=list, max_length=20)
    application_id: uuid.UUID | None = None
    candidate_id: uuid.UUID | None = None


class SendTemplatedRequest(BaseModel):
    template_key: EmailTemplateKey
    application_id: uuid.UUID
    custom_message: str | None = Field(default=None, max_length=2000)


class MessageOut(ORMModel):
    id: uuid.UUID
    thread_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    candidate_id: uuid.UUID | None = None
    direction: EmailDirection
    from_address: str
    from_name: str | None = None
    to_addresses: list[str] = Field(default_factory=list)
    cc_addresses: list[str] = Field(default_factory=list)
    subject: str
    body_html: str | None = None
    body_text: str | None = None
    delivery_status: EmailDeliveryStatus
    #: Which transport handled it. ``console`` means nothing was transmitted.
    transport: str | None = None
    sent_at: datetime | None = None
    failure_reason: str | None = None
    is_automated: bool
    created_at: datetime


class ThreadOut(ORMModel):
    id: uuid.UUID
    subject: str
    candidate_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    folder: EmailFolder
    is_read: bool
    is_important: bool
    is_archived: bool
    message_count: int
    last_message_at: datetime | None = None
    created_at: datetime


class SendResult(BaseModel):
    message: MessageOut
    #: Explicitly true only when a transport actually delivered it.
    transmitted: bool
    note: str


class ProviderStatusOut(BaseModel):
    provider: str
    transmits: bool
    message: str


@router.get(
    "/provider-status",
    response_model=SuccessResponse[ProviderStatusOut],
    summary="Email provider status",
    description=(
        "Whether this server can actually deliver email. When it cannot, messages are "
        "still recorded and rendered, but reported as NOT_SENT_NO_PROVIDER."
    ),
    dependencies=[Depends(require_permission(Perm.EMAIL_READ))],
)
async def provider_status() -> SuccessResponse[ProviderStatusOut]:
    provider = get_email_provider()
    return SuccessResponse(
        data=ProviderStatusOut(
            provider=provider.name,
            transmits=provider.transmits,
            message=(
                f"Emails are delivered via {provider.name}."
                if provider.transmits
                else (
                    "No email provider is configured. Messages are composed and stored "
                    "but not delivered. Set EMAIL_PROVIDER=smtp and SMTP_HOST to send."
                )
            ),
        )
    )


# ------------------------------------------------------------------ templates
@router.get(
    "/templates",
    response_model=SuccessResponse[list[TemplateOut]],
    summary="List email templates",
    dependencies=[Depends(require_permission(Perm.EMAIL_READ))],
)
async def list_templates(
    company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[TemplateOut]]:
    service = EmailService(session, company_id)
    await service.ensure_default_templates()
    templates = await service.list_templates()
    return SuccessResponse(data=[TemplateOut.model_validate(t) for t in templates])


@router.get(
    "/templates/variables",
    response_model=SuccessResponse[list[str]],
    summary="Variables templates may use",
    description=(
        "Templates are rendered in a sandbox against this allow-list. Referencing "
        "anything else is rejected when the template is saved."
    ),
    dependencies=[Depends(require_permission(Perm.EMAIL_READ))],
)
async def template_variables() -> SuccessResponse[list[str]]:
    return SuccessResponse(data=sorted(ALLOWED_VARIABLES))


@router.get(
    "/templates/{template_key}",
    response_model=SuccessResponse[TemplateOut],
    summary="Get an email template",
    dependencies=[Depends(require_permission(Perm.EMAIL_READ))],
)
async def get_template(
    template_key: EmailTemplateKey, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[TemplateOut]:
    template = await EmailService(session, company_id).get_template(template_key)
    return SuccessResponse(data=TemplateOut.model_validate(template))


@router.patch(
    "/templates/{template_key}",
    response_model=SuccessResponse[TemplateOut],
    summary="Customise an email template",
    description="Rejects templates that reference variables outside the allow-list.",
    dependencies=[Depends(require_permission(Perm.EMAIL_TEMPLATE_MANAGE))],
)
async def update_template(
    template_key: EmailTemplateKey,
    payload: TemplateUpdate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[TemplateOut]:
    service = EmailService(session, company_id)
    template = await service.update_template(
        template_key,
        subject=payload.subject,
        body_html=payload.body_html,
        name=payload.name,
        is_active=payload.is_active,
        updated_by_id=principal.id,
    )
    return SuccessResponse(data=TemplateOut.model_validate(template), message="Template updated")


@router.post(
    "/templates/{template_key}/reset",
    response_model=SuccessResponse[TemplateOut],
    summary="Reset a template to the platform default",
    dependencies=[Depends(require_permission(Perm.EMAIL_TEMPLATE_MANAGE))],
)
async def reset_template(
    template_key: EmailTemplateKey, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[TemplateOut]:
    template = await EmailService(session, company_id).reset_template(template_key)
    return SuccessResponse(data=TemplateOut.model_validate(template), message="Template reset")


@router.post(
    "/templates/{template_key}/preview",
    response_model=SuccessResponse[PreviewResponse],
    summary="Preview a rendered template",
    dependencies=[Depends(require_permission(Perm.EMAIL_READ))],
)
async def preview_template(
    template_key: EmailTemplateKey,
    payload: PreviewRequest,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[PreviewResponse]:
    service = EmailService(session, company_id)
    template = await service.get_template(template_key)
    company = await session.get(Company, company_id)

    sample = {
        "candidate_name": "Rahul Sharma",
        "candidate_first_name": "Rahul",
        "job_title": "Senior React Developer",
        "company_name": company.name if company else "Your Company",
        "recruiter_name": "Priya Nair",
        "application_reference": "APP-7K2M4X",
        "interview_date": "Monday, 12 May 2025",
        "interview_time": "10:00 AM",
        "interview_timezone": "IST",
        "interview_round": "Technical Round 1",
        "meeting_link": "https://meet.example.com/hirehq-demo",
        "offer_position": "Senior React Developer",
        "joining_date": "01 June 2025",
        "offer_expiry": "20 May 2025",
        "current_year": datetime.now().year,
        **payload.variables,
    }
    subject, body = service.preview(template, sample)
    return SuccessResponse(data=PreviewResponse(subject=subject, body_html=body))


# -------------------------------------------------------------------- sending
@router.post(
    "/send",
    response_model=SuccessResponse[SendResult],
    summary="Send a one-off email",
    description="The response states plainly whether the message was actually transmitted.",
    dependencies=[Depends(require_permission(Perm.EMAIL_SEND))],
)
async def send_email(
    payload: SendEmailRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[SendResult]:
    service = EmailService(session, company_id)
    message = await service.send_raw(
        to=[str(e) for e in payload.to],
        subject=payload.subject,
        body_html=payload.body_html,
        cc=[str(e) for e in payload.cc],
        application_id=payload.application_id,
        candidate_id=payload.candidate_id,
        sent_by_id=principal.id,
    )
    transmitted = message.delivery_status == EmailDeliveryStatus.SENT
    return SuccessResponse(
        data=SendResult(
            message=MessageOut.model_validate(message),
            transmitted=transmitted,
            note=(
                "Delivered."
                if transmitted
                else (message.failure_reason or "The message was recorded but not sent.")
            ),
        ),
        message="Email sent" if transmitted else "Email recorded but not transmitted",
    )


@router.post(
    "/send-template",
    response_model=SuccessResponse[SendResult],
    summary="Send a templated email about an application",
    dependencies=[Depends(require_permission(Perm.EMAIL_SEND))],
)
async def send_templated(
    payload: SendTemplatedRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[SendResult]:
    from sqlalchemy.orm import selectinload

    application = (
        (
            await session.execute(
                select(Application)
                .where(
                    Application.id == payload.application_id,
                    Application.company_id == company_id,
                )
                .options(
                    selectinload(Application.candidate), selectinload(Application.job)
                )
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if application is None:
        raise ResourceNotFound("Application", payload.application_id)

    company = await session.get(Company, company_id)
    service = EmailService(session, company_id)
    variables = EmailService.build_variables(
        candidate=application.candidate,
        job=application.job,
        application=application,
        company=company,
        recruiter=principal.user,
        extra={"custom_message": payload.custom_message or ""},
    )
    message = await service.send_templated(
        key=payload.template_key,
        to=[application.candidate.email],
        variables=variables,
        application_id=application.id,
        candidate_id=application.candidate_id,
        job_id=application.job_id,
        sent_by_id=principal.id,
    )
    transmitted = message.delivery_status == EmailDeliveryStatus.SENT
    return SuccessResponse(
        data=SendResult(
            message=MessageOut.model_validate(message),
            transmitted=transmitted,
            note=(
                "Delivered."
                if transmitted
                else (message.failure_reason or "The message was recorded but not sent.")
            ),
        )
    )


# --------------------------------------------------------------------- inbox
@router.get(
    "/threads",
    response_model=SuccessResponse[Page[ThreadOut]],
    summary="Recruitment inbox",
    description="Email conversations grouped by candidate and application.",
    dependencies=[Depends(require_permission(Perm.EMAIL_READ))],
)
async def list_threads(
    company_id: CompanyScope,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    folder: EmailFolder | None = None,
    candidate_id: uuid.UUID | None = None,
    unread_only: Annotated[bool, Query()] = False,
) -> SuccessResponse[Page[ThreadOut]]:
    stmt = select(EmailThread).where(EmailThread.company_id == company_id)
    if folder:
        stmt = stmt.where(EmailThread.folder == folder)
    if candidate_id:
        stmt = stmt.where(EmailThread.candidate_id == candidate_id)
    if unread_only:
        stmt = stmt.where(EmailThread.is_read.is_(False))

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(EmailThread.last_message_at.desc().nullslast())
                .limit(page_params.page_size)
                .offset(page_params.offset)
            )
        )
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=Page.build(
            [ThreadOut.model_validate(t) for t in rows],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


@router.get(
    "/threads/{thread_id}",
    response_model=SuccessResponse[dict],
    summary="Get a thread and its messages",
    dependencies=[Depends(require_permission(Perm.EMAIL_READ))],
)
async def get_thread(
    thread_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[dict]:
    thread = await session.scalar(
        select(EmailThread).where(
            EmailThread.id == thread_id, EmailThread.company_id == company_id
        )
    )
    if thread is None:
        raise ResourceNotFound("Email thread", thread_id)

    thread.is_read = True
    messages = (
        (
            await session.execute(
                select(EmailMessage)
                .where(EmailMessage.thread_id == thread_id)
                .order_by(EmailMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    return SuccessResponse(
        data={
            "thread": ThreadOut.model_validate(thread).model_dump(),
            "messages": [MessageOut.model_validate(m).model_dump() for m in messages],
        }
    )


@router.get(
    "/messages",
    response_model=SuccessResponse[Page[MessageOut]],
    summary="List email messages",
    description=(
        "Filter by application, candidate or delivery status. Use "
        "`delivery_status=NOT_SENT_NO_PROVIDER` to find messages that were never sent."
    ),
    dependencies=[Depends(require_permission(Perm.EMAIL_READ))],
)
async def list_messages(
    company_id: CompanyScope,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    application_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    delivery_status: EmailDeliveryStatus | None = None,
    direction: EmailDirection | None = None,
) -> SuccessResponse[Page[MessageOut]]:
    stmt = select(EmailMessage).where(EmailMessage.company_id == company_id)
    if application_id:
        stmt = stmt.where(EmailMessage.application_id == application_id)
    if candidate_id:
        stmt = stmt.where(EmailMessage.candidate_id == candidate_id)
    if delivery_status:
        stmt = stmt.where(EmailMessage.delivery_status == delivery_status)
    if direction:
        stmt = stmt.where(EmailMessage.direction == direction)

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(EmailMessage.created_at.desc())
                .limit(page_params.page_size)
                .offset(page_params.offset)
            )
        )
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=Page.build(
            [MessageOut.model_validate(m) for m in rows],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )
