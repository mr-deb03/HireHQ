"""Background job queue abstraction.

Two implementations:

* ``RedisQueue`` (ARQ) - the production path. Durable, survives a restart, supports
  delayed jobs and is processed by ``app.workers.worker``.
* ``InlineQueue`` - runs the job as an asyncio task in the API process. This makes local
  development work with no infrastructure, but it is **not durable**: it reports
  ``is_durable = False`` so callers that need real deferral (workflow delays, interview
  reminders) can say so instead of pretending the work was scheduled.

Both share one task registry, so a task is defined once and runs identically either way.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger, job_id_ctx

logger = get_logger(__name__)

TaskFunc = Callable[..., Awaitable[Any]]

#: name -> coroutine. Populated by ``app.workers.tasks`` at import.
TASK_REGISTRY: dict[str, TaskFunc] = {}


def task(name: str) -> Callable[[TaskFunc], TaskFunc]:
    """Register a coroutine as a background task."""

    def decorator(func: TaskFunc) -> TaskFunc:
        if name in TASK_REGISTRY:
            raise RuntimeError(f"Background task {name!r} is already registered")
        TASK_REGISTRY[name] = func
        return func

    return decorator


class JobQueue(ABC):
    name: str = "abstract"
    #: True when the queue survives a process restart and can honour delays.
    is_durable: bool = False

    @abstractmethod
    async def enqueue(self, task_name: str, **kwargs: Any) -> str | None: ...

    @abstractmethod
    async def enqueue_in(
        self, task_name: str, *, delay_seconds: int, **kwargs: Any
    ) -> str | None: ...

    async def health(self) -> dict[str, Any]:
        return {"queue": self.name, "durable": self.is_durable}


class InlineQueue(JobQueue):
    """Executes tasks in-process. Development default."""

    name = "inline"
    is_durable = False

    def __init__(self) -> None:
        #: Strong references, so a task is not garbage-collected mid-flight.
        self._tasks: set[asyncio.Task] = set()

    def _resolve(self, task_name: str) -> TaskFunc:
        func = TASK_REGISTRY.get(task_name)
        if func is None:
            raise KeyError(
                f"Unknown background task {task_name!r}. "
                f"Registered: {', '.join(sorted(TASK_REGISTRY)) or 'none'}"
            )
        return func

    async def enqueue(self, task_name: str, **kwargs: Any) -> str | None:
        func = self._resolve(task_name)

        async def _run() -> None:
            token = job_id_ctx.set(f"inline:{task_name}")
            try:
                await func(**kwargs)
            except Exception as exc:
                logger.error(
                    "background_task_failed", task=task_name, error=str(exc), exc_info=True
                )
            finally:
                job_id_ctx.reset(token)

        try:
            running = asyncio.create_task(_run())
        except RuntimeError:
            # No event loop (e.g. a synchronous script): run it to completion instead of
            # dropping the work on the floor.
            await _run()
            return None

        self._tasks.add(running)
        running.add_done_callback(self._tasks.discard)
        return None

    async def enqueue_in(
        self, task_name: str, *, delay_seconds: int, **kwargs: Any
    ) -> str | None:
        func = self._resolve(task_name)

        async def _run_later() -> None:
            try:
                await asyncio.sleep(delay_seconds)
                await func(**kwargs)
            except asyncio.CancelledError:
                logger.warning("delayed_task_cancelled", task=task_name)
                raise
            except Exception as exc:
                logger.error(
                    "background_task_failed", task=task_name, error=str(exc), exc_info=True
                )

        try:
            running = asyncio.create_task(_run_later())
        except RuntimeError:
            logger.warning("delayed_task_dropped", task=task_name, reason="no event loop")
            return None
        self._tasks.add(running)
        running.add_done_callback(self._tasks.discard)
        return None

    async def drain(self, timeout: float = 30.0) -> None:
        """Wait for in-flight tasks. Used by tests to make async work deterministic."""
        if not self._tasks:
            return
        await asyncio.wait(set(self._tasks), timeout=timeout)


class RedisQueue(JobQueue):
    """ARQ-backed durable queue."""

    name = "redis"
    is_durable = True

    def __init__(self) -> None:
        self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            from arq import create_pool
            from arq.connections import RedisSettings

            self._pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
        return self._pool

    async def enqueue(self, task_name: str, **kwargs: Any) -> str | None:
        pool = await self._get_pool()
        job = await pool.enqueue_job(task_name, **kwargs)
        return job.job_id if job else None

    async def enqueue_in(
        self, task_name: str, *, delay_seconds: int, **kwargs: Any
    ) -> str | None:
        from datetime import timedelta

        pool = await self._get_pool()
        job = await pool.enqueue_job(
            task_name, _defer_by=timedelta(seconds=delay_seconds), **kwargs
        )
        return job.job_id if job else None

    async def health(self) -> dict[str, Any]:
        try:
            pool = await self._get_pool()
            await pool.ping()
            return {"queue": self.name, "durable": True, "status": "connected"}
        except Exception as exc:
            return {"queue": self.name, "durable": True, "status": f"unreachable: {exc}"}

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None


_queue: JobQueue | None = None


def get_queue() -> JobQueue:
    global _queue
    if _queue is None:
        # Importing the task module here populates TASK_REGISTRY before first use.
        import app.workers.tasks  # noqa: F401

        if settings.USE_REDIS_QUEUE:
            _queue = RedisQueue()
            logger.info("queue_selected", queue="redis", url=settings.REDIS_URL.split("@")[-1])
        else:
            _queue = InlineQueue()
            logger.info(
                "queue_selected",
                queue="inline",
                note="Background work runs in-process and does not survive a restart.",
            )
    return _queue


def reset_queue() -> None:
    global _queue
    _queue = None
