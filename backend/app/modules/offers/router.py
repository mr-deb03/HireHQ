"""Offer management endpoints, plus the candidate-facing tokenised offer view."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OfferStatus
from app.core.permissions import Perm
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.company import Company
from app.models.offer import Offer
from app.modules.offers.service import OfferService, verify_offer_access_token
from app.schemas.common import ORMModel, PaginationParams, pagination

router = APIRouter(prefix="/offers", tags=["Offers"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class OfferCreate(BaseModel):
    application_id: uuid.UUID
    position_title: str = Field(min_length=1, max_length=200)
    base_salary: float = Field(gt=0)
    joining_date: date | None = None
    variable_pay: float | None = Field(default=None, ge=0)
    joining_bonus: float | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    salary_period: str = Field(default="YEARLY", pattern="^(YEARLY|MONTHLY|HOURLY)$")
    benefits: list[str] = Field(default_factory=list, max_length=25)
    department: str | None = Field(default=None, max_length=150)
    location: str | None = Field(default=None, max_length=255)
    employment_type: str | None = Field(default=None, max_length=30)
    probation_months: int | None = Field(default=None, ge=0, le=24)
    reporting_to: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)
    expires_in_days: int = Field(default=7, ge=1, le=90)


class OfferOut(ORMModel):
    id: uuid.UUID
    reference_code: str
    application_id: uuid.UUID
    candidate_id: uuid.UUID
    job_id: uuid.UUID
    position_title: str
    department: str | None = None
    location: str | None = None
    employment_type: str | None = None
    base_salary: float
    variable_pay: float | None = None
    joining_bonus: float | None = None
    total_compensation: float
    currency: str
    salary_period: str
    benefits: list[str] = Field(default_factory=list)
    joining_date: date | None = None
    probation_months: int | None = None
    reporting_to: str | None = None
    notes: str | None = None
    status: OfferStatus
    expires_at: datetime | None = None
    sent_at: datetime | None = None
    viewed_at: datetime | None = None
    responded_at: datetime | None = None
    decline_reason: str | None = None
    approved_at: datetime | None = None
    created_at: datetime


class SendOfferResponse(BaseModel):
    offer: OfferOut
    #: Reported truthfully - the offer email may not have been transmitted.
    email_delivery_status: str
    candidate_offer_url: str
    message: str


class OfferRespondRequest(BaseModel):
    accepted: bool
    decline_reason: str | None = Field(default=None, max_length=500)


class WithdrawRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


@router.get(
    "",
    response_model=SuccessResponse[Page[OfferOut]],
    summary="List offers",
    dependencies=[Depends(require_permission(Perm.OFFER_READ))],
)
async def list_offers(
    company_id: CompanyScope,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    offer_status: Annotated[list[OfferStatus] | None, Query(alias="status")] = None,
    job_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
) -> SuccessResponse[Page[OfferOut]]:
    stmt = select(Offer).where(Offer.company_id == company_id)
    if offer_status:
        stmt = stmt.where(Offer.status.in_(offer_status))
    if job_id:
        stmt = stmt.where(Offer.job_id == job_id)
    if candidate_id:
        stmt = stmt.where(Offer.candidate_id == candidate_id)

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(Offer.created_at.desc())
                .limit(page_params.page_size)
                .offset(page_params.offset)
            )
        )
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=Page.build(
            [OfferOut.model_validate(o) for o in rows],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


@router.post(
    "",
    response_model=SuccessResponse[OfferOut],
    status_code=status.HTTP_201_CREATED,
    summary="Draft an offer",
    dependencies=[Depends(require_permission(Perm.OFFER_CREATE))],
)
async def create_offer(
    payload: OfferCreate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[OfferOut]:
    service = OfferService(session, company_id)
    offer = await service.create(created_by_id=principal.id, **payload.model_dump())
    return SuccessResponse(
        data=OfferOut.model_validate(offer), message="Offer drafted"
    )


@router.get(
    "/{offer_id}",
    response_model=SuccessResponse[OfferOut],
    summary="Get an offer",
    dependencies=[Depends(require_permission(Perm.OFFER_READ))],
)
async def get_offer(
    offer_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[OfferOut]:
    offer = await OfferService(session, company_id).get(offer_id)
    return SuccessResponse(data=OfferOut.model_validate(offer))


@router.post(
    "/{offer_id}/approve",
    response_model=SuccessResponse[OfferOut],
    summary="Approve a draft offer",
    dependencies=[Depends(require_permission(Perm.OFFER_APPROVE))],
)
async def approve_offer(
    offer_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[OfferOut]:
    service = OfferService(session, company_id)
    offer = await service.get(offer_id)
    await service.approve(offer, approver_id=principal.id)
    return SuccessResponse(data=OfferOut.model_validate(offer), message="Offer approved")


@router.post(
    "/{offer_id}/send",
    response_model=SuccessResponse[SendOfferResponse],
    summary="Send an offer to the candidate",
    description=(
        "Emails a tokenised offer link and moves the application to OFFER. The response "
        "reports the true email delivery status."
    ),
    dependencies=[Depends(require_permission(Perm.OFFER_CREATE))],
)
async def send_offer(
    offer_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
    require_approval: Annotated[bool, Query()] = False,
) -> SuccessResponse[SendOfferResponse]:
    from app.core.config import settings
    from app.models.communication import EmailMessage

    service = OfferService(session, company_id)
    offer = await service.get(offer_id)
    offer, raw_token = await service.send(
        offer, actor_id=principal.id, require_approval=require_approval
    )
    await session.commit()
    await service.events.flush()

    latest_email = await session.scalar(
        select(EmailMessage)
        .where(EmailMessage.application_id == offer.application_id)
        .order_by(EmailMessage.created_at.desc())
        .limit(1)
    )
    delivery = latest_email.delivery_status.value if latest_email else "UNKNOWN"

    message = "Offer sent to the candidate"
    if delivery != "SENT":
        message = (
            "Offer recorded, but the email was not transmitted "
            f"({delivery}). Share the offer link with the candidate directly."
        )

    return SuccessResponse(
        data=SendOfferResponse(
            offer=OfferOut.model_validate(offer),
            email_delivery_status=delivery,
            candidate_offer_url=(
                f"{settings.FRONTEND_BASE_URL}/offers/{offer.id}?token={raw_token}"
            ),
            message=message,
        ),
        message=message,
    )


@router.post(
    "/{offer_id}/withdraw",
    response_model=SuccessResponse[OfferOut],
    summary="Withdraw an offer",
    dependencies=[Depends(require_permission(Perm.OFFER_CREATE))],
)
async def withdraw_offer(
    offer_id: uuid.UUID,
    payload: WithdrawRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[OfferOut]:
    service = OfferService(session, company_id)
    offer = await service.get(offer_id)
    await service.withdraw(offer, actor_id=principal.id, reason=payload.reason)
    return SuccessResponse(data=OfferOut.model_validate(offer), message="Offer withdrawn")


# ------------------------------------------------------- candidate-facing
public_router = APIRouter(prefix="/offers", tags=["Offers"])


@public_router.get(
    "/{offer_id}/view",
    response_model=SuccessResponse[dict],
    summary="View an offer with a token (candidate)",
    description=(
        "Lets a candidate open their offer from the emailed link without signing in. "
        "Returns only offer terms - no internal notes, scores or pipeline data."
    ),
)
async def view_offer_with_token(
    offer_id: uuid.UUID,
    token: Annotated[str, Query(description="Token from the offer email")],
    session: DbSession,
) -> SuccessResponse[dict]:
    # No company scope up front: the token is the authorisation, and the tenant is
    # derived from the offer it unlocks.
    offer = await verify_offer_access_token(session, offer_id, token)

    scoped = OfferService(session, offer.company_id)
    await scoped.mark_viewed(offer)
    company = await session.get(Company, offer.company_id)

    return SuccessResponse(
        data={
            "reference_code": offer.reference_code,
            "company_name": company.name if company else None,
            "company_logo_url": company.logo_url if company else None,
            "position_title": offer.position_title,
            "department": offer.department,
            "location": offer.location,
            "employment_type": offer.employment_type,
            "base_salary": float(offer.base_salary),
            "variable_pay": float(offer.variable_pay) if offer.variable_pay else None,
            "joining_bonus": float(offer.joining_bonus) if offer.joining_bonus else None,
            "total_compensation": offer.total_compensation,
            "currency": offer.currency,
            "salary_period": offer.salary_period,
            "benefits": offer.benefits,
            "joining_date": offer.joining_date.isoformat() if offer.joining_date else None,
            "probation_months": offer.probation_months,
            "reporting_to": offer.reporting_to,
            "notes": offer.notes,
            "status": offer.status.value,
            "expires_at": offer.expires_at.isoformat() if offer.expires_at else None,
            "can_respond": offer.status in (OfferStatus.SENT, OfferStatus.VIEWED),
        }
    )


@public_router.post(
    "/{offer_id}/respond",
    response_model=SuccessResponse[dict],
    summary="Accept or decline an offer (candidate)",
    description=(
        "Accepting starts onboarding automatically and moves the application to "
        "OFFER_ACCEPTED."
    ),
)
async def respond_to_offer(
    offer_id: uuid.UUID,
    payload: OfferRespondRequest,
    token: Annotated[str, Query(description="Token from the offer email")],
    session: DbSession,
) -> SuccessResponse[dict]:
    offer = await verify_offer_access_token(session, offer_id, token)

    scoped = OfferService(session, offer.company_id)
    await scoped.respond(
        offer, accepted=payload.accepted, decline_reason=payload.decline_reason
    )
    await session.commit()
    await scoped.events.flush()

    return SuccessResponse(
        data={
            "reference_code": offer.reference_code,
            "status": offer.status.value,
            "onboarding_started": payload.accepted,
        },
        message=(
            "Congratulations - your offer is accepted. The team will be in touch about "
            "onboarding."
            if payload.accepted
            else "Your response has been recorded. Thank you for letting us know."
        ),
    )
