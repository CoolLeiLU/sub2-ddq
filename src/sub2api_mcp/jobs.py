"""Durable job submission and worker orchestration."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from .contracts import JobRecord, JobType
from .errors import ServiceError
from .logging import log_event
from .metrics import Metrics
from .repository import SqliteRepository

JobHandler = Callable[[JobRecord], Awaitable[dict[str, Any]]]


class JobManager:
    def __init__(self, repository: SqliteRepository, metrics: Metrics) -> None:
        self._repository = repository
        self._metrics = metrics
        self._logger = logging.getLogger("sub2api_mcp")
        self._handlers: dict[JobType, JobHandler] = {}
        self._stop = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()

    def register(self, job_type: JobType, handler: JobHandler) -> None:
        if job_type in self._handlers:
            raise ValueError(f"handler already registered for {job_type.value}")
        self._handlers[job_type] = handler

    async def run_once(self, allowed_types: set[JobType], worker_id: str) -> bool:
        job = await self._repository.claim_next_job(allowed_types, worker_id)
        if job is None:
            return False
        handler = self._handlers.get(job.job_type)
        if handler is None:
            await self._repository.fail_job(
                job.job_id,
                "JOB_HANDLER_MISSING",
                "No handler is registered for this job type",
            )
            return True
        try:
            result = await handler(job)
            current = await self._repository.get_job(job.job_id)
            if current is not None and current.cancel_requested:
                finished = await self._repository.mark_running_job_cancelled(job.job_id)
            else:
                finished = await self._repository.complete_job(job.job_id, result)
        except ServiceError as exc:
            finished = await self._repository.fail_job(
                job.job_id, exc.code, exc.safe_message
            )
        except Exception:
            finished = await self._repository.fail_job(
                job.job_id,
                "INTERNAL_ERROR",
                "The job failed unexpectedly",
            )
        self._metrics.job_transitions.labels(
            job_type=job.job_type.value, status=finished.status.value
        ).inc()
        queue_depth = await self._repository.active_job_count(job.job_type)
        self._metrics.job_queue_depth.labels(job_type=job.job_type.value).set(queue_depth)
        log_event(
            self._logger,
            logging.INFO if finished.status.value == "SUCCEEDED" else logging.WARNING,
            "job_finished",
            jobId=job.job_id,
            jobType=job.job_type.value,
            status=finished.status.value,
            errorCode=finished.error_code,
            queueDepth=queue_depth,
        )
        return True

    async def start(self, *, control_workers: int = 1) -> None:
        self._stop.clear()
        control_types = {JobType.PROBE, JobType.RECOVERY, JobType.MAINTENANCE}
        for _ in range(control_workers):
            self._spawn_worker(control_types, "control")

    def _spawn_worker(self, job_types: set[JobType], prefix: str) -> None:
        worker_id = f"{prefix}-{uuid.uuid4()}"
        task = asyncio.create_task(self._worker_loop(job_types, worker_id), name=worker_id)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _worker_loop(self, job_types: set[JobType], worker_id: str) -> None:
        retry_delay = 0.25
        while not self._stop.is_set():
            try:
                handled = await self.run_once(job_types, worker_id)
                retry_delay = 0.25
            except asyncio.CancelledError:
                raise
            except Exception:
                # A transient SQLite or upstream error must not silently kill the
                # only control worker.  Keep the worker alive and back off so a
                # locked database does not become a tight retry loop.
                self._logger.exception(
                    "job_worker_iteration_failed",
                    extra={"workerId": worker_id},
                )
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=retry_delay)
                retry_delay = min(retry_delay * 2, 10.0)
                continue
            if not handled:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=0.25)

    async def stop(self) -> None:
        self._stop.set()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
