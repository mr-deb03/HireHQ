"""ARQ worker entrypoint.

Run with:  arq app.workers.worker.WorkerSettings

Processes the durable queue when ``USE_REDIS_QUEUE=true``. Also owns the recurring jobs
(interview reminders, offer expiry, retention) which have no natural HTTP trigger.
"""

from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

# Importing the task module registers every task.
import app.workers.tasks  # noqa: F401,E402
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.workers.queue import TASK_REGISTRY

logger = get_logger("worker")


def _wrap(name: str):
    """Adapt a task coroutine to ARQ's ``(ctx, **kwargs)`` calling convention.

    ARQ resolves jobs by function ``__name__``, so the wrapper must carry the task name.
    """
    func = TASK_REGISTRY[name]

    async def runner(ctx, **kwargs):
        job_id = ctx.get("job_id")
        logger.info("task_started", task=name, job_id=job_id)
        try:
            result = await func(**kwargs)
            logger.info("task_completed", task=name, job_id=job_id)
            return result
        except Exception as exc:
            logger.error("task_failed", task=name, job_id=job_id, error=str(exc), exc_info=True)
            raise

    runner.__name__ = name
    return runner


async def startup(ctx) -> None:
    configure_logging()
    logger.info(
        "worker_starting",
        tasks=sorted(TASK_REGISTRY),
        redis=settings.REDIS_URL.split("@")[-1],
    )


async def shutdown(ctx) -> None:
    from app.db.session import dispose_engine

    await dispose_engine()
    logger.info("worker_stopped")


class WorkerSettings:
    """ARQ configuration."""

    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    functions = [_wrap(name) for name in sorted(TASK_REGISTRY)]

    cron_jobs = [
        # Interview reminders: every 15 minutes. The task itself records which offsets
        # have fired per interview, so overlapping runs cannot double-send.
        cron(
            _wrap("send_interview_reminders"),
            minute={0, 15, 30, 45},
            run_at_startup=False,
        ),
        # Candidate replies: often enough to feel live, rarely enough to stay well
        # inside provider rate limits.
        cron(_wrap("sync_mailboxes"), minute={2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57}),
        # Offer housekeeping, once an hour.
        cron(_wrap("expire_offers"), minute=5),
        cron(_wrap("send_offer_reminders"), hour=9, minute=10),
        # Daily maintenance, off-peak.
        cron(_wrap("close_expired_jobs"), hour=1, minute=0),
        cron(_wrap("retry_failed_resumes"), hour=2, minute=0),
        cron(_wrap("anonymise_expired_candidates"), hour=3, minute=0),
    ]

    on_startup = startup
    on_shutdown = shutdown

    max_jobs = 20
    job_timeout = 600
    keep_result = 3600
    max_tries = 3
    health_check_interval = 60
