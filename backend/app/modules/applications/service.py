"""Application creation and pipeline movement.

Two services live here:

* ``ApplicationPipelineService`` - status changes, the immutable timeline, bulk actions.
* ``ApplicationIntakeService`` - creating an application from a candidate's submission,
  including candidate de-duplication and kicking off resume processing.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import (
    ApplicationSource,
    ApplicationStatus,
    AuditAction,
    EmailTemplateKey,
    ReviewFlag,
    VerificationSignal,
)
from app.core.exceptions import (
    BusinessRuleError,
    DuplicateResource,
    ResourceNotFound,
    ValidationError,
)
from app.core.logging import get_logger
from app.models.application import Application, ApplicationTimelineEvent
from app.models.candidate import Candidate
from app.models.company import Company
from app.models.job import Job
from app.modules.applications.state_machine import (
    assert_transition,
    candidate_label,
    effects_for,
)
from app.services.audit import AuditService
from app.services.events import DomainEvent, EventCollector, Events
from app.utils.text import truncate

logger = get_logger(__name__)


def generate_reference(prefix: str) -> str:
    """Short, human-quotable reference, e.g. ``APP-7K2M4X``.

    Uses ``secrets`` over an incrementing counter so a reference does not disclose how
    many applications a company has received.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1
    return f"{prefix}-{''.join(secrets.choice(alphabet) for _ in range(6))}"


