"""Application service layer used by MCP tools and the actor bridge."""

from __future__ import annotations

import re
from typing import Any, Protocol

from . import __version__
from .actor_bridge import ActorAccount
from .contracts import (
    AccountQuarantineReason,
    JobStatus,
    JobType,
    ProbeResult,
    SubmitVideoInput,
)
from .errors import ServiceError
from .jobs import VideoJobService
from .repository import SqliteRepository
from .scheduler import SchedulerService


class ServiceOperations(Protocol):
    async def probe(self) -> ProbeResult: ...

    async def find_active_account(self, email: str) -> ActorAccount | None: ...

    async def account_report(self, user_id: str) -> str: ...


class RecoveryJobOwner(Protocol):
    async def prepare_recovery_job(self) -> dict[str, Any]: ...


class Sub2APIService:
    def __init__(
        self,
        *,
        repository: SqliteRepository,
        operations: ServiceOperations,
        scheduler: SchedulerService,
        video: VideoJobService,
        video_enabled: bool = True,
        recovery_owner: RecoveryJobOwner | None = None,
    ) -> None:
        self.repository = repository
        self._operations = operations
        self._scheduler = scheduler
        self._video = video
        self._video_enabled = video_enabled
        self._recovery_owner = recovery_owner

    async def get_status(self) -> dict[str, Any]:
        job_counts = {
            job_type.value: await self.repository.active_job_count(job_type)
            for job_type in JobType
        }
        return {
            "version": __version__,
            "scheduler_enabled": await self._scheduler.is_enabled(),
            "active_jobs": job_counts,
            "account_quarantine_count": await self.repository.account_quarantine_count(),
            "account_quarantine_counts": {
                reason.value: await self.repository.account_quarantine_count(reason)
                for reason in AccountQuarantineReason
            },
        }

    async def probe_channels(self) -> dict[str, Any]:
        result = await self._operations.probe()
        return result.model_dump(mode="json", exclude_none=True)

    async def get_job(self, job_id: str) -> dict[str, Any]:
        job = await self.repository.get_job(job_id)
        if job is None:
            raise ServiceError("JOB_NOT_FOUND", "The job does not exist")
        return job.model_dump(mode="json")

    async def list_jobs(
        self,
        limit: int,
        cursor: str | None,
        job_type: JobType | None = None,
        status: JobStatus | None = None,
    ) -> dict[str, Any]:
        page = await self.repository.list_jobs(
            limit=limit,
            cursor=cursor,
            job_type=job_type,
            status=status,
        )
        return page.model_dump(mode="json")

    async def get_bound_account(self, actor_key: str) -> dict[str, Any]:
        binding = await self.repository.get_binding(self._validate_actor_key(actor_key))
        if binding is None:
            raise ServiceError("ACCOUNT_NOT_BOUND", "No account is bound to this actor key")
        return {
            "masked_email": binding.masked_email,
            "bound_at": binding.bound_at.isoformat(),
        }

    async def list_account_quarantines(
        self,
        limit: int = 20,
        cursor: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        try:
            parsed_reason = (
                AccountQuarantineReason(reason) if reason is not None else None
            )
        except ValueError as exc:
            raise ServiceError(
                "VALIDATION_ERROR",
                "The account quarantine reason is invalid",
            ) from exc
        page = await self.repository.list_account_quarantines(
            limit=limit,
            cursor=cursor,
            reason=parsed_reason,
        )
        return page.model_dump(mode="json")

    async def set_scheduler_enabled(self, enabled: bool) -> dict[str, bool]:
        await self._scheduler.set_enabled(enabled)
        return {"enabled": enabled}

    async def submit_control_job(self, job_type: JobType) -> dict[str, Any]:
        if job_type not in {JobType.RECOVERY, JobType.MAINTENANCE}:
            raise ValueError("unsupported control job type")
        if job_type is JobType.RECOVERY:
            if self._recovery_owner is None:
                raise ServiceError(
                    "ACCOUNT_RECOVERY_ADAPTER_UNAVAILABLE",
                    "Guardian account recovery is unavailable",
                )
            payload = await self._recovery_owner.prepare_recovery_job()
        else:
            payload = {}
        created = await self.repository.create_job_with_capacity(
            job_type, payload, max_active=1
        )
        if created is None:
            raise ServiceError("JOB_ALREADY_ACTIVE", "A job of this type is already active")
        job, queue_count = created
        return {"job": job.model_dump(mode="json"), "queue_count": queue_count}

    async def bind_account(self, actor_key: str, email: str) -> dict[str, Any]:
        key = self._validate_actor_key(actor_key)
        account = await self._operations.find_active_account(email)
        if account is None or account.status != "active":
            raise ServiceError(
                "ACCOUNT_NOT_BINDABLE", "The account does not exist or is not active"
            )
        binding = await self.repository.bind_actor(
            key, account.user_id, account.email_masked
        )
        return {
            "masked_email": binding.masked_email,
            "bound_at": binding.bound_at.isoformat(),
        }

    async def unbind_account(self, actor_key: str) -> dict[str, bool]:
        await self.repository.unbind_actor(self._validate_actor_key(actor_key))
        return {"unbound": True}

    async def submit_video(self, request: SubmitVideoInput) -> dict[str, Any]:
        if not self._video_enabled:
            raise ServiceError("VIDEO_DISABLED", "Video generation is disabled")
        submission = await self._video.submit(request)
        return submission.model_dump(mode="json")

    async def cancel_job(self, job_id: str) -> dict[str, Any]:
        return (await self.repository.cancel_job(job_id)).model_dump(mode="json")

    async def audit(
        self, principal: str, action: str, subject: str | None, outcome: str
    ) -> None:
        await self.repository.audit(principal, action, subject, outcome)

    @staticmethod
    def _validate_actor_key(value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"v1:[0-9a-f]{64}", normalized):
            raise ServiceError("ACTOR_KEY_INVALID", "The actor key is invalid")
        return normalized
