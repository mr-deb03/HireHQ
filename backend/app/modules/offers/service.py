"""Offer lifecycle and the handoff into onboarding."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.enums import (
    ApplicationStatus,
    AuditAction,
    EmailTemplateKey,
    OfferStatus,
    OnboardingStatus,
)
from app.core.exceptions import BusinessRuleError, ResourceNotFound, ValidationError
from app.core.logging import get_logger
from app.core.security import generate_url_token, hash_url_token
from app.models.application import Application
from app.models.company import Company
from app.models.offer import Offer, Onboarding, OnboardingTask
from app.models.user import User
from app.services.audit import AuditService
from app.services.events import DomainEvent, EventCollector, Events
from app.utils.text import truncate

logger = get_logger(__name__)

#: Statuses from which an offer can still be acted on by the candidate.
_LIVE_OFFER_STATUSES = frozenset({OfferStatus.SENT, OfferStatus.VIEWED})

DEFAULT_ONBOARDING_TASKS: tuple[dict, ...] = (
    {"title": "Upload government ID", "category": "DOCUMENT", "owner_type": "CANDIDATE"},
    {"title": "Upload education certificates", "category": "DOCUMENT", "owner_type": "CANDIDATE"},
    {
        "title": "Upload previous employment letters",
        "category": "DOCUMENT",
        "owner_type": "CANDIDATE",
    },
    {"title": "Submit bank details for payroll", "category": "HR", "owner_type": "CANDIDATE"},
    {"title": "Sign the employment agreement", "category": "HR", "owner_type": "CANDIDATE"},
    {"title": "Background verification", "category": "VERIFICATION", "owner_type": "COMPANY"},
    {"title": "Create accounts and access", "category": "IT_SETUP", "owner_type": "COMPANY"},
    {"title": "Assign equipment", "category": "IT_SETUP", "owner_type": "COMPANY"},
    {"title": "Schedule day-one induction", "category": "HR", "owner_type": "COMPANY"},
)


def generate_offer_reference() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return f"OFR-{datetime.now(UTC).year}-{''.join(secrets.choice(alphabet) for _ in range(5))}"


class OfferService:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID) -> None:
        self.session = session
        self.company_id = company_id
        self.audit = AuditService(session)
        self.events = EventCollector()

    async def get(self, offer_id: uuid.UUID) -> Offer:
        offer = await self.session.scalar(
            select(Offer).where(Offer.id == offer_id, Offer.company_id == self.company_id)
        )
        if offer is None:
            raise ResourceNotFound("Offer", offer_id)
        return offer

    async def create(
        self,
        *,
        application_id: uuid.UUID,
        position_title: str,
        base_salary: float,
        created_by_id: uuid.UUID,
        joining_date: date | None = None,
        variable_pay: float | None = None,
        joining_bonus: float | None = None,
        currency: str = "INR",
        salary_period: str = "YEARLY",
        benefits: list[str] | None = None,
        department: str | None = None,
        location: str | None = None,
        employment_type: str | None = None,
        probation_months: int | None = None,
        reporting_to: str | None = None,
        notes: str | None = None,
        expires_in_days: int = 7,
    ) -> Offer:
        application = (
            (
                await self.session.execute(
                    select(Application)
                    .where(
                        Application.id == application_id,
                        Application.company_id == self.company_id,
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
            raise ResourceNotFound("Application", application_id)
        if application.status in (
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
            ApplicationStatus.HIRED,
        ):
            raise BusinessRuleError(
                f"Cannot create an offer for a {application.status.value.lower()} application"
            )
        if base_salary <= 0:
            raise ValidationError("The base salary must be greater than zero")
        if joining_date and joining_date < date.today():
            raise ValidationError("The joining date cannot be in the past")

        existing = await self.session.scalar(
            select(Offer).where(
                Offer.application_id == application_id,
                Offer.status.in_([*_LIVE_OFFER_STATUSES, OfferStatus.DRAFT, OfferStatus.ACCEPTED]),
            )
        )
        if existing is not None:
            raise BusinessRuleError(
                f"This application already has a {existing.status.value.lower()} offer",
                code="OFFER_ALREADY_EXISTS",
                details={"offer_id": str(existing.id)},
            )

        offer = Offer(
            company_id=self.company_id,
            application_id=application.id,
            candidate_id=application.candidate_id,
            job_id=application.job_id,
            reference_code=generate_offer_reference(),
            position_title=position_title,
            department=department,
            location=location,
            employment_type=employment_type,
            base_salary=base_salary,
            variable_pay=variable_pay,
            joining_bonus=joining_bonus,
            currency=currency.upper(),
            salary_period=salary_period,
            benefits=benefits or [],
            joining_date=joining_date,
            probation_months=probation_months,
            reporting_to=reporting_to,
            notes=notes,
            status=OfferStatus.DRAFT,
            expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
            created_by_id=created_by_id,
        )
        self.session.add(offer)
        await self.session.flush()

        await self.audit.record(
            action=AuditAction.CREATE,
            entity_type="Offer",
            entity_id=offer.id,
            company_id=self.company_id,
            actor_id=created_by_id,
            summary=(
                f"Drafted offer {offer.reference_code} for "
                f"{application.candidate.full_name} - {position_title}"
            ),
        )
        logger.info("offer_created", offer_id=str(offer.id))
        return offer

    async def approve(self, offer: Offer, *, approver_id: uuid.UUID) -> Offer:
        if offer.status != OfferStatus.DRAFT:
            raise BusinessRuleError("Only a draft offer can be approved")
        offer.approved_by_id = approver_id
        offer.approved_at = datetime.now(UTC)
        await self.audit.record(
            action=AuditAction.UPDATE,
            entity_type="Offer",
            entity_id=offer.id,
            company_id=self.company_id,
            actor_id=approver_id,
            summary=f"Approved offer {offer.reference_code}",
        )
        await self.session.flush()
        return offer

    async def send(
        self, offer: Offer, *, actor_id: uuid.UUID, require_approval: bool = False
    ) -> tuple[Offer, str]:
        """Send an offer to the candidate. Returns ``(offer, raw_access_token)``."""
        if offer.status not in (OfferStatus.DRAFT,):
            raise BusinessRuleError(
                f"An offer with status {offer.status.value} cannot be sent"
            )
        if require_approval and offer.approved_at is None:
            raise BusinessRuleError(
                "This offer must be approved before it is sent",
                code="OFFER_APPROVAL_REQUIRED",
            )

        raw_token = generate_url_token()
        offer.access_token_hash = hash_url_token(raw_token)
        offer.status = OfferStatus.SENT
        offer.sent_at = datetime.now(UTC)
        await self.session.flush()

        application = (
            (
                await self.session.execute(
                    select(Application)
                    .where(Application.id == offer.application_id)
                    .options(
                        selectinload(Application.candidate), selectinload(Application.job)
                    )
                )
            )
            .unique()
            .scalar_one()
        )
        company = await self.session.get(Company, self.company_id)
        recruiter = await self.session.get(User, actor_id)

        from app.modules.emails.service import EmailService

        email_service = EmailService(self.session, self.company_id)
        variables = EmailService.build_variables(
            candidate=application.candidate,
            job=application.job,
            application=application,
            company=company,
            recruiter=recruiter,
            offer=offer,
            extra={
                "offer_url": (
                    f"{settings.FRONTEND_BASE_URL}/offers/{offer.id}?token={raw_token}"
                )
            },
        )
        message = await email_service.send_templated(
            key=EmailTemplateKey.OFFER,
            to=[application.candidate.email],
            variables=variables,
            application_id=application.id,
            candidate_id=application.candidate_id,
            job_id=application.job_id,
            sent_by_id=actor_id,
        )

        from app.modules.applications.service import ApplicationPipelineService

        pipeline = ApplicationPipelineService(self.session, self.company_id)
        if application.status != ApplicationStatus.OFFER:
            try:
                await pipeline.change_status(
                    application,
                    new_status=ApplicationStatus.OFFER,
                    actor_id=actor_id,
                    reason=f"Offer {offer.reference_code} sent",
                    publish_events=False,
                )
            except BusinessRuleError:
                logger.info("offer_status_move_skipped", application_id=str(application.id))

        await pipeline.add_timeline_event(
            application,
            event_type="OFFER_SENT",
            title="Offer sent",
            description=f"Offer {offer.reference_code} for {offer.position_title}",
            actor_id=actor_id,
            visible_to_candidate=True,
            meta={
                "offer_id": str(offer.id),
                "email_delivery_status": message.delivery_status.value,
            },
        )

        await self.audit.record(
            action=AuditAction.UPDATE,
            entity_type="Offer",
            entity_id=offer.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=f"Sent offer {offer.reference_code} to {application.candidate.email}",
            meta={"email_delivery_status": message.delivery_status.value},
        )
        self.events.collect(
            DomainEvent(
                name=Events.OFFER_SENT,
                company_id=self.company_id,
                entity_type="Offer",
                entity_id=offer.id,
                actor_id=actor_id,
                payload={
                    "offer_id": str(offer.id),
                    "job_id": str(offer.job_id),
                    "candidate_id": str(offer.candidate_id),
                    "candidate_name": application.candidate.full_name,
                },
            )
        )
        await self.session.flush()
        logger.info(
            "offer_sent",
            offer_id=str(offer.id),
            email_status=message.delivery_status.value,
        )
        return offer, raw_token

    async def mark_viewed(self, offer: Offer) -> Offer:
        if offer.status == OfferStatus.SENT:
            offer.status = OfferStatus.VIEWED
            offer.viewed_at = datetime.now(UTC)
            await self.session.flush()
        return offer

    async def respond(
        self,
        offer: Offer,
        *,
        accepted: bool,
        actor_id: uuid.UUID | None = None,
        decline_reason: str | None = None,
    ) -> Offer:
        """Record the candidate's decision and move the pipeline accordingly."""
        if offer.status not in _LIVE_OFFER_STATUSES:
            raise BusinessRuleError(
                f"This offer is {offer.status.value.lower()} and can no longer be answered",
                code="OFFER_NOT_ACTIONABLE",
            )
        if offer.expires_at and offer.expires_at <= datetime.now(UTC):
            offer.status = OfferStatus.EXPIRED
            await self.session.flush()
            raise BusinessRuleError(
                "This offer has expired. Please contact the recruiter.",
                code="OFFER_EXPIRED",
            )

        now = datetime.now(UTC)
        offer.status = OfferStatus.ACCEPTED if accepted else OfferStatus.REJECTED
        offer.responded_at = now
        if not accepted:
            offer.decline_reason = truncate(decline_reason, 500) if decline_reason else None

        application = (
            (
                await self.session.execute(
                    select(Application)
                    .where(Application.id == offer.application_id)
                    .options(
                        selectinload(Application.candidate), selectinload(Application.job)
                    )
                )
            )
            .unique()
            .scalar_one()
        )

        from app.modules.applications.service import ApplicationPipelineService

        pipeline = ApplicationPipelineService(self.session, self.company_id)
        target = (
            ApplicationStatus.OFFER_ACCEPTED if accepted else ApplicationStatus.OFFER_REJECTED
        )
        try:
            await pipeline.change_status(
                application,
                new_status=target,
                actor_id=actor_id,
                actor_type="USER" if actor_id else "SYSTEM",
                reason=(
                    f"Candidate accepted offer {offer.reference_code}"
                    if accepted
                    else f"Candidate declined offer {offer.reference_code}"
                ),
                publish_events=False,
            )
        except BusinessRuleError:
            logger.info("offer_response_status_move_skipped", offer_id=str(offer.id))

        onboarding = None
        if accepted:
            onboarding = await self.start_onboarding(offer, application)

        self.events.collect(
            DomainEvent(
                name=Events.OFFER_ACCEPTED if accepted else Events.OFFER_REJECTED,
                company_id=self.company_id,
                entity_type="Application",
                entity_id=application.id,
                actor_id=actor_id,
                payload={
                    "offer_id": str(offer.id),
                    "job_id": str(offer.job_id),
                    "job_title": application.job.title,
                    "candidate_id": str(offer.candidate_id),
                    "candidate_name": application.candidate.full_name,
                    "onboarding_id": str(onboarding.id) if onboarding else None,
                },
            )
        )

        await self.audit.record(
            action=AuditAction.STATUS_CHANGE,
            entity_type="Offer",
            entity_id=offer.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=(
                f"Offer {offer.reference_code} "
                f"{'accepted' if accepted else 'declined'} by the candidate"
            ),
            meta={"decline_reason": decline_reason} if not accepted else None,
        )
        await self.session.flush()
        logger.info("offer_responded", offer_id=str(offer.id), accepted=accepted)
        return offer

    async def withdraw(
        self, offer: Offer, *, actor_id: uuid.UUID, reason: str | None = None
    ) -> Offer:
        if offer.status in (OfferStatus.ACCEPTED, OfferStatus.WITHDRAWN):
            raise BusinessRuleError(
                f"An offer that is {offer.status.value.lower()} cannot be withdrawn"
            )
        offer.status = OfferStatus.WITHDRAWN
        await self.audit.record(
            action=AuditAction.UPDATE,
            entity_type="Offer",
            entity_id=offer.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=f"Withdrew offer {offer.reference_code}",
            meta={"reason": reason},
        )
        await self.session.flush()
        return offer

    # ----------------------------------------------------------- onboarding
    async def start_onboarding(
        self, offer: Offer, application: Application
    ) -> Onboarding:
        """Create the onboarding record and its default checklist (s36)."""
        existing = await self.session.scalar(
            select(Onboarding).where(Onboarding.offer_id == offer.id)
        )
        if existing is not None:
            return existing

        onboarding = Onboarding(
            company_id=self.company_id,
            offer_id=offer.id,
            candidate_id=offer.candidate_id,
            application_id=offer.application_id,
            status=OnboardingStatus.PREBOARDING,
            expected_joining_date=offer.joining_date,
            owner_id=offer.created_by_id,
        )
        self.session.add(onboarding)
        await self.session.flush()

        for index, template in enumerate(DEFAULT_ONBOARDING_TASKS):
            self.session.add(
                OnboardingTask(
                    onboarding_id=onboarding.id,
                    display_order=index,
                    due_date=offer.joining_date,
                    **template,
                )
            )
        await self.session.flush()
        logger.info("onboarding_started", onboarding_id=str(onboarding.id))
        return onboarding

async def verify_offer_access_token(
    session: AsyncSession, offer_id: uuid.UUID, raw_token: str
) -> Offer:
    """Validate a candidate's tokenised offer link (no login required).

    Deliberately not a method on ``OfferService``: the tenant is *derived* from the
    offer the token unlocks, so there is no company scope to construct beforehand.
    """
    from app.core.exceptions import InvalidToken
    from app.core.security import constant_time_equals

    offer = await session.scalar(select(Offer).where(Offer.id == offer_id))
    if offer is None or not offer.access_token_hash:
        raise ResourceNotFound("Offer", offer_id)
    if not constant_time_equals(offer.access_token_hash, hash_url_token(raw_token)):
        raise InvalidToken("This offer link is not valid")
    return offer