class ApplicationPipelineService:
    """Status transitions and the timeline."""

    def __init__(self, session: AsyncSession, company_id: uuid.UUID) -> None:
        self.session = session
        self.company_id = company_id
        self.audit = AuditService(session)
        self.events = EventCollector()

    # ------------------------------------------------------------- timeline
    async def add_timeline_event(
        self,
        application: Application,
        *,
        event_type: str,
        title: str,
        description: str | None = None,
        previous_status: ApplicationStatus | None = None,
        new_status: ApplicationStatus | None = None,
        actor_id: uuid.UUID | None = None,
        actor_type: str = "USER",
        visible_to_candidate: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> ApplicationTimelineEvent:
        event = ApplicationTimelineEvent(
            company_id=self.company_id,
            application_id=application.id,
            event_type=event_type,
            title=truncate(title, 255),
            description=description,
            previous_status=previous_status,
            new_status=new_status,
            actor_id=actor_id,
            actor_type=actor_type,
            is_visible_to_candidate=visible_to_candidate,
            meta=meta or {},
        )
        self.session.add(event)
        return event

    async def get_timeline(
        self, application_id: uuid.UUID, *, candidate_view: bool = False
    ) -> list[ApplicationTimelineEvent]:
        stmt = (
            select(ApplicationTimelineEvent)
            .where(
                ApplicationTimelineEvent.application_id == application_id,
                ApplicationTimelineEvent.company_id == self.company_id,
            )
            .order_by(ApplicationTimelineEvent.created_at.asc())
        )
        if candidate_view:
            stmt = stmt.where(ApplicationTimelineEvent.is_visible_to_candidate.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())

    # --------------------------------------------------------------- status
    async def change_status(
        self,
        application: Application,
        *,
        new_status: ApplicationStatus,
        actor_id: uuid.UUID | None = None,
        actor_type: str = "USER",
        reason: str | None = None,
        send_email: bool = False,
        custom_message: str | None = None,
        publish_events: bool = True,
    ) -> Application:
        """Move an application through the pipeline, recording everything."""
        previous = application.status
        assert_transition(previous, new_status)

        now = datetime.now(UTC)
        application.status = new_status
        application.status_changed_at = now
        if actor_type in ("WORKFLOW", "SYSTEM"):
            application.last_automated_action_at = now

        effects = effects_for(new_status)
        if effects.stamps_shortlisted and application.shortlisted_at is None:
            application.shortlisted_at = now
        if effects.stamps_interviewed and application.interviewed_at is None:
            application.interviewed_at = now
        if effects.stamps_offered and application.offered_at is None:
            application.offered_at = now
        if effects.stamps_hired:
            application.hired_at = now
        if new_status == ApplicationStatus.REJECTED and reason:
            application.rejection_reason = truncate(reason, 255)
        if new_status == ApplicationStatus.WITHDRAWN:
            application.withdrawn_at = now

        await self.add_timeline_event(
            application,
            event_type="STATUS_CHANGED",
            title=f"Status changed to {new_status.value.replace('_', ' ').title()}",
            description=reason,
            previous_status=previous,
            new_status=new_status,
            actor_id=actor_id,
            actor_type=actor_type,
            visible_to_candidate=True,
            meta={"candidate_label": candidate_label(new_status)},
        )

        await self.audit.record(
            action=AuditAction.STATUS_CHANGE,
            entity_type="Application",
            entity_id=application.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=(
                f"Application {application.reference_code} moved from "
                f"{previous.value} to {new_status.value}"
                + (" by automation" if actor_type == "WORKFLOW" else "")
            ),
            changes={"status": {"from": previous.value, "to": new_status.value}},
            meta={"actor_type": actor_type, "reason": reason},
        )

        if send_email and effects.email_template:
            await self._send_status_email(
                application,
                template_key=EmailTemplateKey(effects.email_template),
                custom_message=custom_message,
                actor_id=actor_id,
                automated=actor_type != "USER",
            )

        await self.session.flush()

        if publish_events:
            self.events.collect(
                DomainEvent(
                    name=Events.APPLICATION_STATUS_CHANGED,
                    company_id=self.company_id,
                    entity_type="Application",
                    entity_id=application.id,
                    actor_id=actor_id,
                    payload={
                        "previous_status": previous.value,
                        "new_status": new_status.value,
                        "job_id": str(application.job_id),
                        "candidate_id": str(application.candidate_id),
                        "assigned_recruiter_id": (
                            str(application.assigned_recruiter_id)
                            if application.assigned_recruiter_id
                            else None
                        ),
                    },
                )
            )
            if new_status == ApplicationStatus.HIRED:
                self.events.collect(
                    DomainEvent(
                        name=Events.CANDIDATE_HIRED,
                        company_id=self.company_id,
                        entity_type="Application",
                        entity_id=application.id,
                        actor_id=actor_id,
                        payload={
                            "job_id": str(application.job_id),
                            "candidate_id": str(application.candidate_id),
                        },
                    )
                )

        logger.info(
            "application_status_changed",
            application_id=str(application.id),
            previous=previous.value,
            new=new_status.value,
            actor_type=actor_type,
        )
        return application

    async def _send_status_email(
        self,
        application: Application,
        *,
        template_key: EmailTemplateKey,
        custom_message: str | None,
        actor_id: uuid.UUID | None,
        automated: bool,
    ) -> None:
        from app.models.user import User
        from app.modules.emails.service import EmailService

        candidate = application.candidate or await self.session.get(
            Candidate, application.candidate_id
        )
        job = application.job or await self.session.get(Job, application.job_id)
        company = await self.session.get(Company, self.company_id)
        recruiter = await self.session.get(User, actor_id) if actor_id else None

        service = EmailService(self.session, self.company_id)
        variables = EmailService.build_variables(
            candidate=candidate,
            job=job,
            application=application,
            company=company,
            recruiter=recruiter,
            extra={"custom_message": custom_message or ""},
        )
        message = await service.send_templated(
            key=template_key,
            to=[candidate.email],
            variables=variables,
            application_id=application.id,
            candidate_id=application.candidate_id,
            job_id=application.job_id,
            sent_by_id=actor_id,
            is_automated=automated,
        )
        await self.add_timeline_event(
            application,
            event_type="EMAIL_SENT",
            title=f"Email sent: {template_key.value.replace('_', ' ').title()}",
            description=(
                None
                if message.delivery_status.value == "SENT"
                else f"Delivery status: {message.delivery_status.value}"
            ),
            actor_id=actor_id,
            actor_type="WORKFLOW" if automated else "USER",
            meta={"delivery_status": message.delivery_status.value, "email_id": str(message.id)},
        )

    # ---------------------------------------------------------------- bulk
    async def bulk_change_status(
        self,
        application_ids: Sequence[uuid.UUID],
        *,
        new_status: ApplicationStatus,
        actor_id: uuid.UUID,
        reason: str | None = None,
        send_email: bool = False,
    ) -> dict[str, Any]:
        """Apply a status change to many applications.

        Partial success is the expected outcome - some applications will be in a state
        that cannot reach the target - so each is reported individually rather than
        failing the whole batch.
        """
        if len(application_ids) > 200:
            raise ValidationError("At most 200 applications can be updated at once")

        stmt = (
            select(Application)
            .where(
                Application.id.in_(application_ids),
                Application.company_id == self.company_id,
            )
            .options(
                selectinload(Application.candidate), selectinload(Application.job)
            )
        )
        applications = list((await self.session.execute(stmt)).unique().scalars().all())
        found = {a.id for a in applications}

        succeeded: list[str] = []
        failed: list[dict[str, str]] = []

        for missing in set(application_ids) - found:
            failed.append({"id": str(missing), "reason": "Not found in this company"})

        for application in applications:
            try:
                await self.change_status(
                    application,
                    new_status=new_status,
                    actor_id=actor_id,
                    reason=reason,
                    send_email=send_email,
                )
                succeeded.append(str(application.id))
            except BusinessRuleError as exc:
                failed.append({"id": str(application.id), "reason": exc.message})

        logger.info(
            "bulk_status_change",
            requested=len(application_ids),
            succeeded=len(succeeded),
            failed=len(failed),
            new_status=new_status.value,
        )
        return {
            "requested": len(application_ids),
            "succeeded": succeeded,
            "failed": failed,
            "new_status": new_status.value,
        }


class ApplicationIntakeService:
    """Creating applications, including candidate de-duplication."""

    def __init__(self, session: AsyncSession, company_id: uuid.UUID) -> None:
        self.session = session
        self.company_id = company_id
        self.audit = AuditService(session)
        self.events = EventCollector()
        self.pipeline = ApplicationPipelineService(session, company_id)

    async def find_or_create_candidate(
        self,
        *,
        email: str,
        first_name: str,
        last_name: str,
        phone: str | None = None,
        user_id: uuid.UUID | None = None,
        location: str | None = None,
        source: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[Candidate, bool]:
        """Return ``(candidate, created)``, de-duplicating within this company (s32).

        Email is the primary key for a person here because it is the identifier we can
        actually verify. Phone is used as a secondary signal: a match on phone with a
        different email produces a *review flag*, not a merge - two people can share a
        household phone, and silently merging profiles would be worse than a false
        duplicate a human can dismiss.
        """
        email = email.strip().lower()
        existing = await self.session.scalar(
            select(Candidate)
            .where(
                Candidate.company_id == self.company_id,
                Candidate.email == email,
                Candidate.deleted_at.is_(None),
            )
            .options(selectinload(Candidate.skills))
        )
        if existing is not None:
            # Fill in details the candidate has since supplied, without overwriting
            # anything a recruiter may have corrected.
            if phone and not existing.phone:
                existing.phone = phone
            if location and not existing.location:
                existing.location = location
            if user_id and not existing.user_id:
                existing.user_id = user_id
            return existing, False

        if phone:
            phone_match = await self.session.scalar(
                select(Candidate).where(
                    Candidate.company_id == self.company_id,
                    Candidate.phone == phone,
                    Candidate.deleted_at.is_(None),
                )
            )
            if phone_match is not None:
                self._add_review_flag(
                    phone_match,
                    ReviewFlag.DUPLICATE_PROFILE_DETECTED,
                    f"Another applicant ({email}) submitted the same phone number.",
                )

        candidate = Candidate(
            company_id=self.company_id,
            user_id=user_id,
            email=email,
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            phone=phone,
            location=location,
            source=source,
            **(extra or {}),
        )
        self.session.add(candidate)
        await self.session.flush()
        logger.info("candidate_created", candidate_id=str(candidate.id))
        return candidate, True

    @staticmethod
    def _add_review_flag(candidate: Candidate, flag: ReviewFlag, message: str) -> None:
        """Append a review flag if it is not already present.

        These are prompts for a human, never automatic judgements about a person (s17).
        """
        flags = list(candidate.review_flags or [])
        if any(f.get("code") == flag.value for f in flags):
            return
        flags.append(
            {
                "code": flag.value,
                "message": message,
                "raised_at": datetime.now(UTC).isoformat(),
                "resolved": False,
            }
        )
        candidate.review_flags = flags

    async def create_application(
        self,
        *,
        job: Job,
        candidate: Candidate,
        source: ApplicationSource = ApplicationSource.DIRECT,
        source_detail: str | None = None,
        utm: dict[str, Any] | None = None,
        cover_letter: str | None = None,
        expected_salary: float | None = None,
        notice_period_days: int | None = None,
        referral_id: uuid.UUID | None = None,
        consent_given: bool = False,
        actor_id: uuid.UUID | None = None,
    ) -> Application:
        if job.company_id != self.company_id:
            raise ResourceNotFound("Job", job.id)
        if not job.is_open_for_applications:
            raise BusinessRuleError(
                "This job is not currently accepting applications",
                code="JOB_NOT_ACCEPTING_APPLICATIONS",
                details={"job_status": job.status.value},
            )
        if not consent_given:
            raise ValidationError(
                "Consent to process your application data is required",
                code="CONSENT_REQUIRED",
            )

        existing = await self.session.scalar(
            select(Application).where(
                Application.job_id == job.id, Application.candidate_id == candidate.id
            )
        )
        if existing is not None:
            raise DuplicateResource(
                "You have already applied for this role",
                code="ALREADY_APPLIED",
                details={
                    "application_id": str(existing.id),
                    "status": existing.status.value,
                    "applied_at": existing.created_at.isoformat(),
                },
            )

        now = datetime.now(UTC)
        application = Application(
            company_id=self.company_id,
            reference_code=generate_reference("APP"),
            job_id=job.id,
            candidate_id=candidate.id,
            status=ApplicationStatus.APPLIED,
            source=source,
            source_detail=truncate(source_detail, 120) if source_detail else None,
            utm=utm or {},
            cover_letter=cover_letter,
            expected_salary=expected_salary,
            notice_period_days=notice_period_days,
            referral_id=referral_id,
            consent_given_at=now,
            status_changed_at=now,
        )
        self.session.add(application)

        candidate.consent_given_at = candidate.consent_given_at or now
        candidate.privacy_policy_accepted_at = candidate.privacy_policy_accepted_at or now
        if expected_salary and not candidate.expected_salary:
            candidate.expected_salary = expected_salary
        if notice_period_days is not None and candidate.notice_period_days is None:
            candidate.notice_period_days = notice_period_days

        job.application_count = (job.application_count or 0) + 1
        await self.session.flush()

        await self.pipeline.add_timeline_event(
            application,
            event_type="APPLICATION_SUBMITTED",
            title="Application submitted",
            description=f"Applied for {job.title}",
            new_status=ApplicationStatus.APPLIED,
            actor_id=actor_id or candidate.user_id,
            actor_type="USER",
            visible_to_candidate=True,
            meta={"source": source.value, "reference": application.reference_code},
        )

        await self.audit.record(
            action=AuditAction.CREATE,
            entity_type="Application",
            entity_id=application.id,
            company_id=self.company_id,
            actor_id=actor_id or candidate.user_id,
            summary=f"{candidate.full_name} applied for {job.title}",
            meta={"job_id": str(job.id), "source": source.value},
        )

        self.events.collect(
            DomainEvent(
                name=Events.APPLICATION_CREATED,
                company_id=self.company_id,
                entity_type="Application",
                entity_id=application.id,
                actor_id=actor_id or candidate.user_id,
                payload={
                    "job_id": str(job.id),
                    "job_title": job.title,
                    "candidate_id": str(candidate.id),
                    "candidate_name": candidate.full_name,
                    "source": source.value,
                },
            )
        )

        logger.info(
            "application_created",
            application_id=str(application.id),
            job_id=str(job.id),
            source=source.value,
        )
        return application

    async def refresh_verification_signals(self, candidate: Candidate) -> None:
        """Recompute the objective verification signals shown to recruiters (s17).

        Uses count queries rather than reading ``candidate.skills`` / ``.experience``:
        this runs immediately after the candidate is created, when those collections
        have never been loaded, and touching them would trigger a lazy load that raises
        ``MissingGreenlet`` under the async session.
        """
        from app.models.candidate import (
            CandidateEducation,
            CandidateExperience,
            CandidateSkill,
        )

        signals: list[str] = []
        if candidate.email_verified:
            signals.append(VerificationSignal.EMAIL_VERIFIED.value)
        if candidate.phone_verified:
            signals.append(VerificationSignal.PHONE_VERIFIED.value)

        async def count_of(model) -> int:
            return await self.session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.candidate_id == candidate.id)
            ) or 0

        has_resume = await self.session.scalar(
            select(func.count())
            .select_from(Application)
            .where(
                Application.candidate_id == candidate.id, Application.resume_id.is_not(None)
            )
        )
        if has_resume:
            signals.append(VerificationSignal.RESUME_UPLOADED.value)

        if candidate.linkedin_url or candidate.github_url or candidate.portfolio_url:
            signals.append(VerificationSignal.LINKS_PROVIDED.value)

        skill_count = await count_of(CandidateSkill)
        history_count = await count_of(CandidateExperience) + await count_of(
            CandidateEducation
        )

        complete = all(
            [candidate.phone, candidate.location, skill_count > 0, history_count > 0]
        )
        if complete:
            signals.append(VerificationSignal.PROFILE_COMPLETE.value)
        else:
            self._add_review_flag(
                candidate,
                ReviewFlag.MISSING_INFORMATION,
                "The candidate profile is missing contact, skills or history details.",
            )

        candidate.verification_signals = signals


