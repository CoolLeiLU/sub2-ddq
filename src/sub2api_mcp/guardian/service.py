"""Guardian application service and safe background direct scheduler."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ..contracts import JobRecord, JobType
from ..errors import ServiceError
from ..logging import log_event
from ..metrics import Metrics
from ..repository import SqliteRepository
from .account_recovery import AccountRecoveryExecutor, AccountRecoveryOperations
from .contracts import (
    AccountRecoveryOwner,
    AccountRecoveryResult,
    AccountRecoveryRunStatus,
    AccountRecoveryRunTrigger,
    ChannelPolicyOverride,
    GroupPolicyOverride,
    GuardianAccountRecoveryRun,
    GuardianPolicy,
    ManualControl,
)
from .engine import GuardianEngine
from .model_plaza import ModelPlazaOperations, ModelPlazaRefresher
from .repository import GuardianRepository

_RETENTION_INTERVAL = timedelta(minutes=10)
_RETENTION_BATCH_SIZE = 20_000
_RETENTION_TOTAL_KEYS = frozenset({"processed_total", "deleted_total"})


def _sqlite_database_bytes(path: Path) -> int:
    return sum(
        candidate.stat().st_size
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
        if candidate.exists()
    )


def _merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(
                cast(dict[str, Any], merged[key]),
                cast(dict[str, Any], value),
            )
        else:
            merged[key] = value
    return merged


class GuardianService:
    def __init__(
        self,
        repository: GuardianRepository,
        engine: GuardianEngine,
        metrics: Metrics | None = None,
        primary_repository: SqliteRepository | None = None,
        account_operations: AccountRecoveryOperations | None = None,
        plaza_operations: ModelPlazaOperations | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.engine = engine
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._logger = logging.getLogger("sub2api_mcp.guardian")
        self._metrics = metrics
        self._primary_repository = primary_repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._account_recovery = (
            AccountRecoveryExecutor(repository, account_operations, clock=self._clock)
            if account_operations is not None
            else None
        )
        self._model_plaza = (
            ModelPlazaRefresher(repository, plaza_operations, clock=self._clock)
            if plaza_operations is not None
            else None
        )
        self._metered_account_recovery_run_ids: set[str] = set()
        self._last_retention_at: datetime | None = None
        self._recovery_metric_requests = 0
        self._recovery_metric_tokens = 0
        self._recovery_metric_blocked = 0

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="guardian-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        self._wake.set()
        await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                policy = await self.repository.get_policy()
                await asyncio.wait_for(self._wake.wait(), timeout=policy.scan_interval_seconds)
                self._wake.clear()
                if self._stop.is_set():
                    break
            except TimeoutError:
                pass
            if self._stop.is_set():
                break
            now = self._clock()
            await self._run_retention_if_due(now=now)
            try:
                policy = await self.repository.get_policy()
                if policy.enabled:
                    slot = int(now.timestamp()) // policy.scan_interval_seconds
                    await self.run_once(dry_run=False, idempotency_key=f"scheduled:{slot}")
            except Exception:
                self._logger.exception("guardian_scheduled_cycle_failed")

    async def get_policy(self) -> dict[str, Any]:
        policy = await self.repository.get_policy()
        return {
            "policy": policy.model_dump(mode="json"),
            "defaults": GuardianPolicy().model_dump(mode="json"),
            "scheduling_enabled": policy.enabled,
        }

    async def update_policy(
        self, patch: dict[str, Any], *, expected_revision: int
    ) -> dict[str, Any]:
        deprecated = {"observe_only", "auto_apply", "rollout"}.intersection(patch)
        if deprecated:
            raise ServiceError(
                "DEPRECATED_GUARDIAN_CONTROL",
                "Observe mode and rollout controls were removed; update enabled instead",
            )
        current = await self.repository.get_policy()
        merged = _merge_dict(current.model_dump(mode="json"), patch)
        merged["revision"] = current.revision
        try:
            candidate = GuardianPolicy.model_validate(merged)
        except ValidationError:
            raise
        saved = await self.repository.update_policy(candidate, expected_revision=expected_revision)
        self._wake.set()
        await self.repository.add_event(
            event_type="POLICY_UPDATED",
            severity="INFO",
            message=f"Guardian policy revision {saved.revision} saved",
            details={"revision": saved.revision},
        )
        return {
            "policy": saved.model_dump(mode="json"),
            "scheduling_enabled": saved.enabled,
        }

    async def overview(self) -> dict[str, Any]:
        return await self.repository.overview()

    async def status(self) -> dict[str, Any]:
        policy = await self.repository.get_policy()
        runs = await self.repository.list_runs(limit=1)
        return {
            "enabled": policy.enabled,
            "background_task_running": self._task is not None and not self._task.done(),
            "scan_interval_seconds": policy.scan_interval_seconds,
            "last_run": runs[0] if runs else None,
        }

    async def set_scheduling_enabled(
        self,
        *,
        enabled: bool,
        confirm: bool,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not confirm:
            raise ServiceError(
                "CONFIRMATION_REQUIRED",
                "Scheduling start or stop requires confirm=true",
            )
        if not 1 <= len(idempotency_key) <= 128:
            raise ServiceError(
                "IDEMPOTENCY_KEY_REQUIRED",
                "A bounded idempotency key is required",
            )
        subject = "enabled" if enabled else "disabled"
        saved = await self.repository.get_idempotent_result(
            idempotency_key,
            "guardian_set_scheduling",
            subject,
        )
        if saved is not None:
            return saved
        current = await self.repository.get_policy()
        updated = current.model_copy(update={"enabled": enabled})
        policy = await self.repository.update_policy(
            updated,
            expected_revision=expected_revision,
        )
        result = {
            "enabled": policy.enabled,
            "policy_revision": policy.revision,
        }
        await self.repository.add_event(
            event_type="SCHEDULING_STARTED" if enabled else "SCHEDULING_STOPPED",
            severity="WARNING",
            message=(
                "Guardian direct scheduling started"
                if enabled
                else "Guardian direct scheduling stopped"
            ),
            details={"enabled": enabled, "revision": policy.revision},
        )
        await self.repository.save_idempotent_result(
            idempotency_key,
            "guardian_set_scheduling",
            subject,
            result,
        )
        return result

    async def recovery_status(self, *, limit: int = 20) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ServiceError("VALIDATION_ERROR", "limit must be between 1 and 100")
        policy = await self.repository.get_policy()
        episodes = await self.repository.list_open_channel_error_episodes(limit=limit)
        runs = await self.repository.list_account_recovery_runs(limit=limit)
        latest_active_check = await self.repository.latest_account_recovery_run(
            AccountRecoveryRunTrigger.HOURLY_ACTIVE_CHECK
        )
        return {
            "enabled": policy.enabled,
            "owner": policy.account_recovery.owner.value,
            "trigger": policy.account_recovery.trigger.value,
            "retry_cooldown_seconds": policy.account_recovery.retry_cooldown_seconds,
            "active_check": {
                "enabled": policy.probe.enabled,
                "interval_seconds": policy.probe.interval_seconds,
                "template": "channel_monitor_primary_model",
                "model_source": "channel_monitor.primary_model",
                "last_run_at": (
                    latest_active_check.started_at.isoformat()
                    if latest_active_check is not None
                    else None
                ),
            },
            "latest_abnormal_snapshot": (await self.repository.latest_abnormal_account_snapshot()),
            "open_episodes": [
                {
                    "episode_id": item.episode_id,
                    "channel_id": item.channel_id,
                    "group_id": item.group_id,
                    "opened_snapshot_id": item.opened_snapshot_id,
                    "opened_at": item.opened_at.isoformat(),
                }
                for item in episodes
            ],
            "recent_runs": [item.model_dump(mode="json") for item in runs],
        }

    async def recovery_run(self, run_id: str) -> dict[str, Any]:
        run = await self.repository.get_account_recovery_run(run_id)
        if run is None:
            raise ServiceError(
                "ACCOUNT_RECOVERY_RUN_NOT_FOUND",
                "The account recovery run does not exist",
            )
        results = await self.repository.list_account_recovery_results(run_id)
        return {
            "run": run.model_dump(mode="json"),
            "results": [item.model_dump(mode="json") for item in results],
        }

    async def submit_pending_recovery(
        self,
        *,
        confirm: bool,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not confirm:
            raise ServiceError(
                "CONFIRMATION_REQUIRED",
                "Manual account recovery requires confirm=true",
            )
        if not 1 <= len(idempotency_key) <= 128:
            raise ServiceError(
                "IDEMPOTENCY_KEY_REQUIRED",
                "A bounded idempotency key is required",
            )
        saved = await self.repository.get_idempotent_result(
            idempotency_key,
            "guardian_submit_recovery",
            "pending",
        )
        if saved is not None:
            return saved
        if self._primary_repository is None:
            raise ServiceError(
                "ACCOUNT_RECOVERY_ADAPTER_UNAVAILABLE",
                "Durable recovery jobs are unavailable",
            )
        payload = await self.prepare_recovery_job()
        created = await self._primary_repository.create_job_with_capacity(
            JobType.RECOVERY,
            payload,
            max_active=1,
        )
        if created is None:
            raise ServiceError(
                "JOB_ALREADY_ACTIVE",
                "A recovery job is already active",
            )
        job, queue_count = created
        result = {
            "job": job.model_dump(mode="json"),
            "queue_count": queue_count,
        }
        await self.repository.save_idempotent_result(
            idempotency_key,
            "guardian_submit_recovery",
            "pending",
            result,
        )
        return result

    async def run_once(
        self, *, dry_run: bool, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        started = time.monotonic()
        mode = "dry_run" if dry_run else "requested_apply"
        status = "failed"
        try:
            result = await self.engine.run_once(dry_run=dry_run, idempotency_key=idempotency_key)
            status = str(result.get("status", "unknown")).casefold()
            # A dry run is an evaluation-only operation.  Account recovery
            # performs real upstream mutations (disable/restore), so it must
            # never run as a side effect of a read-only Guardian evaluation.
            if not dry_run:
                await self._run_conditional_account_recovery(result)
            await self._after_run_operations(result)
            return result
        finally:
            if self._metrics is not None:
                self._metrics.guardian_runs.labels(status=status, mode=mode).inc()
                self._metrics.guardian_duration.labels(mode=mode).observe(
                    time.monotonic() - started
                )

    async def execute_account_recovery(
        self,
        *,
        snapshot_id: str,
        trigger: AccountRecoveryRunTrigger,
        episode_id: str | None = None,
        channel_id: str | None = None,
        group_id: str | None = None,
        already_processed_account_ids: frozenset[str] = frozenset(),
    ) -> GuardianAccountRecoveryRun:
        if self._account_recovery is None:
            raise ServiceError(
                "ACCOUNT_RECOVERY_ADAPTER_UNAVAILABLE",
                "Guardian account recovery operations are unavailable",
            )
        policy = await self.repository.get_policy()
        if not policy.enabled:
            raise ServiceError(
                "GUARDIAN_DISABLED",
                "Guardian scheduling is disabled",
            )
        scope = policy.scope
        monitored_group_ids = await self.repository.monitored_group_ids_for_snapshot(
            snapshot_id,
            excluded_channel_ids=scope.excluded_channel_ids,
            excluded_group_ids=scope.excluded_group_ids,
        )
        if monitored_group_ids is None:
            raise ServiceError(
                "GUARDIAN_MONITORED_SCOPE_UNAVAILABLE",
                "The monitored channel scope is unavailable for this account snapshot",
            )
        if scope.managed_group_mode == "selected":
            monitored_group_ids = frozenset(scope.managed_group_ids)
        monitored_group_ids -= scope.excluded_group_ids
        run = await self._account_recovery.execute(
            snapshot_id=snapshot_id,
            trigger=trigger,
            policy=policy.account_recovery,
            policy_revision=policy.revision,
            monitored_group_ids=monitored_group_ids,
            episode_id=episode_id,
            channel_id=channel_id,
            group_id=group_id,
            quarantined_account_ids=await self._quarantined_account_ids(),
            already_processed_account_ids=already_processed_account_ids,
            probe_interval_seconds=policy.probe.interval_seconds,
            probe_model=policy.probe.model,
            probe_prompt=policy.probe.prompt,
        )
        records = await self.repository.list_account_recovery_results(run.run_id)
        if (
            run.status is not AccountRecoveryRunStatus.RUNNING
            and self._metrics is not None
            and run.run_id not in self._metered_account_recovery_run_ids
        ):
            allowed_results = {item.value for item in AccountRecoveryResult}
            for record in records:
                if (
                    run.trigger is AccountRecoveryRunTrigger.HOURLY_ACTIVE_CHECK
                    and record.reason == "healthy_no_change"
                ):
                    continue
                if record.result.value in allowed_results:
                    self._metrics.guardian_account_recovery_results.labels(
                        result=record.result.value
                    ).inc()
            self._metered_account_recovery_run_ids.add(run.run_id)
        return run

    async def prepare_recovery_job(self) -> dict[str, Any]:
        policy = await self.repository.get_policy()
        if (
            not policy.enabled
            or not policy.account_recovery.enabled
            or policy.account_recovery.owner is not AccountRecoveryOwner.GUARDIAN
        ):
            raise ServiceError(
                "ACCOUNT_RECOVERY_NOT_GUARDIAN_OWNED",
                "Guardian account recovery is not enabled and owned by Guardian",
            )
        snapshot_id = await self.repository.latest_abnormal_account_snapshot()
        if snapshot_id is not None:
            return {
                "snapshot_id": snapshot_id,
                "trigger": AccountRecoveryRunTrigger.BAD_ACCOUNT_STATE.value,
            }
        episode = await self.repository.latest_open_channel_error_episode()
        if episode is not None and episode.group_id is not None:
            return {
                "snapshot_id": episode.opened_snapshot_id,
                "trigger": AccountRecoveryRunTrigger.CHANNEL_ERROR.value,
                "episode_id": episode.episode_id,
                "channel_id": episode.channel_id,
                "group_id": episode.group_id,
            }
        raise ServiceError(
            "NO_ABNORMAL_ACCOUNT_SNAPSHOT",
            "The latest account snapshot has no recoverable abnormal accounts",
        )

    async def handle_recovery(self, job: JobRecord) -> dict[str, Any]:
        if job.job_type is not JobType.RECOVERY:
            raise ValueError("Guardian can only handle recovery jobs")
        payload = job.payload
        raw_snapshot_id = payload.get("snapshot_id")
        raw_trigger = payload.get("trigger")
        if (
            not isinstance(raw_snapshot_id, str)
            or len(raw_snapshot_id) != 64
            or any(character not in "0123456789abcdef" for character in raw_snapshot_id)
            or not isinstance(raw_trigger, str)
        ):
            raise ServiceError("INVALID_RECOVERY_JOB", "The recovery job payload is invalid")
        try:
            trigger = AccountRecoveryRunTrigger(raw_trigger)
        except ValueError as exc:
            raise ServiceError(
                "INVALID_RECOVERY_JOB",
                "The recovery job trigger is invalid",
            ) from exc
        if trigger is AccountRecoveryRunTrigger.MANUAL:
            raise ServiceError(
                "INVALID_RECOVERY_JOB",
                "Manual recovery jobs must resolve to conditional evidence first",
            )
        episode_id = payload.get("episode_id")
        channel_id = payload.get("channel_id")
        group_id = payload.get("group_id")
        if trigger is AccountRecoveryRunTrigger.CHANNEL_ERROR and not all(
            isinstance(value, str) and value for value in (episode_id, channel_id, group_id)
        ):
            raise ServiceError(
                "INVALID_RECOVERY_JOB",
                "The channel-error recovery job is incomplete",
            )
        run = await self.execute_account_recovery(
            snapshot_id=raw_snapshot_id,
            trigger=trigger,
            episode_id=cast(str | None, episode_id),
            channel_id=cast(str | None, channel_id),
            group_id=cast(str | None, group_id),
        )
        return {"recovery_run": run.model_dump(mode="json")}

    async def _run_conditional_account_recovery(
        self,
        guardian_run: dict[str, Any],
    ) -> None:
        if self._account_recovery is None or guardian_run.get("status") != "SUCCEEDED":
            return
        result = cast(dict[str, Any], guardian_run.get("result") or {})
        snapshot_id = result.get("snapshot_id")
        if not isinstance(snapshot_id, str):
            return
        policy = await self.repository.get_policy()
        if (
            not policy.enabled
            or not policy.account_recovery.enabled
            or policy.account_recovery.owner is not AccountRecoveryOwner.GUARDIAN
        ):
            return
        processed: set[str] = set()
        completed_runs: list[GuardianAccountRecoveryRun] = []
        raw_value = result.get("account_recovery_triggers")
        raw_triggers = cast(list[object], raw_value) if isinstance(raw_value, list) else []
        for raw_value in raw_triggers:
            if not isinstance(raw_value, dict):
                continue
            raw = cast(dict[str, object], raw_value)
            episode_id = raw.get("episode_id")
            channel_id = raw.get("channel_id")
            group_id = raw.get("group_id")
            if not all(isinstance(value, str) for value in (episode_id, channel_id, group_id)):
                continue
            run = await self.execute_account_recovery(
                snapshot_id=snapshot_id,
                trigger=AccountRecoveryRunTrigger.CHANNEL_ERROR,
                episode_id=cast(str, episode_id),
                channel_id=cast(str, channel_id),
                group_id=cast(str, group_id),
                already_processed_account_ids=frozenset(processed),
            )
            completed_runs.append(run)
            records = await self.repository.list_account_recovery_results(run.run_id)
            processed.update(item.account_id for item in records if item.tested)
        bad_state_run = await self.execute_account_recovery(
            snapshot_id=snapshot_id,
            trigger=AccountRecoveryRunTrigger.BAD_ACCOUNT_STATE,
            already_processed_account_ids=frozenset(processed),
        )
        completed_runs.append(bad_state_run)
        result["account_recovery_runs"] = [item.model_dump(mode="json") for item in completed_runs]

    async def _hourly_active_check_due(self, *, interval_seconds: int) -> bool:
        latest = await self.repository.latest_account_recovery_run(
            AccountRecoveryRunTrigger.HOURLY_ACTIVE_CHECK
        )
        if latest is None:
            return True
        if latest.status in {
            AccountRecoveryRunStatus.FAILED,
            AccountRecoveryRunStatus.INTERRUPTED,
        }:
            return True
        if latest.status is AccountRecoveryRunStatus.RUNNING:
            return False
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("Guardian clock must be timezone-aware")
        return (now.astimezone(UTC) - latest.started_at).total_seconds() >= interval_seconds

    async def _quarantined_account_ids(self) -> frozenset[str]:
        if self._primary_repository is None:
            return frozenset()
        account_ids: set[str] = set()
        cursor: str | None = None
        for _ in range(100):
            page = await self._primary_repository.list_account_quarantines(
                limit=100,
                cursor=cursor,
            )
            account_ids.update(item.account_id for item in page.items)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        else:
            raise ServiceError(
                "QUARANTINE_SCAN_LIMIT_REACHED",
                "The quarantine registry exceeds the safe scan limit",
            )
        intents = await self._primary_repository.list_account_quarantine_intents(limit=10_000)
        account_ids.update(item.account_id for item in intents)
        return frozenset(account_ids)

    async def _after_run_operations(self, run: dict[str, Any]) -> None:
        try:
            await self._refresh_v2_metrics(run)
            await self._check_recovery_budget_alert()
            await self._refresh_model_plaza_if_due(run)
            await self._run_retention_if_due(now=datetime.now(UTC))
        except Exception:
            self._logger.exception(
                "guardian_post_run_operations_failed",
                extra={"runId": run.get("run_id")},
            )

    async def _refresh_model_plaza_if_due(self, run: dict[str, Any]) -> None:
        if self._model_plaza is None or run.get("status") != "SUCCEEDED":
            return
        result = cast(dict[str, Any], run.get("result") or {})
        if result.get("requested_dry_run"):
            return
        snapshot_id = result.get("snapshot_id")
        if not isinstance(snapshot_id, str):
            return
        policy = await self.repository.get_policy()
        if not policy.enabled or not policy.model_plaza.enabled:
            return
        scope = policy.scope
        monitored_group_ids = await self.repository.monitored_group_ids_for_snapshot(
            snapshot_id,
            excluded_channel_ids=scope.excluded_channel_ids,
            excluded_group_ids=scope.excluded_group_ids,
        )
        if monitored_group_ids is None:
            return
        if scope.managed_group_mode == "selected":
            monitored_group_ids = frozenset(scope.managed_group_ids)
        monitored_group_ids -= scope.excluded_group_ids
        await self._model_plaza.refresh_if_due(
            snapshot_id=snapshot_id,
            monitored_group_ids=monitored_group_ids,
            refresh_times=policy.model_plaza.refresh_times,
        )

    async def _run_retention_if_due(self, *, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("retention schedule time must be timezone-aware")
        if (
            self._last_retention_at is not None
            and now - self._last_retention_at < _RETENTION_INTERVAL
        ):
            return
        self._last_retention_at = now
        started = time.monotonic()
        stores: tuple[tuple[str, GuardianRepository | SqliteRepository], ...] = (
            (("guardian", self.repository),)
            if self._primary_repository is None
            else (
                ("guardian", self.repository),
                ("primary", self._primary_repository),
            )
        )
        processed_total = 0
        deleted_total = 0
        try:
            for store, repository in stores:
                result = await repository.cleanup_retention(
                    now=now,
                    batch_size=_RETENTION_BATCH_SIZE,
                )
                processed_total += int(result.get("processed_total", 0))
                deleted_total += int(result.get("deleted_total", 0))
                if self._metrics is not None:
                    for operation, raw_count in result.items():
                        if operation in _RETENTION_TOTAL_KEYS:
                            continue
                        count = int(raw_count)
                        if count > 0:
                            self._metrics.retention_rows.labels(
                                store=store,
                                operation=operation,
                            ).inc(count)
            database_bytes = _sqlite_database_bytes(self.repository.path)
            if self._metrics is not None:
                self._metrics.retention_runs.labels(status="success").inc()
                self._metrics.database_size_bytes.set(database_bytes)
            log_event(
                self._logger,
                logging.INFO,
                "guardian_retention_completed",
                "scheduled retention completed",
                processedRows=processed_total,
                deletedRows=deleted_total,
                databaseBytes=database_bytes,
                durationMs=round((time.monotonic() - started) * 1000),
            )
        except Exception:
            if self._metrics is not None:
                self._metrics.retention_runs.labels(status="failed").inc()
            self._logger.exception(
                "scheduled retention failed",
                extra={
                    "event": "guardian_retention_failed",
                    "durationMs": round((time.monotonic() - started) * 1000),
                },
            )

    async def _refresh_v2_metrics(self, run: dict[str, Any]) -> None:
        if self._metrics is None:
            return
        result = cast(dict[str, Any], run.get("result") or {})
        replayed = bool(run.get("idempotent_replay"))
        if result.get("snapshot_id") and not replayed:
            self._metrics.guardian_shared_snapshots.labels(status="consumed").inc()
        elif result.get("no_new_evidence") and not replayed:
            self._metrics.guardian_shared_snapshots.labels(status="empty").inc()
        duplicates = int(result.get("duplicate_observations") or 0)
        if duplicates and not replayed:
            self._metrics.guardian_duplicate_observations.labels(source="SHARED_MONITOR").inc(
                duplicates
            )
        traffic_processed = int(result.get("traffic_buckets_processed") or 0)
        if traffic_processed and not replayed:
            self._metrics.guardian_traffic_buckets.labels(status="fused").inc(traffic_processed)
        sampling = await self.repository.sampling_status()
        latest = sampling.get("latest_snapshot_at")
        if latest:
            captured = datetime.fromisoformat(str(latest).replace("Z", "+00:00"))
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=UTC)
            self._metrics.guardian_snapshot_age_seconds.set(
                max(0, (datetime.now(UTC) - captured).total_seconds())
            )
        for state, count in cast(
            dict[str, int], sampling.get("channels_by_freshness") or {}
        ).items():
            self._metrics.guardian_channels_by_freshness.labels(state=state).set(count)
        channels = await self.repository.list_channels(limit=200)
        confidence_values = [
            float(channel.get("confidence") or 0)
            for channel in cast(list[dict[str, Any]], channels.get("items") or [])
        ]
        self._metrics.guardian_channel_confidence_min.set(min(confidence_values, default=0))
        self._metrics.guardian_channel_confidence_average.set(
            sum(confidence_values) / len(confidence_values) if confidence_values else 0
        )
        budget = await self.probe_budget()
        requests = int(budget["request_count"])
        tokens = int(budget["total_tokens"])
        blocked = int(budget["blocked_count"])
        if requests > self._recovery_metric_requests:
            self._metrics.guardian_recovery_probe_requests.labels(result="completed").inc(
                requests - self._recovery_metric_requests
            )
        if blocked > self._recovery_metric_blocked:
            self._metrics.guardian_recovery_probe_requests.labels(result="blocked").inc(
                blocked - self._recovery_metric_blocked
            )
        if tokens > self._recovery_metric_tokens:
            self._metrics.guardian_recovery_probe_tokens.labels(priced="unknown").inc(
                tokens - self._recovery_metric_tokens
            )
        self._recovery_metric_requests = requests
        self._recovery_metric_tokens = tokens
        self._recovery_metric_blocked = blocked

    async def _check_recovery_budget_alert(self) -> None:
        policy = await self.repository.get_policy()
        if not policy.recovery_budget.enabled:
            return
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        usage = await self.repository.recovery_probe_budget_summary(now.date())
        request_ratio = float(usage["request_count"]) / policy.recovery_budget.daily_requests
        token_ratio = float(usage["total_tokens"]) / policy.recovery_budget.daily_tokens
        ratio = max(request_ratio, token_ratio)
        if ratio < 0.8:
            return
        exhausted = ratio >= 1
        event_type = "RECOVERY_BUDGET_EXHAUSTED" if exhausted else "RECOVERY_BUDGET_WARNING"
        existing = await self.repository.list_events(limit=20, event_type=event_type)
        for event in cast(list[dict[str, Any]], existing.get("items") or []):
            created = datetime.fromisoformat(str(event["created_at"]).replace("Z", "+00:00"))
            if created.astimezone(ZoneInfo("Asia/Shanghai")).date() == now.date():
                return
        await self.repository.add_event(
            event_type=event_type,
            severity="ERROR" if exhausted else "WARNING",
            message=(
                "Guardian recovery probe budget exhausted"
                if exhausted
                else "Guardian recovery probe budget reached 80 percent"
            ),
            details={
                "request_count": usage["request_count"],
                "daily_requests": policy.recovery_budget.daily_requests,
                "total_tokens": usage["total_tokens"],
                "daily_tokens": policy.recovery_budget.daily_tokens,
            },
        )

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        return await self.repository.cancel_run(run_id)

    async def list_groups(self) -> dict[str, Any]:
        policy = await self.repository.get_policy()
        excluded = policy.scope.excluded_group_ids
        items = await self.repository.list_groups()
        for item in items:
            item["excluded"] = item["group_id"] in excluded
        return {"items": items}

    async def update_group_policy(self, group_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        validated = GroupPolicyOverride.model_validate(patch)
        data = validated.model_dump(mode="json", exclude_none=True)
        saved = await self.repository.upsert_group_override(group_id, data)
        await self.repository.add_event(
            event_type="GROUP_POLICY_UPDATED",
            severity="INFO",
            group_id=group_id,
            message=f"Group {group_id} override updated",
            details=data,
        )
        return saved

    async def delete_group_policy(self, group_id: str) -> dict[str, bool]:
        await self.repository.delete_group_override(group_id)
        await self.repository.add_event(
            event_type="GROUP_POLICY_CLEARED",
            severity="INFO",
            group_id=group_id,
            message=f"Group {group_id} now inherits the global policy",
        )
        return {"deleted": True}

    async def list_channels(
        self,
        *,
        limit: int,
        cursor: str | None,
        group_id: str | None,
        health: str | None,
        query: str | None,
    ) -> dict[str, Any]:
        return await self.repository.list_channels(
            limit=limit,
            cursor=cursor,
            group_id=group_id,
            health=health,
            query=query,
        )

    async def get_channel(self, channel_id: str) -> dict[str, Any]:
        channel = await self.repository.get_channel(channel_id)
        if channel is None:
            raise ServiceError("CHANNEL_NOT_FOUND", "The Guardian channel does not exist")
        channel["samples"] = [
            sample.model_dump(mode="json")
            for sample in await self.repository.list_samples(channel_id, limit=60)
        ]
        return channel

    async def update_channel(self, channel_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        channel = await self.repository.get_channel(channel_id)
        if channel is None:
            raise ServiceError("CHANNEL_NOT_FOUND", "The Guardian channel does not exist")
        current = await self.repository.get_channel_override(channel_id)
        base = (
            current.model_dump(mode="json")
            if current is not None
            else ChannelPolicyOverride().model_dump(mode="json")
        )
        candidate = ChannelPolicyOverride.model_validate({**base, **patch})
        await self.repository.upsert_channel_override(channel_id, candidate)
        await self.repository.add_event(
            event_type="CHANNEL_OVERRIDE_UPDATED",
            severity="INFO",
            channel_id=channel_id,
            group_id=cast(str | None, channel["group_id"]),
            message="Channel scheduling override updated",
            details={"fields": sorted(patch)},
        )
        saved = await self.repository.get_channel(channel_id)
        assert saved is not None
        return saved

    async def channel_action(
        self,
        channel_id: str,
        action: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        normalized = action.strip().casefold()
        controls = {
            "pause": ManualControl.PAUSED,
            "resume": ManualControl.NONE,
            "exclude": ManualControl.EXCLUDED,
            "include": ManualControl.NONE,
            "fuse": ManualControl.FUSED,
            "recover": ManualControl.NONE,
        }
        if normalized == "probe":
            return await self.run_once(
                dry_run=True,
                idempotency_key=idempotency_key or f"probe:{channel_id}",
            )
        if normalized not in controls:
            raise ServiceError("INVALID_CHANNEL_ACTION", "The channel action is invalid")
        channel = await self.repository.set_manual_control(channel_id, controls[normalized])
        await self.repository.add_event(
            event_type=f"CHANNEL_{normalized.upper()}",
            severity="WARNING" if normalized in {"pause", "exclude", "fuse"} else "INFO",
            channel_id=channel_id,
            group_id=cast(str | None, channel["group_id"]),
            message=f"Manual channel action: {normalized}",
            details={"idempotency_key_present": bool(idempotency_key)},
        )
        return channel

    async def list_events(
        self,
        *,
        limit: int,
        cursor: str | None,
        event_type: str | None,
        severity: str | None,
    ) -> dict[str, Any]:
        return await self.repository.list_events(
            limit=limit,
            cursor=cursor,
            event_type=event_type,
            severity=severity,
        )

    async def probe_spend(self) -> dict[str, Any]:
        return await self.repository.probe_spend()

    async def sampling_status(self) -> dict[str, Any]:
        policy = await self.repository.get_policy()
        status = await self.repository.sampling_status()
        return {
            **status,
            "mode": policy.sampling.mode.value,
            "fresh_seconds": policy.sampling.fresh_seconds,
            "expire_seconds": policy.sampling.expire_seconds,
        }

    async def channel_explanation(self, channel_id: str) -> dict[str, Any]:
        channel = await self.repository.get_channel(channel_id)
        if channel is None:
            raise ServiceError("CHANNEL_NOT_FOUND", "The Guardian channel does not exist")
        return {
            "channel_id": channel_id,
            "health": channel["health"],
            "score": channel["score"],
            "confidence": channel["confidence"],
            "freshness_state": channel["freshness_state"],
            "last_evidence_at": channel["last_evidence_at"],
            "warmup_buckets": channel["warmup_buckets"],
            "reason": channel["details"].get("reason"),
            "evidence_sources": channel["details"].get("evidence_sources", []),
            "short_score": channel["details"].get("short_score"),
            "long_score": channel["details"].get("long_score"),
            "expected_action": channel["details"].get("expected_action"),
        }

    async def probe_budget(self) -> dict[str, Any]:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        policy = await self.repository.get_policy()
        usage = await self.repository.recovery_probe_budget_summary(now.date())
        return {
            **usage,
            "daily_request_limit": policy.recovery_budget.daily_requests,
            "daily_token_limit": policy.recovery_budget.daily_tokens,
            "enabled": policy.recovery_budget.enabled,
        }
