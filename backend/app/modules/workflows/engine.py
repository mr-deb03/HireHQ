"""Workflow execution engine.

A workflow is ``trigger -> conditions -> ordered steps``. The engine:

* de-duplicates runs with an idempotency key, so a redelivered event cannot double-fire;
* records why a run was skipped, not just that it was;
* contains step failures so one broken action does not abort the rest of the automation;
* refuses to let automation reject a candidate without a human in the loop (s19, s63).

That last rule is enforced in two places - here at execution time and in
``validate_steps`` at save time - because it is the one guarantee the product must not
lose to a configuration mistake.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ApplicationStatus,
    EmailTemplateKey,
    NotificationType,
    WorkflowActionType,
    WorkflowExecutionStatus,
)
from app.core.logging import get_logger
from app.models.application import Application
from app.models.workflow import Workflow, WorkflowExecution, WorkflowStep
from app.modules.workflows.conditions import (
    ConditionError,
    build_context,
    evaluate,
    validate_conditions,
)
from app.services.events import DomainEvent
from app.utils.text import truncate

logger = get_logger(__name__)

#: Statuses a workflow may never move an application into without explicit human
#: approval. Automation can shortlist; only a person can reject or hire.
HUMAN_ONLY_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.REJECTED,
        ApplicationStatus.HIRED,
        ApplicationStatus.OFFER,
    }
)

MAX_STEPS_PER_WORKFLOW = 20


class WorkflowValidationError(ValueError):
    pass


def validate_steps(steps: list[dict[str, Any]], *, requires_human_approval: bool) -> None:
    """Validate step configuration at save time."""
    if len(steps) > MAX_STEPS_PER_WORKFLOW:
        raise WorkflowValidationError(
            f"A workflow may have at most {MAX_STEPS_PER_WORKFLOW} steps"
        )

    for index, step in enumerate(steps):
        raw_action = step.get("action_type")
        try:
            action = WorkflowActionType(raw_action)
        except ValueError as exc:
            raise WorkflowValidationError(
                f"Step {index + 1}: unknown action {raw_action!r}"
            ) from exc

        config = step.get("config") or {}
        try:
            validate_conditions(step.get("conditions"))
        except ConditionError as exc:
            raise WorkflowValidationError(f"Step {index + 1}: {exc}") from exc

        if action == WorkflowActionType.CHANGE_STATUS:
            raw_status = config.get("status")
            try:
                status = ApplicationStatus(raw_status)
            except ValueError as exc:
                raise WorkflowValidationError(
                    f"Step {index + 1}: {raw_status!r} is not a valid application status"
                ) from exc
            if status in HUMAN_ONLY_STATUSES and not requires_human_approval:
                raise WorkflowValidationError(
                    f"Step {index + 1}: moving an application to {status.value} "
                    "automatically is not permitted. Enable 'requires human approval' on "
                    "this workflow so a person confirms the decision."
                )

        elif action == WorkflowActionType.SEND_EMAIL:
            raw_key = config.get("template_key")
            try:
                EmailTemplateKey(raw_key)
            except ValueError as exc:
                raise WorkflowValidationError(
                    f"Step {index + 1}: unknown email template {raw_key!r}"
                ) from exc

        elif action == WorkflowActionType.ADD_TO_TALENT_POOL:
            if not config.get("pool_name") and not config.get("pool_id"):
                raise WorkflowValidationError(
                    f"Step {index + 1}: specify pool_id or pool_name"
                )

        elif action == WorkflowActionType.ADD_TAG:
            if not config.get("tag"):
                raise WorkflowValidationError(f"Step {index + 1}: specify a tag")

        elif action == WorkflowActionType.DELAY:
            minutes = step.get("delay_minutes", 0)
            if not isinstance(minutes, int) or not 0 < minutes <= 60 * 24 * 30:
                raise WorkflowValidationError(
                    f"Step {index + 1}: delay must be between 1 minute and 30 days"
                )


class WorkflowEngine:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID) -> None:
        self.session = session
        self.company_id = company_id

    # ----------------------------------------------------------- entrypoint
    async def handle_event(self, event: DomainEvent) -> list[WorkflowExecution]:
        trigger = event.workflow_trigger
        if trigger is None:
            return []

        workflows = (
            (
                await self.session.execute(
                    select(Workflow)
                    .where(
                        Workflow.company_id == self.company_id,
                        Workflow.trigger == trigger,
                        Workflow.is_enabled.is_(True),
                    )
                    .order_by(Workflow.priority, Workflow.created_at)
                )
            )
            .unique()
            .scalars()
            .all()
        )
        if not workflows:
            return []

        executions: list[WorkflowExecution] = []
        for workflow in workflows:
            if workflow.job_ids:
                job_id = str(event.payload.get("job_id") or "")
                if job_id and job_id not in {str(j) for j in workflow.job_ids}:
                    continue
            execution = await self._run(workflow, event)
            if execution is not None:
                executions.append(execution)
        return executions

    async def _run(self, workflow: Workflow, event: DomainEvent) -> WorkflowExecution | None:
        key = event.idempotency_key(workflow.id)

        existing = await self.session.scalar(
            select(WorkflowExecution).where(WorkflowExecution.idempotency_key == key)
        )
        if existing is not None:
            logger.debug("workflow_already_ran", workflow=str(workflow.id), key=key)
            return None

        execution = WorkflowExecution(
            company_id=self.company_id,
            workflow_id=workflow.id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            idempotency_key=key,
            status=WorkflowExecutionStatus.RUNNING,
            trigger_context={k: str(v) for k, v in event.payload.items()},
            started_at=datetime.now(UTC),
        )
        self.session.add(execution)
        try:
            await self.session.flush()
        except IntegrityError:
            # Two workers raced on the same event; the other one won.
            await self.session.rollback()
            logger.debug("workflow_race_lost", workflow=str(workflow.id), key=key)
            return None

        try:
            context, entities = await self._load_context(event)
        except Exception as exc:
            logger.error("workflow_context_failed", workflow=str(workflow.id), error=str(exc))
            execution.status = WorkflowExecutionStatus.FAILED
            execution.error = truncate(str(exc), 2000)
            execution.completed_at = datetime.now(UTC)
            return execution

        outcome = evaluate(workflow.conditions, context)
        if not outcome.passed:
            execution.status = WorkflowExecutionStatus.SKIPPED
            execution.skip_reason = truncate(f"Conditions not met: {outcome.summary}", 500)
            execution.completed_at = datetime.now(UTC)
            logger.info(
                "workflow_skipped", workflow=workflow.name, reason=execution.skip_reason
            )
            return execution

        if workflow.requires_human_approval:
            execution.awaiting_approval = True
            execution.status = WorkflowExecutionStatus.PENDING
            execution.skip_reason = (
                "Waiting for human approval before its actions are applied."
            )
            execution.step_results = [
                {
                    "step": index,
                    "action": step.action_type.value,
                    "status": "PROPOSED",
                    "detail": self._describe_step(step),
                }
                for index, step in enumerate(workflow.steps)
                if step.is_enabled
            ]
            await self._notify_approval_required(workflow, execution, entities)
            logger.info("workflow_awaiting_approval", workflow=workflow.name)
            return execution

        await self._execute_steps(workflow, execution, context, entities)
        workflow.execution_count += 1
        workflow.last_executed_at = datetime.now(UTC)
        return execution

    async def approve(
        self, execution: WorkflowExecution, *, approved_by_id: uuid.UUID
    ) -> WorkflowExecution:
        """Apply a workflow that was held for human approval."""
        if not execution.awaiting_approval:
            from app.core.exceptions import BusinessRuleError

            raise BusinessRuleError("This workflow run is not awaiting approval")

        workflow = await self.session.get(Workflow, execution.workflow_id)
        if workflow is None:
            from app.core.exceptions import ResourceNotFound

            raise ResourceNotFound("Workflow", execution.workflow_id)

        event = DomainEvent(
            name=workflow.trigger.value,
            company_id=self.company_id,
            entity_type=execution.entity_type,
            entity_id=execution.entity_id,
            payload=execution.trigger_context,
            actor_id=approved_by_id,
        )
        context, entities = await self._load_context(event)

        execution.awaiting_approval = False
        execution.approved_by_id = approved_by_id
        execution.approved_at = datetime.now(UTC)
        execution.status = WorkflowExecutionStatus.RUNNING
        execution.skip_reason = None
        await self._execute_steps(
            workflow, execution, context, entities, actor_id=approved_by_id
        )
        workflow.execution_count += 1
        workflow.last_executed_at = datetime.now(UTC)
        return execution

    # ------------------------------------------------------------- internals
    async def _load_context(self, event: DomainEvent) -> tuple[dict[str, Any], dict[str, Any]]:
        """Materialise the entities and flat condition context for this event."""
        from sqlalchemy.orm import selectinload

        from app.models.ats import AtsScore
        from app.models.candidate import Candidate
        from app.models.job import Job

        entities: dict[str, Any] = {}
        application = None

        if event.entity_type == "Application":
            application = (
                (
                    await self.session.execute(
                        select(Application)
                        .where(
                            Application.id == event.entity_id,
                            Application.company_id == self.company_id,
                        )
                        .options(
                            selectinload(Application.candidate).selectinload(Candidate.skills),
                            selectinload(Application.job).selectinload(Job.skills),
                        )
                    )
                )
                .unique()
                .scalar_one_or_none()
            )

        if application is None:
            return build_context(event_payload=event.payload), entities

        entities["application"] = application
        entities["candidate"] = application.candidate
        entities["job"] = application.job

        latest_score = await self.session.scalar(
            select(AtsScore)
            .where(AtsScore.application_id == application.id)
            .order_by(AtsScore.created_at.desc())
            .limit(1)
        )
        entities["ats_score"] = latest_score

        context = build_context(
            application=application,
            candidate=application.candidate,
            job=application.job,
            ats_score=latest_score,
            event_payload=event.payload,
        )
        return context, entities

    async def _execute_steps(
        self,
        workflow: Workflow,
        execution: WorkflowExecution,
        context: dict[str, Any],
        entities: dict[str, Any],
        *,
        actor_id: uuid.UUID | None = None,
    ) -> None:
        results: list[dict[str, Any]] = []
        failed = False

        for index, step in enumerate(sorted(workflow.steps, key=lambda s: s.step_order)):
            if not step.is_enabled:
                results.append(
                    {"step": index, "action": step.action_type.value, "status": "DISABLED"}
                )
                continue

            gate = evaluate(step.conditions, context)
            if not gate.passed:
                results.append(
                    {
                        "step": index,
                        "action": step.action_type.value,
                        "status": "SKIPPED",
                        "detail": f"Step conditions not met: {gate.summary}",
                    }
                )
                continue

            try:
                detail = await self._execute_step(
                    step, workflow, entities, context, actor_id=actor_id
                )
                results.append(
                    {
                        "step": index,
                        "action": step.action_type.value,
                        "status": "COMPLETED",
                        "detail": truncate(detail, 500),
                    }
                )
            except Exception as exc:
                logger.error(
                    "workflow_step_failed",
                    workflow=workflow.name,
                    step=index,
                    action=step.action_type.value,
                    error=str(exc),
                    exc_info=True,
                )
                results.append(
                    {
                        "step": index,
                        "action": step.action_type.value,
                        "status": "FAILED",
                        "detail": truncate(str(exc), 500),
                    }
                )
                if not step.continue_on_error:
                    failed = True
                    break

        execution.step_results = results
        execution.status = (
            WorkflowExecutionStatus.FAILED if failed else WorkflowExecutionStatus.COMPLETED
        )
        execution.completed_at = datetime.now(UTC)
        logger.info(
            "workflow_executed",
            workflow=workflow.name,
            status=execution.status.value,
            steps=len(results),
        )

    async def _execute_step(
        self,
        step: WorkflowStep,
        workflow: Workflow,
        entities: dict[str, Any],
        context: dict[str, Any],
        *,
        actor_id: uuid.UUID | None = None,
    ) -> str:
        action = step.action_type
        config = step.config or {}
        application: Application | None = entities.get("application")

        if action == WorkflowActionType.CHANGE_STATUS:
            if application is None:
                raise ValueError("No application in context")
            status = ApplicationStatus(config["status"])
            if status in HUMAN_ONLY_STATUSES and not workflow.requires_human_approval:
                # Defence in depth: validate_steps already refuses this at save time, but
                # an older row or a direct database edit must not slip past.
                raise ValueError(
                    f"Refusing to move to {status.value} without human approval"
                )
            from app.modules.applications.service import ApplicationPipelineService

            service = ApplicationPipelineService(self.session, self.company_id)
            await service.change_status(
                application,
                new_status=status,
                actor_id=actor_id,
                actor_type="WORKFLOW" if actor_id is None else "USER",
                reason=f"Automated by workflow '{workflow.name}'",
                publish_events=False,
            )
            return f"Moved to {status.value}"

        if action == WorkflowActionType.SEND_EMAIL:
            if application is None:
                raise ValueError("No application in context")
            from app.models.company import Company
            from app.modules.emails.service import EmailService

            company = await self.session.get(Company, self.company_id)
            email_service = EmailService(self.session, self.company_id)
            variables = EmailService.build_variables(
                candidate=entities.get("candidate"),
                job=entities.get("job"),
                application=application,
                company=company,
                extra={"custom_message": config.get("custom_message", "")},
            )
            message = await email_service.send_templated(
                key=EmailTemplateKey(config["template_key"]),
                to=[entities["candidate"].email],
                variables=variables,
                application_id=application.id,
                candidate_id=application.candidate_id,
                job_id=application.job_id,
                is_automated=True,
            )
            # Report the true outcome into the execution log.
            return f"Email {config['template_key']}: {message.delivery_status.value}"

        if action == WorkflowActionType.NOTIFY:
            from app.modules.notifications.service import NotificationService

            service = NotificationService(self.session)
            recipients = await self._notification_recipients(entities, config)
            if not recipients:
                return "No recipients resolved"
            await service.create_many(
                user_ids=recipients,
                notification_type=NotificationType.WORKFLOW_ACTION,
                title=config.get("title", f"Workflow: {workflow.name}"),
                body=config.get("message", ""),
                company_id=self.company_id,
                entity_type="Application",
                entity_id=application.id if application else None,
                action_url=(
                    f"/recruiter/candidates/{application.candidate_id}" if application else None
                ),
            )
            return f"Notified {len(recipients)} user(s)"

        if action == WorkflowActionType.ADD_TAG:
            if application is None:
                raise ValueError("No application in context")
            tag = str(config["tag"])[:50]
            if tag not in application.tags:
                application.tags = [*application.tags, tag]
            return f"Tagged '{tag}'"

        if action == WorkflowActionType.FLAG_FOR_REVIEW:
            candidate = entities.get("candidate")
            if candidate is None:
                raise ValueError("No candidate in context")
            flag = {
                "code": config.get("code", "WORKFLOW_REVIEW"),
                "message": config.get("message", f"Flagged by workflow '{workflow.name}'"),
                "raised_at": datetime.now(UTC).isoformat(),
                "source": "WORKFLOW",
            }
            candidate.review_flags = [*(candidate.review_flags or []), flag]
            return "Raised a review flag"

        if action == WorkflowActionType.ADD_TO_TALENT_POOL:
            candidate = entities.get("candidate")
            if candidate is None:
                raise ValueError("No candidate in context")
            from app.modules.talent_pool.service import TalentPoolService

            service = TalentPoolService(self.session, self.company_id)
            pool = await service.get_or_create(
                pool_id=config.get("pool_id"), name=config.get("pool_name", "Automated")
            )
            added = await service.add_candidate(
                pool, candidate.id, note=f"Added by workflow '{workflow.name}'"
            )
            return f"{'Added to' if added else 'Already in'} pool '{pool.name}'"

        if action == WorkflowActionType.ASSIGN_RECRUITER:
            if application is None:
                raise ValueError("No application in context")
            recruiter_id = config.get("recruiter_id")
            if not recruiter_id:
                raise ValueError("No recruiter_id configured")
            application.assigned_recruiter_id = uuid.UUID(str(recruiter_id))
            return "Assigned a recruiter"

        if action == WorkflowActionType.CREATE_TASK:
            from app.modules.notifications.service import NotificationService

            service = NotificationService(self.session)
            recipients = await self._notification_recipients(entities, config)
            if not recipients:
                return "No assignee resolved"
            await service.create_many(
                user_ids=recipients,
                notification_type=NotificationType.WORKFLOW_ACTION,
                title=config.get("title", "Task from a workflow"),
                body=config.get("description", ""),
                company_id=self.company_id,
                priority="HIGH",
                entity_type="Application",
                entity_id=application.id if application else None,
                action_url=(
                    f"/recruiter/candidates/{application.candidate_id}" if application else None
                ),
                meta={"is_task": True, "workflow": workflow.name},
            )
            return f"Created a task for {len(recipients)} user(s)"

        if action == WorkflowActionType.DELAY:
            # Delays are honoured by scheduling the remainder of the workflow on the
            # queue. Without a worker there is nothing to resume it, so the step reports
            # that rather than silently sleeping and blocking the request.
            from app.workers.queue import get_queue

            queue = get_queue()
            if not queue.is_durable:
                return (
                    f"Delay of {step.delay_minutes} minute(s) skipped: no background "
                    "worker is configured, so deferred steps cannot be resumed."
                )
            await queue.enqueue_in(
                "resume_workflow",
                delay_seconds=step.delay_minutes * 60,
                workflow_id=str(workflow.id),
                step_order=step.step_order,
                entity_id=str(entities["application"].id) if application else None,
                company_id=str(self.company_id),
            )
            return f"Scheduled the remaining steps in {step.delay_minutes} minute(s)"

        raise ValueError(f"Unsupported action {action}")

    async def _notification_recipients(
        self, entities: dict[str, Any], config: dict[str, Any]
    ) -> list[uuid.UUID]:
        if explicit := config.get("user_ids"):
            return [uuid.UUID(str(u)) for u in explicit]

        application: Application | None = entities.get("application")
        recipients: list[uuid.UUID] = []
        if application is not None:
            if application.assigned_recruiter_id:
                recipients.append(application.assigned_recruiter_id)
            job = entities.get("job")
            if job is not None:
                if job.created_by_id:
                    recipients.append(job.created_by_id)
                if job.hiring_manager_id:
                    recipients.append(job.hiring_manager_id)
        return list(dict.fromkeys(recipients))

    async def _notify_approval_required(
        self, workflow: Workflow, execution: WorkflowExecution, entities: dict[str, Any]
    ) -> None:
        from app.modules.notifications.service import NotificationService

        service = NotificationService(self.session)
        recipients = await self._notification_recipients(entities, {})
        if not recipients:
            return
        await service.create_many(
            user_ids=recipients,
            notification_type=NotificationType.WORKFLOW_ACTION,
            title=f"Approval needed: {workflow.name}",
            body=(
                "An automated workflow has proposed actions that need your confirmation "
                "before they are applied."
            ),
            company_id=self.company_id,
            priority="HIGH",
            entity_type="WorkflowExecution",
            entity_id=execution.id,
            action_url="/recruiter/workflows",
            meta={"requires_approval": True},
        )

    @staticmethod
    def _describe_step(step: WorkflowStep) -> str:
        config = step.config or {}
        match step.action_type:
            case WorkflowActionType.CHANGE_STATUS:
                return f"Move the application to {config.get('status')}"
            case WorkflowActionType.SEND_EMAIL:
                return f"Send the '{config.get('template_key')}' email to the candidate"
            case WorkflowActionType.ADD_TAG:
                return f"Tag the application '{config.get('tag')}'"
            case WorkflowActionType.ADD_TO_TALENT_POOL:
                return f"Add the candidate to the '{config.get('pool_name')}' pool"
            case WorkflowActionType.NOTIFY:
                return config.get("title", "Send a notification")
            case WorkflowActionType.CREATE_TASK:
                return config.get("title", "Create a task")
            case WorkflowActionType.ASSIGN_RECRUITER:
                return "Assign a recruiter"
            case WorkflowActionType.FLAG_FOR_REVIEW:
                return "Raise a review flag on the candidate"
            case WorkflowActionType.DELAY:
                return f"Wait {step.delay_minutes} minute(s)"
        return step.action_type.value