async def resolve_source(raw: str | None) -> tuple[ApplicationSource, str | None]:
    """Map a ``?source=`` query value onto the enum, keeping the raw value for analytics."""
    if not raw:
        return ApplicationSource.DIRECT, None
    normalised = raw.strip().upper().replace("-", "_").replace(" ", "_")
    try:
        return ApplicationSource(normalised), raw.strip()[:120]
    except ValueError:
        aliases = {
            "LINKEDIN": ApplicationSource.LINKEDIN,
            "LI": ApplicationSource.LINKEDIN,
            "IG": ApplicationSource.INSTAGRAM,
            "INSTA": ApplicationSource.INSTAGRAM,
            "FB": ApplicationSource.FACEBOOK,
            "X": ApplicationSource.TWITTER,
            "NAUKRI": ApplicationSource.JOB_BOARD,
            "INDEED": ApplicationSource.JOB_BOARD,
            "MONSTER": ApplicationSource.JOB_BOARD,
            "GLASSDOOR": ApplicationSource.JOB_BOARD,
            "WEBSITE": ApplicationSource.COMPANY_WEBSITE,
            "CAREERS": ApplicationSource.COMPANY_WEBSITE,
        }
        return aliases.get(normalised, ApplicationSource.OTHER), raw.strip()[:120]


def status_counts_to_funnel(counts: dict[str, int]) -> dict[str, int]:
    """Convert per-status counts into cumulative funnel stages."""
    from app.modules.applications.state_machine import PIPELINE_ORDER, reached_stage

    funnel: dict[str, int] = {}
    for stage in PIPELINE_ORDER:
        total = 0
        for status_value, count in counts.items():
            try:
                status = ApplicationStatus(status_value)
            except ValueError:
                continue
            if reached_stage(status, stage):
                total += count
        funnel[stage.value] = total
    return funnel
