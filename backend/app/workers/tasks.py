"""Background tasks.

Each task owns its own database session and commits independently, because it runs
outside any HTTP request. Events raised inside a task are flushed after that commit, so
downstream automation only ever sees committed state.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.enums import EmailTemplateKey, InterviewStatus, OfferStatus, ResumeStatus
from app.core.logging import get_logger
from app.db.session import session_scope
from app.workers.queue import task

logger = get_logger(__name__)


@task("process_resume")
async def process_resume(*, resume_id: str, company_id: str, application_id: str | None = None):
    """Parse a resume, then score the application it belongs to.

    This is the spine of the intake pipeline: resume -> structured profile -> ATS score
    -> workflow evaluation. Each stage commits before the next begins so a failure late
    in the chain does not discard earlier work.
    """
    resume_uuid = uuid.UUID(resume_id)
    company_uuid = uuid.UUID(company_id)

    from app.modules.resumes.service import ResumeService

    async with session_scope() as session:
        service = ResumeService(session, company_uuid)
        try:
            await service.process(resume_uuid)
        except Exception as exc:
            logger.error("process_resume_failed", resume_id=resume_id, error=str(exc))
            return {"status": "failed", "error": str(exc)}

    if application_id:
        await score_application(application_id=application_id, company_id=company_id)
    return {"status": "completed", "resume_id": resume_id}


@task("score_application")
async def score_application(*, application_id: str, company_id: str):
    """Run the ATS engine and release the resulting event to the workflow engine."""
    from app.modules.ats.service import AtsService

    application_uuid = uuid.UUID(application_id)
    company_uuid = uuid.UUID(company_id)

    async with session_scope() as session:
        service = AtsService(session, company_uuid)
        try:
            score = await service.score(application_uuid)
        except Exception as exc:
            logger.error("score_application_failed", application_id=application_id, error=str(exc))
            return {"status": "failed", "error": str(exc)}
        events = service.events

    # Flushed only after the enclosing session committed.
    await events.flush()
    return {"status": "completed", "score": float(score.overall_score)}


@task("rescore_job")
async def rescore_job(*, job_id: str, company_id: str, actor_id: str | None = None):
    from app.modules.ats.service import AtsService

    async with session_scope() as session:
        service = AtsService(session, uuid.UUID(company_id))
        result = await service.rescore_job(
            uuid.UUID(job_id), actor_id=uuid.UUID(actor_id) if actor_id else None
        )
    logger.info("job_rescored", job_id=job_id, **result)
    return result


@task("send_interview_reminders")
async def send_interview_reminders(*, offsets_minutes: list[int] | None = None):
    """Send interview reminders at the configured offsets.

    Runs on a schedule. Idempotent: each interview records which offsets have already
    fired, so a re-run - or overlapping schedules - cannot send the same reminder twice.
    """
    from app.models.company import Company
    from app.models.interview import Interview
    from app.modules.emails.service import EmailService

    offsets = sorted(offsets_minutes or [1440, 60], reverse=True)
    now = datetime.now(UTC)
    sent = 0

    async with session_scope() as session:
        horizon = now + timedelta(minutes=max(offsets) + 15)
        interviews = (
            (
                await session.execute(
                    select(Interview)
                    .where(
                        Interview.scheduled_start > now,
                        Interview.scheduled_start <= horizon,
                        Interview.status.in_(
                            [InterviewStatus.SCHEDULED, InterviewStatus.CONFIRMED]
                        ),
                    )
                    .limit(500)
                )
            )
            .unique()
            .scalars()
            .all()
        )

        for interview in interviews:
            minutes_away = (interview.scheduled_start - now).total_seconds() / 60
            already = set(interview.reminders_sent or [])

            # Fire the largest offset the interview has just passed under.
            due = next(
                (o for o in offsets if o not in already and minutes_away <= o),
                None,
            )
            if due is None:
                continue

            application = interview.application
            candidate = application.candidate
            job = application.job
            company = await session.get(Company, interview.company_id)

            service = EmailService(session, interview.company_id)
            variables = EmailService.build_variables(
                candidate=candidate,
                job=job,
                application=application,
                company=company,
                interview=interview,
            )
            await service.send_templated(
                key=EmailTemplateKey.INTERVIEW_REMINDER,
                to=[candidate.email],
                variables=variables,
                application_id=application.id,
                candidate_id=candidate.id,
                job_id=job.id,
                is_automated=True,
            )
            interview.reminders_sent = [*already, due]
            sent += 1

    logger.info("interview_reminders_processed", sent=sent, offsets=offsets)
    return {"reminders_sent": sent}


@task("expire_offers")
async def expire_offers():
    """Mark offers past their expiry as EXPIRED so the pipeline reflects reality."""
    from app.models.offer import Offer

    now = datetime.now(UTC)
    expired = 0
    async with session_scope() as session:
        offers = (
            (
                await session.execute(
                    select(Offer).where(
                        Offer.status.in_([OfferStatus.SENT, OfferStatus.VIEWED]),
                        Offer.expires_at.is_not(None),
                        Offer.expires_at <= now,
                    )
                )
            )
            .scalars()
            .all()
        )
        for offer in offers:
            offer.status = OfferStatus.EXPIRED
            expired += 1
    logger.info("offers_expired", count=expired)
    return {"expired": expired}


@task("send_offer_reminders")
async def send_offer_reminders(*, days_before: int = 2):
    """Remind candidates whose offer is close to expiring."""
    from app.models.company import Company
    from app.models.offer import Offer
    from app.modules.emails.service import EmailService

    now = datetime.now(UTC)
    window_end = now + timedelta(days=days_before)
    sent = 0

    async with session_scope() as session:
        offers = (
            (
                await session.execute(
                    select(Offer).where(
                        Offer.status.in_([OfferStatus.SENT, OfferStatus.VIEWED]),
                        Offer.expires_at.is_not(None),
                        Offer.expires_at > now,
                        Offer.expires_at <= window_end,
                    )
                )
            )
            .scalars()
            .all()
        )
        for offer in offers:
            from app.models.candidate import Candidate

            candidate = await session.get(Candidate, offer.candidate_id)
            company = await session.get(Company, offer.company_id)
            if candidate is None:
                continue
            service = EmailService(session, offer.company_id)
            variables = EmailService.build_variables(
                candidate=candidate, company=company, offer=offer
            )
            await service.send_templated(
                key=EmailTemplateKey.OFFER_REMINDER,
                to=[candidate.email],
                variables=variables,
                candidate_id=candidate.id,
                is_automated=True,
            )
            sent += 1
    logger.info("offer_reminders_sent", count=sent)
    return {"reminders_sent": sent}


@task("close_expired_jobs")
async def close_expired_jobs():
    """Close published jobs whose application deadline has passed."""
    from datetime import date

    from app.core.enums import JobStatus
    from app.models.job import Job

    closed = 0
    async with session_scope() as session:
        jobs = (
            (
                await session.execute(
                    select(Job).where(
                        Job.status == JobStatus.PUBLISHED,
                        Job.application_deadline.is_not(None),
                        Job.application_deadline < date.today(),
                    )
                )
            )
            .scalars()
            .all()
        )
        for job in jobs:
            job.status = JobStatus.CLOSED
            job.closed_at = datetime.now(UTC)
            closed += 1
    logger.info("expired_jobs_closed", count=closed)
    return {"closed": closed}


@task("retry_failed_resumes")
async def retry_failed_resumes(*, max_attempts: int = 3):
    """Retry resumes whose processing failed transiently."""
    from app.models.resume import Resume

    retried = 0
    async with session_scope() as session:
        resumes = (
            (
                await session.execute(
                    select(Resume)
                    .where(
                        Resume.status == ResumeStatus.FAILED,
                        Resume.processing_attempts < max_attempts,
                    )
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        targets = [(str(r.id), str(r.company_id)) for r in resumes]

    from app.workers.queue import get_queue

    queue = get_queue()
    for resume_id, company_id in targets:
        await queue.enqueue("process_resume", resume_id=resume_id, company_id=company_id)
        retried += 1
    logger.info("failed_resumes_requeued", count=retried)
    return {"requeued": retried}


@task("resume_workflow")
async def resume_workflow(
    *, workflow_id: str, step_order: int, entity_id: str | None, company_id: str
):
    """Continue a workflow whose DELAY step has elapsed."""
    from app.models.workflow import Workflow
    from app.modules.workflows.engine import WorkflowEngine
    from app.services.events import DomainEvent

    if not entity_id:
        return {"status": "skipped", "reason": "no entity"}

    async with session_scope() as session:
        workflow = await session.get(Workflow, uuid.UUID(workflow_id))
        if workflow is None or not workflow.is_enabled:
            return {"status": "skipped", "reason": "workflow unavailable"}

        engine = WorkflowEngine(session, uuid.UUID(company_id))
        event = DomainEvent(
            name=workflow.trigger.value,
            company_id=uuid.UUID(company_id),
            entity_type="Application",
            entity_id=uuid.UUID(entity_id),
            payload={"resumed_from_step": str(step_order)},
        )
        context, entities = await engine._load_context(event)

        from app.core.enums import WorkflowExecutionStatus
        from app.models.workflow import WorkflowExecution

        execution = WorkflowExecution(
            company_id=uuid.UUID(company_id),
            workflow_id=workflow.id,
            entity_type="Application",
            entity_id=uuid.UUID(entity_id),
            idempotency_key=f"{workflow_id}:{entity_id}:resume:{step_order}",
            status=WorkflowExecutionStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        session.add(execution)

        remaining = [s for s in workflow.steps if s.step_order > step_order]
        workflow.steps.clear()
        workflow.steps.extend(remaining)
        await engine._execute_steps(workflow, execution, context, entities)

    return {"status": "completed", "workflow_id": workflow_id}


@task("anonymise_expired_candidates")
async def anonymise_expired_candidates(*, batch_size: int = 100):
    """Anonymise candidate records whose retention period has elapsed (s49).

    Applications, scores and analytics rows survive - they carry no personal data once
    the candidate is anonymised - so historical reporting stays intact while the person
    is no longer identifiable.
    """
    from app.models.candidate import Candidate

    now = datetime.now(UTC)
    anonymised = 0
    async with session_scope() as session:
        candidates = (
            (
                await session.execute(
                    select(Candidate)
                    .where(
                        Candidate.retention_expires_at.is_not(None),
                        Candidate.retention_expires_at <= now,
                        Candidate.deleted_at.is_(None),
                    )
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )
        for candidate in candidates:
            token = uuid.uuid4().hex[:12]
            candidate.first_name = "Anonymised"
            candidate.last_name = f"Candidate {token}"
            candidate.email = f"anonymised+{token}@removed.invalid"
            candidate.phone = None
            candidate.location = None
            candidate.city = None
            candidate.photo_url = None
            candidate.date_of_birth = None
            candidate.linkedin_url = None
            candidate.github_url = None
            candidate.portfolio_url = None
            candidate.other_links = {}
            candidate.summary = None
            candidate.ai_summary = None
            candidate.deleted_at = now
            anonymised += 1
    logger.info("candidates_anonymised", count=anonymised)
    return {"anonymised": anonymised}


@task("sync_mailboxes")
async def sync_mailboxes(*, account_id: str | None = None):
    """Pull candidate replies from every connected mailbox.

    Runs on a schedule. Each account is synced in its own session so one broken
    connection cannot stop the others, and the per-account cursor makes overlapping runs
    safe.
    """
    from app.models.communication import EmailAccount
    from app.modules.emails.accounts import sync_account

    async with session_scope() as session:
        stmt = select(EmailAccount.id).where(EmailAccount.is_active.is_(True))
        if account_id:
            stmt = stmt.where(EmailAccount.id == uuid.UUID(account_id))
        account_ids = list((await session.execute(stmt)).scalars().all())

    if not account_ids:
        return {"accounts": 0, "imported": 0}

    imported = 0
    failures = 0
    for identifier in account_ids:
        async with session_scope() as session:
            account = await session.get(EmailAccount, identifier)
            if account is None:
                continue
            try:
                result = await sync_account(session, account)
                imported += result.messages_imported
                if not result.synced:
                    failures += 1
            except Exception as exc:
                failures += 1
                logger.warning(
                    "mailbox_sync_error", account_id=str(identifier), error=str(exc)[:200]
                )

    logger.info(
        "mailboxes_synced", accounts=len(account_ids), imported=imported, failures=failures
    )
    return {"accounts": len(account_ids), "imported": imported, "failures": failures}
