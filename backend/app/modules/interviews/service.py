"""Interview scheduling, rescheduling, feedback and AI feedback summarisation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import (
    ApplicationStatus,
    AuditAction,
    EmailTemplateKey,
    InterviewRecommendation,
    InterviewStatus,
    InterviewType,
)
from app.core.exceptions import (
    BusinessRuleError,
    DuplicateResource,
    PermissionDenied,
    ResourceNotFound,
    ValidationError,
)
from app.core.logging import get_logger
from app.models.application import Application
from app.models.calendar import CalendarEvent
from app.models.company import Company
from app.models.interview import Interview, InterviewFeedback, InterviewParticipant
from app.models.user import User
from app.providers.ai.factory import get_ai_provider
from app.providers.calendar import (
    CalendarAttendee,
    CalendarEventPayload,
    get_calendar_provider,
)
from app.services.audit import AuditService
from app.services.events import DomainEvent, EventCollector, Events
from app.utils.text import truncate

logger = get_logger(__name__)

MIN_DURATION_MINUTES = 5
MAX_DURATION_MINUTES = 8 * 60


class InterviewService:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID) -> None:
        self.session = session
        self.company_id = company_id
        self.audit = AuditService(session)
        self.events = EventCollector()

    # --------------------------------------------------------------- reads
    def base_query(self):
        return (
            select(Interview)
            .where(Interview.company_id == self.company_id)
            .options(
                selectinload(Interview.participants),
                selectinload(Interview.feedback),
                selectinload(Interview.application).selectinload(Application.candidate),
                selectinload(Interview.application).selectinload(Application.job),
            )
        )

    async def get(self, interview_id: uuid.UUID) -> Interview:
        interview = (
            (await self.session.execute(self.base_query().where(Interview.id == interview_id)))
            .unique()
            .scalar_one_or_none()
        )
        if interview is None:
            raise ResourceNotFound("Interview", interview_id)
        return interview

    async def list(
        self,
        *,
        job_id: uuid.UUID | None = None,
        candidate_id: uuid.UUID | None = None,
        application_id: uuid.UUID | None = None,
        interviewer_id: uuid.UUID | None = None,
        statuses: list[InterviewStatus] | None = None,
        start_after: datetime | None = None,
        start_before: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Interview], int]:
        stmt = self.base_query()
        if job_id:
            stmt = stmt.where(Interview.job_id == job_id)
        if candidate_id:
            stmt = stmt.where(Interview.candidate_id == candidate_id)
        if application_id:
            stmt = stmt.where(Interview.application_id == application_id)
        if interviewer_id:
            stmt = stmt.where(
                Interview.id.in_(
                    select(InterviewParticipant.interview_id).where(
                        InterviewParticipant.user_id == interviewer_id
                    )
                )
            )
        if statuses:
            stmt = stmt.where(Interview.status.in_(statuses))
        if start_after:
            stmt = stmt.where(Interview.scheduled_start >= start_after)
        if start_before:
            stmt = stmt.where(Interview.scheduled_start <= start_before)

        total = (
            await self.session.execute(
                select(func.count()).select_from(stmt.order_by(None).subquery())
            )
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(Interview.scheduled_start.asc())
                    .limit(page_size)
                    .offset((page - 1) * page_size)
                )
            )
            .unique()
            .scalars()
            .all()
        )
        return list(rows), total

    # ------------------------------------------------------------ scheduling
    async def schedule(
        self,
        *,
        application_id: uuid.UUID,
        interview_type: InterviewType,
        scheduled_start: datetime,
        duration_minutes: int,
        interviewer_ids: list[uuid.UUID],
        organiser_id: uuid.UUID,
        title: str | None = None,
        round_name: str | None = None,
        timezone: str = "UTC",
        meeting_link: str | None = None,
        location: str | None = None,
        candidate_instructions: str | None = None,
        internal_notes: str | None = None,
        send_invitation: bool = True,
        create_conference: bool = False,
    ) -> Interview:
        if not MIN_DURATION_MINUTES <= duration_minutes <= MAX_DURATION_MINUTES:
            raise ValidationError(
                f"Duration must be between {MIN_DURATION_MINUTES} minutes and "
                f"{MAX_DURATION_MINUTES // 60} hours"
            )
        if scheduled_start <= datetime.now(UTC):
            raise ValidationError("An interview cannot be scheduled in the past")
        if not interviewer_ids:
            raise ValidationError("At least one interviewer is required")

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
                f"Cannot schedule an interview for a {application.status.value.lower()} "
                "application"
            )

        interviewers = await self._validate_interviewers(interviewer_ids)
        scheduled_end = scheduled_start + timedelta(minutes=duration_minutes)

        conflicts = await self.find_conflicts(
            interviewer_ids, scheduled_start, scheduled_end
        )
        if conflicts:
            raise DuplicateResource(
                "One or more interviewers already have an interview at that time",
                code="INTERVIEWER_CONFLICT",
                details={
                    "conflicts": [
                        {
                            "interviewer": c["interviewer_name"],
                            "interview_id": str(c["interview_id"]),
                            "starts_at": c["starts_at"].isoformat(),
                        }
                        for c in conflicts
                    ]
                },
            )

        round_number = (
            await self.session.scalar(
                select(func.count())
                .select_from(Interview)
                .where(Interview.application_id == application_id)
            )
        ) + 1

        interview = Interview(
            company_id=self.company_id,
            application_id=application.id,
            job_id=application.job_id,
            candidate_id=application.candidate_id,
            title=title
            or f"{interview_type.value.replace('_', ' ').title()} - {application.job.title}",
            round_number=round_number,
            round_name=round_name,
            interview_type=interview_type,
            status=InterviewStatus.SCHEDULED,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            duration_minutes=duration_minutes,
            timezone=timezone,
            meeting_link=meeting_link,
            location=location,
            candidate_instructions=candidate_instructions,
            internal_notes=internal_notes,
            organiser_id=organiser_id,
        )
        self.session.add(interview)
        await self.session.flush()

        for user in interviewers:
            self.session.add(
                InterviewParticipant(
                    interview_id=interview.id, user_id=user.id, role="INTERVIEWER"
                )
            )
        if organiser_id not in {u.id for u in interviewers}:
            self.session.add(
                InterviewParticipant(
                    interview_id=interview.id,
                    user_id=organiser_id,
                    role="ORGANISER",
                    is_required=False,
                )
            )

        event = await self._sync_calendar(
            interview,
            application=application,
            interviewers=interviewers,
            create_conference=create_conference,
        )
        interview.calendar_event_id = event.id
        if event.meeting_link and not interview.meeting_link:
            interview.meeting_link = event.meeting_link

        # Move the application into INTERVIEW if it is not there already.
        if application.status not in (
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.INTERVIEW_PASSED,
        ):
            from app.modules.applications.service import ApplicationPipelineService

            pipeline = ApplicationPipelineService(self.session, self.company_id)
            try:
                await pipeline.change_status(
                    application,
                    new_status=ApplicationStatus.INTERVIEW,
                    actor_id=organiser_id,
                    reason=f"Interview scheduled: {interview.title}",
                    publish_events=False,
                )
            except BusinessRuleError:
                # An unusual current status should not block scheduling the interview.
                logger.info(
                    "interview_status_move_skipped",
                    application_id=str(application.id),
                    status=application.status.value,
                )

        if send_invitation:
            await self._send_invitation(
                interview, application, EmailTemplateKey.INTERVIEW_INVITATION
            )

        await self.audit.record(
            action=AuditAction.CREATE,
            entity_type="Interview",
            entity_id=interview.id,
            company_id=self.company_id,
            actor_id=organiser_id,
            summary=(
                f"Scheduled {interview.title} with "
                f"{application.candidate.full_name} for "
                f"{scheduled_start.strftime('%d %b %Y %H:%M')} UTC"
            ),
            meta={"round": round_number, "interviewers": len(interviewers)},
        )

        self.events.collect(
            DomainEvent(
                name=Events.INTERVIEW_SCHEDULED,
                company_id=self.company_id,
                entity_type="Interview",
                entity_id=interview.id,
                actor_id=organiser_id,
                payload={
                    "interview_id": str(interview.id),
                    "interview_title": interview.title,
                    "application_id": str(application.id),
                    "job_id": str(application.job_id),
                    "candidate_id": str(application.candidate_id),
                    "candidate_name": application.candidate.full_name,
                    "interviewer_ids": [str(u.id) for u in interviewers],
                },
            )
        )

        await self.session.flush()
        logger.info(
            "interview_scheduled",
            interview_id=str(interview.id),
            round=round_number,
            calendar_sync=event.sync_status,
        )
        return interview

    async def _validate_interviewers(self, interviewer_ids: list[uuid.UUID]) -> list[User]:
        users = (
            (
                await self.session.execute(
                    select(User).where(
                        User.id.in_(interviewer_ids),
                        User.company_id == self.company_id,
                        User.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        found = {u.id for u in users}
        missing = set(interviewer_ids) - found
        if missing:
            raise ValidationError(
                "Some interviewers were not found in your company",
                details={"missing_user_ids": [str(m) for m in missing]},
            )
        return list(users)

    async def find_conflicts(
        self,
        interviewer_ids: list[uuid.UUID],
        start: datetime,
        end: datetime,
        *,
        exclude_interview_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Find overlapping interviews for these interviewers.

        Two intervals overlap when ``existing.start < new.end`` and
        ``existing.end > new.start`` - back-to-back slots do not conflict.
        """
        stmt = (
            select(Interview, InterviewParticipant.user_id, User.first_name, User.last_name)
            .join(InterviewParticipant, InterviewParticipant.interview_id == Interview.id)
            .join(User, User.id == InterviewParticipant.user_id)
            .where(
                Interview.company_id == self.company_id,
                InterviewParticipant.user_id.in_(interviewer_ids),
                Interview.status.in_(
                    [InterviewStatus.SCHEDULED, InterviewStatus.CONFIRMED]
                ),
                and_(Interview.scheduled_start < end, Interview.scheduled_end > start),
            )
        )
        if exclude_interview_id:
            stmt = stmt.where(Interview.id != exclude_interview_id)

        return [
            {
                "interview_id": row[0].id,
                "interviewer_id": row[1],
                "interviewer_name": f"{row[2]} {row[3]}",
                "starts_at": row[0].scheduled_start,
            }
            for row in (await self.session.execute(stmt)).all()
        ]

    async def _sync_calendar(
        self,
        interview: Interview,
        *,
        application: Application,
        interviewers: list[User],
        create_conference: bool,
    ) -> CalendarEvent:
        """Create HireHQ's own event and mirror it to an external calendar if connected."""
        attendees = [
            CalendarAttendee(
                email=application.candidate.email,
                name=application.candidate.full_name,
            ),
            *[
                CalendarAttendee(email=u.email, name=u.full_name)
                for u in interviewers
            ],
        ]

        provider = get_calendar_provider()
        payload = CalendarEventPayload(
            title=interview.title,
            start_at=interview.scheduled_start,
            end_at=interview.scheduled_end,
            timezone=interview.timezone,
            description=interview.candidate_instructions or "",
            location=interview.location,
            meeting_link=interview.meeting_link,
            attendees=attendees,
            create_conference=create_conference,
        )

        access_token = await self._calendar_token(interview.organiser_id)
        try:
            result = await provider.create_event(payload, access_token=access_token)
        except Exception as exc:
            logger.warning("calendar_sync_failed", error=str(exc))
            from app.providers.calendar import CalendarSyncResult

            result = CalendarSyncResult(status="FAILED", detail=truncate(str(exc), 500))

        event = CalendarEvent(
            company_id=self.company_id,
            title=interview.title,
            description=interview.candidate_instructions,
            location=interview.location,
            meeting_link=result.meeting_link or interview.meeting_link,
            start_at=interview.scheduled_start,
            end_at=interview.scheduled_end,
            timezone=interview.timezone,
            organiser_id=interview.organiser_id,
            interview_id=interview.id,
            provider=result.provider,
            external_event_id=result.external_event_id,
            sync_status=result.status,
            sync_error=result.detail if result.status == "FAILED" else None,
            last_synced_at=datetime.now(UTC) if result.synced else None,
            attendees=[
                {
                    "email": a.email,
                    "name": a.name,
                    "type": "CANDIDATE" if a.email == application.candidate.email else "INTERVIEWER",
                    "response": "PENDING",
                }
                for a in attendees
            ],
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def _calendar_token(self, user_id: uuid.UUID | None) -> str | None:
        """Usable access token for the organiser's connected calendar, refreshing if stale.

        Access tokens live about an hour, so an interview scheduled the morning after a
        connection would otherwise fail to sync. Refreshing here - rather than on a
        timer - means a token is only renewed when it is actually needed.
        """
        if user_id is None:
            return None
        from app.models.calendar import CalendarAccount

        account = await self.session.scalar(
            select(CalendarAccount).where(
                CalendarAccount.user_id == user_id,
                CalendarAccount.company_id == self.company_id,
                CalendarAccount.is_active.is_(True),
            )
        )
        if account is None:
            return None

        from app.services.oauth_tokens import ensure_fresh_access_token

        return await ensure_fresh_access_token(self.session, account)

    async def _send_invitation(
        self,
        interview: Interview,
        application: Application,
        template_key: EmailTemplateKey,
    ) -> None:
        from app.modules.emails.service import EmailService

        company = await self.session.get(Company, self.company_id)
        recruiter = (
            await self.session.get(User, interview.organiser_id)
            if interview.organiser_id
            else None
        )
        service = EmailService(self.session, self.company_id)
        variables = EmailService.build_variables(
            candidate=application.candidate,
            job=application.job,
            application=application,
            company=company,
            recruiter=recruiter,
            interview=interview,
        )
        await service.send_templated(
            key=template_key,
            to=[application.candidate.email],
            variables=variables,
            application_id=application.id,
            candidate_id=application.candidate_id,
            job_id=application.job_id,
            sent_by_id=interview.organiser_id,
            is_automated=True,
        )

    # ---------------------------------------------------------- reschedule
    async def reschedule(
        self,
        interview: Interview,
        *,
        scheduled_start: datetime,
        duration_minutes: int | None = None,
        actor_id: uuid.UUID,
        reason: str | None = None,
        notify: bool = True,
    ) -> Interview:
        if interview.status in (InterviewStatus.CANCELLED, InterviewStatus.COMPLETED):
            raise BusinessRuleError(
                f"A {interview.status.value.lower()} interview cannot be rescheduled"
            )
        if scheduled_start <= datetime.now(UTC):
            raise ValidationError("An interview cannot be rescheduled into the past")

        duration = duration_minutes or interview.duration_minutes
        new_end = scheduled_start + timedelta(minutes=duration)

        interviewer_ids = [p.user_id for p in interview.participants if p.user_id]
        conflicts = await self.find_conflicts(
            interviewer_ids, scheduled_start, new_end, exclude_interview_id=interview.id
        )
        if conflicts:
            raise DuplicateResource(
                "One or more interviewers are busy at the new time",
                code="INTERVIEWER_CONFLICT",
                details={"conflicts": [c["interviewer_name"] for c in conflicts]},
            )

        previous_start = interview.scheduled_start
        interview.rescheduled_from = previous_start
        interview.scheduled_start = scheduled_start
        interview.scheduled_end = new_end
        interview.duration_minutes = duration
        interview.status = InterviewStatus.RESCHEDULED
        interview.reschedule_count += 1
        interview.candidate_confirmed_at = None
        # Reminders must fire again relative to the new time.
        interview.reminders_sent = []

        if interview.calendar_event_id:
            await self._update_calendar_event(interview)

        if notify:
            application = interview.application
            await self._send_invitation(
                interview, application, EmailTemplateKey.INTERVIEW_RESCHEDULED
            )

        await self.audit.record(
            action=AuditAction.UPDATE,
            entity_type="Interview",
            entity_id=interview.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=(
                f"Rescheduled {interview.title} from "
                f"{previous_start.strftime('%d %b %H:%M')} to "
                f"{scheduled_start.strftime('%d %b %H:%M')} UTC"
            ),
            meta={"reason": reason},
        )
        self.events.collect(
            DomainEvent(
                name=Events.INTERVIEW_RESCHEDULED,
                company_id=self.company_id,
                entity_type="Interview",
                entity_id=interview.id,
                actor_id=actor_id,
                payload={
                    "interview_id": str(interview.id),
                    "job_id": str(interview.job_id),
                    "candidate_id": str(interview.candidate_id),
                    "interviewer_ids": [str(i) for i in interviewer_ids],
                },
            )
        )
        await self.session.flush()
        return interview

    async def _update_calendar_event(self, interview: Interview) -> None:
        event = await self.session.get(CalendarEvent, interview.calendar_event_id)
        if event is None:
            return
        event.start_at = interview.scheduled_start
        event.end_at = interview.scheduled_end

        if event.external_event_id:
            provider = get_calendar_provider()
            token = await self._calendar_token(interview.organiser_id)
            payload = CalendarEventPayload(
                title=interview.title,
                start_at=interview.scheduled_start,
                end_at=interview.scheduled_end,
                timezone=interview.timezone,
                description=interview.candidate_instructions or "",
                location=interview.location,
                meeting_link=interview.meeting_link,
                attendees=[
                    CalendarAttendee(email=a["email"], name=a.get("name"))
                    for a in (event.attendees or [])
                ],
            )
            try:
                result = await provider.update_event(
                    event.external_event_id, payload, access_token=token
                )
                event.sync_status = result.status
                event.sync_error = result.detail if result.status == "FAILED" else None
                event.last_synced_at = datetime.now(UTC) if result.synced else None
            except Exception as exc:
                event.sync_status = "FAILED"
                event.sync_error = truncate(str(exc), 500)

    async def cancel(
        self,
        interview: Interview,
        *,
        actor_id: uuid.UUID,
        reason: str | None = None,
    ) -> Interview:
        if interview.status == InterviewStatus.CANCELLED:
            raise BusinessRuleError("This interview is already cancelled")

        interview.status = InterviewStatus.CANCELLED
        interview.cancelled_at = datetime.now(UTC)
        interview.cancellation_reason = truncate(reason, 255) if reason else None

        if interview.calendar_event_id:
            event = await self.session.get(CalendarEvent, interview.calendar_event_id)
            if event is not None:
                event.status = "CANCELLED"
                if event.external_event_id:
                    provider = get_calendar_provider()
                    token = await self._calendar_token(interview.organiser_id)
                    try:
                        result = await provider.cancel_event(
                            event.external_event_id, access_token=token
                        )
                        event.sync_status = result.status
                    except Exception as exc:
                        event.sync_status = "FAILED"
                        event.sync_error = truncate(str(exc), 500)

        await self.audit.record(
            action=AuditAction.UPDATE,
            entity_type="Interview",
            entity_id=interview.id,
            company_id=self.company_id,
            actor_id=actor_id,
            summary=f"Cancelled {interview.title}",
            meta={"reason": reason},
        )
        await self.session.flush()
        return interview

    async def mark_completed(
        self, interview: Interview, *, actor_id: uuid.UUID
    ) -> Interview:
        if interview.status == InterviewStatus.COMPLETED:
            raise BusinessRuleError("This interview is already marked complete")
        interview.status = InterviewStatus.COMPLETED
        interview.completed_at = datetime.now(UTC)

        self.events.collect(
            DomainEvent(
                name=Events.INTERVIEW_COMPLETED,
                company_id=self.company_id,
                entity_type="Interview",
                entity_id=interview.id,
                actor_id=actor_id,
                payload={
                    "interview_id": str(interview.id),
                    "application_id": str(interview.application_id),
                    "job_id": str(interview.job_id),
                    "candidate_id": str(interview.candidate_id),
                    "interviewer_ids": [
                        str(p.user_id) for p in interview.participants if p.user_id
                    ],
                },
            )
        )
        await self.session.flush()
        return interview

    # ------------------------------------------------------------- feedback
    async def submit_feedback(
        self,
        interview: Interview,
        *,
        interviewer_id: uuid.UUID,
        overall_rating: float,
        recommendation: InterviewRecommendation,
        technical_skills: int | None = None,
        communication: int | None = None,
        problem_solving: int | None = None,
        domain_knowledge: int | None = None,
        culture_fit: int | None = None,
        strengths: str | None = None,
        weaknesses: str | None = None,
        comments: str | None = None,
        private_remarks: str | None = None,
        scorecard: dict[str, Any] | None = None,
        is_draft: bool = False,
    ) -> InterviewFeedback:
        participant_ids = {p.user_id for p in interview.participants if p.user_id}
        if interviewer_id not in participant_ids:
            raise PermissionDenied(
                "You can only submit feedback for interviews you are a participant in"
            )

        existing = await self.session.scalar(
            select(InterviewFeedback).where(
                InterviewFeedback.interview_id == interview.id,
                InterviewFeedback.interviewer_id == interviewer_id,
            )
        )
        if existing is not None and not existing.is_draft:
            raise DuplicateResource(
                "You have already submitted feedback for this interview",
                code="FEEDBACK_ALREADY_SUBMITTED",
            )

        feedback = existing or InterviewFeedback(
            company_id=self.company_id,
            interview_id=interview.id,
            application_id=interview.application_id,
            interviewer_id=interviewer_id,
        )
        feedback.overall_rating = overall_rating
        feedback.recommendation = recommendation
        feedback.technical_skills = technical_skills
        feedback.communication = communication
        feedback.problem_solving = problem_solving
        feedback.domain_knowledge = domain_knowledge
        feedback.culture_fit = culture_fit
        feedback.strengths = strengths
        feedback.weaknesses = weaknesses
        feedback.comments = comments
        feedback.private_remarks = private_remarks
        feedback.scorecard = scorecard or {}
        feedback.is_draft = is_draft
        feedback.submitted_at = None if is_draft else datetime.now(UTC)

        if existing is None:
            self.session.add(feedback)
        await self.session.flush()

        if is_draft:
            return feedback

        if interview.status != InterviewStatus.COMPLETED:
            interview.status = InterviewStatus.COMPLETED
            interview.completed_at = interview.completed_at or datetime.now(UTC)

        from app.modules.applications.service import ApplicationPipelineService

        pipeline = ApplicationPipelineService(self.session, self.company_id)
        application = interview.application
        await pipeline.add_timeline_event(
            application,
            event_type="FEEDBACK_SUBMITTED",
            title=f"Interview feedback submitted for {interview.title}",
            description=f"Recommendation: {recommendation.value.replace('_', ' ').title()}",
            actor_id=interviewer_id,
            visible_to_candidate=False,
            meta={"interview_id": str(interview.id), "rating": overall_rating},
        )

        await self.audit.record(
            action=AuditAction.CREATE,
            entity_type="InterviewFeedback",
            entity_id=feedback.id,
            company_id=self.company_id,
            actor_id=interviewer_id,
            summary=(
                f"Submitted feedback for {interview.title}: "
                f"{recommendation.value.replace('_', ' ').title()} ({overall_rating}/5)"
            ),
        )

        interviewer = await self.session.get(User, interviewer_id)
        self.events.collect(
            DomainEvent(
                name=Events.FEEDBACK_SUBMITTED,
                company_id=self.company_id,
                entity_type="Application",
                entity_id=interview.application_id,
                actor_id=interviewer_id,
                payload={
                    "feedback_id": str(feedback.id),
                    "interview_id": str(interview.id),
                    "job_id": str(interview.job_id),
                    "candidate_id": str(interview.candidate_id),
                    "candidate_name": application.candidate.full_name,
                    "interviewer_name": interviewer.full_name if interviewer else "An interviewer",
                    "interview_recommendation": recommendation.value,
                    "interview_rating": float(overall_rating),
                },
            )
        )
        await self.session.flush()
        logger.info(
            "feedback_submitted",
            interview_id=str(interview.id),
            recommendation=recommendation.value,
        )
        return feedback

    async def summarise_feedback(
        self, application_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> tuple[str, list[str], list[str], str | None, str]:
        """AI digest of every submitted feedback form for an application (s29).

        Returns ``(summary, strengths, weaknesses, consensus, engine)``. Advisory only -
        the recommendation of record stays each interviewer's own.
        """
        rows = (
            (
                await self.session.execute(
                    select(InterviewFeedback)
                    .where(
                        InterviewFeedback.application_id == application_id,
                        InterviewFeedback.company_id == self.company_id,
                        InterviewFeedback.is_draft.is_(False),
                    )
                    .order_by(InterviewFeedback.submitted_at)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            raise ResourceNotFound("Interview feedback", application_id)

        application = (
            (
                await self.session.execute(
                    select(Application)
                    .where(Application.id == application_id)
                    .options(
                        selectinload(Application.candidate), selectinload(Application.job)
                    )
                )
            )
            .unique()
            .scalar_one()
        )

        # Private remarks are deliberately excluded: they are the interviewer's own
        # working notes and must not be fed into a shared summary.
        items = [
            {
                "overall_rating": float(f.overall_rating),
                "recommendation": f.recommendation.value,
                "technical_skills": f.technical_skills,
                "communication": f.communication,
                "problem_solving": f.problem_solving,
                "domain_knowledge": f.domain_knowledge,
                "culture_fit": f.culture_fit,
                "strengths": f.strengths,
                "weaknesses": f.weaknesses,
                "comments": f.comments,
            }
            for f in rows
        ]

        ai = get_ai_provider()
        result = await ai.summarize_interview_feedback(
            feedback_items=items,
            candidate_name=application.candidate.full_name,
            job_title=application.job.title,
        )
        summary = result.value

        for feedback in rows:
            feedback.ai_summary = truncate(summary.summary, 4000)
            feedback.ai_summary_engine = result.usage.engine

        await self.audit.record_ai(
            feature="FEEDBACK_SUMMARY",
            engine=result.usage.engine,
            model=result.usage.model,
            company_id=self.company_id,
            user_id=actor_id,
            entity_type="Application",
            entity_id=application_id,
            input_digest={"feedback_count": len(items)},
            output_summary={
                "consensus": summary.consensus,
                "summary": truncate(summary.summary, 300),
            },
            latency_ms=result.usage.latency_ms,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            error=result.usage.error,
        )
        await self.session.flush()
        return (
            summary.summary,
            summary.strengths,
            summary.weaknesses,
            summary.consensus,
            result.usage.engine,
        )

    async def pending_feedback(
        self, *, interviewer_id: uuid.UUID | None = None
    ) -> list[Interview]:
        """Completed interviews with no submitted feedback yet."""
        submitted = select(InterviewFeedback.interview_id).where(
            InterviewFeedback.is_draft.is_(False)
        )
        if interviewer_id:
            submitted = submitted.where(InterviewFeedback.interviewer_id == interviewer_id)

        stmt = self.base_query().where(
            Interview.status == InterviewStatus.COMPLETED,
            Interview.id.not_in(submitted),
        )
        if interviewer_id:
            stmt = stmt.where(
                Interview.id.in_(
                    select(InterviewParticipant.interview_id).where(
                        InterviewParticipant.user_id == interviewer_id,
                        InterviewParticipant.role != "OBSERVER",
                    )
                )
            )
        stmt = stmt.order_by(Interview.scheduled_start.desc()).limit(100)
        return list((await self.session.execute(stmt)).unique().scalars().all())

    async def can_view(self, interview: Interview, principal: Any) -> bool:
        """Interviewers may only see interviews they are participating in."""
        from app.core.permissions import Perm

        if principal.has(Perm.INTERVIEW_READ):
            return True
        if principal.has(Perm.INTERVIEW_READ_ASSIGNED):
            return principal.id in {p.user_id for p in interview.participants}
        return False
