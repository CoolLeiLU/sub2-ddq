"""Versioned SQLite persistence with explicit transactional claims."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import asyncpg
from pydantic import ValidationError

from .contracts import (
    AccountBinding,
    AccountQuarantineIntent,
    AccountQuarantinePage,
    AccountQuarantineReason,
    AccountQuarantineRecord,
    AccountQuarantineRestoreIntent,
    JobPage,
    JobRecord,
    JobStatus,
    JobType,
    QuarantineProbeResult,
)
from .db import Database
from .db import rowcount as _rowcount
from .errors import ServiceError
from .schema import ACCOUNT_QUARANTINE_RESTORE_TABLE_SQL, SCHEMA_SQL
from .schema import SCHEMA_VERSION as CURRENT_SCHEMA_VERSION


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json_default(value: object) -> str:
    """Encode the values ``json.dumps`` rejects.

    Rows from ``TIMESTAMPTZ`` columns carry ``datetime`` objects under asyncpg
    where SQLite handed back text, so anything derived from a row — paging
    cursors, stored details, audit records — needs this hook.
    """

    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=_json_default,
    )


class SqliteRepository:
    SCHEMA_VERSION = CURRENT_SCHEMA_VERSION
    MAX_ACCOUNT_QUARANTINES = 10_000

    def __init__(self, database: Database, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._database = database
        self._clock = clock

    async def initialize(self) -> None:
        """Create the schema and mark interrupted work as resumable.

        The legacy SQLite repository upgraded an existing file through
        ``_current_schema_version`` plus three migration helpers.  A fresh
        PostgreSQL deployment always starts at the current shape, so only the
        restart reconciliation below is retained; historical rows move across
        through ``scripts/migrate_sqlite_to_postgres.py``.
        """

        now = self._clock()
        async with self._database.transaction() as connection:
            for statement in SCHEMA_SQL.split(";"):
                if statement.strip():
                    await connection.execute(statement)
            # Kept separate from SCHEMA_SQL: this table references
            # account_quarantines and must be created after it exists.
            for statement in ACCOUNT_QUARANTINE_RESTORE_TABLE_SQL.split(";"):
                if statement.strip():
                    await connection.execute(statement)
            await connection.execute(
                "INSERT INTO service_metadata(key, value) VALUES('schema_version', $1) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                str(self.SCHEMA_VERSION),
            )
            await connection.execute(
                "UPDATE jobs SET status = $1, error_code = $2, error_message = $3, "
                "updated_at = $4, finished_at = $5, worker_id = NULL "
                "WHERE status = $6",
                JobStatus.INTERRUPTED.value,
                "SERVICE_RESTARTED",
                "The service restarted while this job was running",
                now,
                now,
                JobStatus.RUNNING.value,
            )
            # Video generation was removed from the service; any job still
            # queued or running for it can never complete.
            await connection.execute(
                "UPDATE jobs SET status = $1, error_code = $2, error_message = $3, "
                "updated_at = $4, finished_at = $5, worker_id = NULL "
                "WHERE job_type = $6 AND status IN ($7, $8)",
                JobStatus.FAILED.value,
                "VIDEO_REMOVED",
                "Video generation is no longer supported",
                now,
                now,
                JobType.VIDEO.value,
                JobStatus.QUEUED.value,
                JobStatus.RUNNING.value,
            )

    async def create_job(self, job_type: JobType, payload: dict[str, Any]) -> JobRecord:
        job_id = str(uuid.uuid4())
        now = self._clock()
        async with self._database.acquire() as connection:
            await connection.execute(
                "INSERT INTO jobs(job_id, job_type, status, payload_json, created_at, updated_at) "
                "VALUES($1, $2, $3, $4, $5, $6)",
                job_id,
                job_type.value,
                JobStatus.QUEUED.value,
                _json(payload),
                now,
                now,
            )
            row = await connection.fetchrow("SELECT * FROM jobs WHERE job_id = $1", job_id)
        assert row is not None
        return self._job_from_row(row)

    async def create_job_with_capacity(
        self,
        job_type: JobType,
        payload: dict[str, Any],
        *,
        max_active: int,
    ) -> tuple[JobRecord, int] | None:
        job_id = str(uuid.uuid4())
        now = self._clock()
        async with self._database.transaction() as connection:
            active = int(
                await connection.fetchval(
                    "SELECT COUNT(*) FROM jobs WHERE job_type = $1 AND status IN ($2, $3)",
                    job_type.value,
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                )
                or 0
            )
            if active >= max_active:
                return None
            await connection.execute(
                "INSERT INTO jobs(job_id, job_type, status, payload_json, created_at, updated_at) "
                "VALUES($1, $2, $3, $4, $5, $6)",
                job_id,
                job_type.value,
                JobStatus.QUEUED.value,
                _json(payload),
                now,
                now,
            )
            row = await connection.fetchrow("SELECT * FROM jobs WHERE job_id = $1", job_id)
        if row is None:
            raise RuntimeError("job disappeared after insert")
        return self._job_from_row(row), active + 1

    async def active_job_count(self, job_type: JobType) -> int:
        async with self._database.acquire() as connection:
            value = await connection.fetchval(
                "SELECT COUNT(*) FROM jobs WHERE job_type = $1 AND status IN ($2, $3)",
                job_type.value,
                JobStatus.QUEUED.value,
                JobStatus.RUNNING.value,
            )
        return int(value or 0)

    async def get_job(self, job_id: str) -> JobRecord | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow("SELECT * FROM jobs WHERE job_id = $1", job_id)
        return self._job_from_row(row) if row is not None else None

    @staticmethod
    def _encode_cursor(created_at: datetime | str, job_id: str) -> str:
        """Encode a paging cursor.

        Two shapes share this helper: job cursors carry a timestamp, quarantine
        cursors carry a scope string. Both are JSON-encoded and base64url'd.
        """

        raw = _json([created_at, job_id]).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[str, str]:
        """Decode a paging cursor into its two raw string halves.

        The caller decides what the first half means: ``list_jobs`` parses it as
        a timestamp, ``list_account_quarantines`` reads it as a scope marker.
        """

        if len(cursor) > 4096:
            raise ServiceError("INVALID_CURSOR", "The cursor is invalid")
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            raw_value: object = json.loads(base64.urlsafe_b64decode(padded).decode())
            if not isinstance(raw_value, list):
                raise ValueError
            value = cast(list[object], raw_value)
            if len(value) != 2 or not all(isinstance(item, str) for item in value):
                raise ValueError
            return cast(str, value[0]), cast(str, value[1])
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise ServiceError("INVALID_CURSOR", "The job cursor is invalid") from exc

    @staticmethod
    def _cursor_timestamp(value: str) -> datetime:
        """Parse the timestamp half of a job cursor.

        asyncpg needs a datetime to bind against the TIMESTAMPTZ column; a bare
        string leaves the parameter type indeterminate and the query fails.
        """

        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    async def list_jobs(
        self,
        limit: int,
        cursor: str | None,
        job_type: JobType | None,
        status: JobStatus | None,
    ) -> JobPage:
        if not 1 <= limit <= 100:
            raise ServiceError("INVALID_PAGE_SIZE", "Job page size must be between 1 and 100")
        parameters: list[object] = []
        conditions: list[str] = []
        if job_type is not None:
            parameters.append(job_type.value)
            conditions.append(f"job_type = ${len(parameters)}")
        if status is not None:
            parameters.append(status.value)
            conditions.append(f"status = ${len(parameters)}")
        if cursor:
            encoded_time, job_id = self._decode_cursor(cursor)
            created_at = self._cursor_timestamp(encoded_time)
            parameters.extend((created_at, job_id))
            timestamp_index = len(parameters) - 1
            job_index = len(parameters)
            conditions.append(
                f"(created_at < ${timestamp_index} "
                f"OR (created_at = ${timestamp_index} AND job_id < ${job_index}))"
            )
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        parameters.append(limit + 1)
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT * FROM jobs {where} ORDER BY created_at DESC, job_id DESC "
                f"LIMIT ${len(parameters)}",
                *parameters,
            )
        has_more = len(rows) > limit
        selected = rows[:limit]
        next_cursor = None
        if has_more and selected:
            next_cursor = self._encode_cursor(selected[-1]["created_at"], selected[-1]["job_id"])
        return JobPage(items=[self._job_from_row(row) for row in selected], next_cursor=next_cursor)

    async def claim_next_job(self, job_types: set[JobType], worker_id: str) -> JobRecord | None:
        if not job_types:
            return None
        now = self._clock()
        values = sorted(item.value for item in job_types)
        # ``SKIP LOCKED`` lets concurrent workers each take a different queued
        # job, reproducing the serialization SQLite's write lock provided.
        async with self._database.transaction() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM jobs WHERE status = $1 AND job_type = ANY($2::text[]) "
                "ORDER BY created_at, job_id LIMIT 1 FOR UPDATE SKIP LOCKED",
                JobStatus.QUEUED.value,
                values,
            )
            if row is None:
                return None
            await connection.execute(
                "UPDATE jobs SET status = $1, worker_id = $2, started_at = $3, updated_at = $4 "
                "WHERE job_id = $5 AND status = $6",
                JobStatus.RUNNING.value,
                worker_id,
                now,
                now,
                row["job_id"],
                JobStatus.QUEUED.value,
            )
            claimed = await connection.fetchrow(
                "SELECT * FROM jobs WHERE job_id = $1", row["job_id"]
            )
        if claimed is None:
            raise RuntimeError("claimed job disappeared")
        return self._job_from_row(claimed)

    async def complete_job(self, job_id: str, result: dict[str, Any]) -> JobRecord:
        return await self._finish_job(job_id, JobStatus.SUCCEEDED, result, None, None)

    async def fail_job(self, job_id: str, error_code: str, message: str) -> JobRecord:
        return await self._finish_job(job_id, JobStatus.FAILED, None, error_code, message)

    async def _finish_job(
        self,
        job_id: str,
        status: JobStatus,
        result: dict[str, Any] | None,
        error_code: str | None,
        error_message: str | None,
    ) -> JobRecord:
        now = self._clock()
        async with self._database.acquire() as connection:
            status_text = await connection.execute(
                "UPDATE jobs SET status = $1, result_json = $2, error_code = $3, "
                "error_message = $4, updated_at = $5, finished_at = $6, worker_id = NULL "
                "WHERE job_id = $7 AND status = $8",
                status.value,
                _json(result) if result is not None else None,
                error_code,
                error_message,
                now,
                now,
                job_id,
                JobStatus.RUNNING.value,
            )
            if _rowcount(status_text) != 1:
                raise ServiceError("INVALID_JOB_STATE", "The job is not running")
            row = await connection.fetchrow("SELECT * FROM jobs WHERE job_id = $1", job_id)
        if row is None:
            raise RuntimeError("finished job disappeared")
        return self._job_from_row(row)

    async def cancel_job(self, job_id: str) -> JobRecord:
        now = self._clock()
        async with self._database.acquire() as connection:
            row = await connection.fetchrow("SELECT * FROM jobs WHERE job_id = $1", job_id)
            if row is None:
                raise ServiceError("JOB_NOT_FOUND", "The job does not exist")
            status = JobStatus(row["status"])
            if status is JobStatus.QUEUED:
                await connection.execute(
                    "UPDATE jobs SET status = $1, cancel_requested = 1, updated_at = $2, "
                    "finished_at = $3 WHERE job_id = $4",
                    JobStatus.CANCELLED.value,
                    now,
                    now,
                    job_id,
                )
            elif status is JobStatus.RUNNING:
                await connection.execute(
                    "UPDATE jobs SET cancel_requested = 1, updated_at = $1 WHERE job_id = $2",
                    now,
                    job_id,
                )
            row = await connection.fetchrow("SELECT * FROM jobs WHERE job_id = $1", job_id)
        assert row is not None
        return self._job_from_row(row)

    async def mark_running_job_cancelled(self, job_id: str) -> JobRecord:
        now = self._clock()
        async with self._database.acquire() as connection:
            updated = await connection.execute(
                "UPDATE jobs SET status = $1, cancel_requested = 1, updated_at = $2, "
                "finished_at = $3, worker_id = NULL WHERE job_id = $4 AND status = $5",
                JobStatus.CANCELLED.value,
                now,
                now,
                job_id,
                JobStatus.RUNNING.value,
            )
            if _rowcount(updated) != 1:
                raise ServiceError("INVALID_JOB_STATE", "The job is not running")
            row = await connection.fetchrow("SELECT * FROM jobs WHERE job_id = $1", job_id)
        assert row is not None
        return self._job_from_row(row)

    async def acquire_scheduler_lease(self, owner: str, *, lease_seconds: int) -> bool:
        now = self._clock().astimezone(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        async with self._database.transaction() as connection:
            row = await connection.fetchrow(
                "SELECT owner, expires_at FROM scheduler_lease WHERE singleton = 1 FOR UPDATE"
            )
            if row is not None and row["owner"] != owner and row["expires_at"] > now:
                return False
            await connection.execute(
                "INSERT INTO scheduler_lease(singleton, owner, expires_at) VALUES(1, $1, $2) "
                "ON CONFLICT(singleton) DO UPDATE SET owner = excluded.owner, "
                "expires_at = excluded.expires_at",
                owner,
                expires,
            )
        return True

    async def upsert_account_quarantine(
        self,
        record: AccountQuarantineRecord,
    ) -> AccountQuarantineRecord:
        async with self._database.transaction() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM account_quarantines WHERE account_id = $1 FOR UPDATE",
                record.account_id,
            )
            intent = await connection.fetchrow(
                "SELECT 1 FROM account_quarantine_intents WHERE account_id = $1",
                record.account_id,
            )
            if row is not None and intent is not None:
                raise ServiceError(
                    "QUARANTINE_DATA_INVALID",
                    "The account has conflicting quarantine states",
                )
            if intent is not None:
                raise ServiceError(
                    "QUARANTINE_TRANSITION_CONFLICT",
                    "The account has a pending quarantine transition",
                )
            if row is not None:
                return self._quarantine_from_row(row)
            count = int(
                await connection.fetchval(
                    "SELECT (SELECT COUNT(*) FROM account_quarantines) + "
                    "(SELECT COUNT(*) FROM account_quarantine_intents)"
                )
                or 0
            )
            if count >= self.MAX_ACCOUNT_QUARANTINES:
                raise ServiceError(
                    "QUARANTINE_CAPACITY_REACHED",
                    "The account quarantine registry is full",
                )
            await connection.execute(
                "INSERT INTO account_quarantines("
                "account_id, reason, group_ids_json, threshold_ms, observed_count, "
                "quarantined_at, last_probe_at, last_probe_latency_ms, "
                "last_probe_result, recovery_success_streak, updated_at"
                ") VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
                record.account_id,
                record.reason.value,
                _json(list(record.group_ids)),
                record.threshold_ms,
                record.observed_count,
                record.quarantined_at,
                record.last_probe_at if record.last_probe_at is not None else None,
                record.last_probe_latency_ms,
                record.last_probe_result.value,
                record.recovery_success_streak,
                self._clock(),
            )
            row = await connection.fetchrow(
                "SELECT * FROM account_quarantines WHERE account_id = $1",
                record.account_id,
            )
        if row is None:
            raise RuntimeError("quarantine row disappeared after insert")
        return self._quarantine_from_row(row)

    async def acquire_account_control_lease(
        self,
        owner: str,
        *,
        lease_seconds: int,
    ) -> bool:
        now = self._clock().astimezone(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        async with self._database.transaction() as connection:
            row = await connection.fetchrow(
                "SELECT owner, expires_at FROM account_control_lease WHERE singleton = 1 FOR UPDATE"
            )
            if row is not None and row["owner"] != owner and row["expires_at"] > now:
                return False
            await connection.execute(
                "INSERT INTO account_control_lease(singleton, owner, expires_at) "
                "VALUES(1, $1, $2) ON CONFLICT(singleton) DO UPDATE SET "
                "owner = excluded.owner, expires_at = excluded.expires_at",
                owner,
                expires,
            )
        return True

    async def release_account_control_lease(self, owner: str) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                "DELETE FROM account_control_lease WHERE singleton = 1 AND owner = $1",
                owner,
            )

    async def get_account_quarantine(
        self,
        account_id: str,
    ) -> AccountQuarantineRecord | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM account_quarantines WHERE account_id = $1",
                account_id,
            )
        return self._quarantine_from_row(row) if row is not None else None

    async def list_account_quarantines(
        self,
        limit: int = 100,
        cursor: str | None = None,
        reason: AccountQuarantineReason | None = None,
    ) -> AccountQuarantinePage:
        if not 1 <= limit <= 100:
            raise ServiceError(
                "INVALID_PAGE_SIZE",
                "Account quarantine page size must be between 1 and 100",
            )
        conditions: list[str] = []
        parameters: list[object] = []
        if reason is not None:
            parameters.append(reason.value)
            conditions.append(f"reason = ${len(parameters)}")
        cursor_kind = (
            f"account-quarantine:{reason.value}" if reason is not None else "account-quarantine:*"
        )
        if cursor:
            kind, account_id = self._decode_cursor(cursor)
            if kind != cursor_kind:
                raise ServiceError("INVALID_CURSOR", "The quarantine cursor is invalid")
            parameters.append(account_id)
            conditions.append(f"account_id > ${len(parameters)}")
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        parameters.append(limit + 1)
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT * FROM account_quarantines {where} ORDER BY account_id ASC "
                f"LIMIT ${len(parameters)}",
                *parameters,
            )
        selected = rows[:limit]
        next_cursor = None
        if len(rows) > limit and selected:
            next_cursor = self._encode_cursor(
                cursor_kind,
                selected[-1]["account_id"],
            )
        return AccountQuarantinePage(
            items=[self._quarantine_from_row(row) for row in selected],
            next_cursor=next_cursor,
        )

    async def list_account_quarantines_for_probe(
        self,
        limit: int,
    ) -> list[AccountQuarantineRecord]:
        if not 1 <= limit <= 5:
            raise ServiceError(
                "INVALID_PAGE_SIZE",
                "Account quarantine probe limit must be between 1 and 5",
            )
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                "SELECT * FROM account_quarantines "
                "ORDER BY CASE WHEN last_probe_at IS NULL THEN 0 ELSE 1 END, "
                "last_probe_at ASC, quarantined_at ASC, account_id ASC LIMIT $1",
                limit,
            )
        return [self._quarantine_from_row(row) for row in rows]

    async def upsert_account_quarantine_intent(
        self,
        intent: AccountQuarantineIntent,
    ) -> AccountQuarantineIntent:
        async with self._database.transaction() as connection:
            existing = await connection.fetchrow(
                "SELECT * FROM account_quarantine_intents WHERE account_id = $1 FOR UPDATE",
                intent.account_id,
            )
            marker = await connection.fetchrow(
                "SELECT 1 FROM account_quarantines WHERE account_id = $1",
                intent.account_id,
            )
            if existing is not None and marker is not None:
                raise ServiceError(
                    "QUARANTINE_DATA_INVALID",
                    "The account has conflicting quarantine states",
                )
            if marker is not None:
                raise ServiceError(
                    "QUARANTINE_TRANSITION_CONFLICT",
                    "The account is already quarantined",
                )
            if existing is None:
                registry_count = int(
                    await connection.fetchval(
                        "SELECT (SELECT COUNT(*) FROM account_quarantines) + "
                        "(SELECT COUNT(*) FROM account_quarantine_intents)"
                    )
                    or 0
                )
                if registry_count >= self.MAX_ACCOUNT_QUARANTINES:
                    raise ServiceError(
                        "QUARANTINE_CAPACITY_REACHED",
                        "The account quarantine registry is full",
                    )
                await connection.execute(
                    "INSERT INTO account_quarantine_intents("
                    "account_id, reason, group_ids_json, threshold_ms, observed_count, "
                    "previous_status, previous_schedulable, created_at"
                    ") VALUES($1, $2, $3, $4, $5, $6, $7, $8)",
                    intent.account_id,
                    intent.reason.value,
                    _json(list(intent.group_ids)),
                    intent.threshold_ms,
                    intent.observed_count,
                    intent.previous_status,
                    intent.previous_schedulable,
                    intent.created_at,
                )
                existing = await connection.fetchrow(
                    "SELECT * FROM account_quarantine_intents WHERE account_id = $1",
                    intent.account_id,
                )
        if existing is None:
            raise RuntimeError("quarantine intent disappeared after insert")
        return self._quarantine_intent_from_row(existing)

    async def list_account_quarantine_intents(
        self,
        limit: int,
    ) -> list[AccountQuarantineIntent]:
        if not 1 <= limit <= self.MAX_ACCOUNT_QUARANTINES:
            raise ServiceError(
                "INVALID_PAGE_SIZE",
                "Account quarantine intent limit is outside the safe range",
            )
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                "SELECT * FROM account_quarantine_intents ORDER BY created_at, account_id LIMIT $1",
                limit,
            )
        return [self._quarantine_intent_from_row(row) for row in rows]

    async def promote_account_quarantine_intent(
        self,
        account_id: str,
    ) -> AccountQuarantineRecord | None:
        async with self._database.transaction() as connection:
            intent = await connection.fetchrow(
                "SELECT * FROM account_quarantine_intents WHERE account_id = $1 FOR UPDATE",
                account_id,
            )
            if intent is None:
                return None
            await connection.execute(
                "INSERT INTO account_quarantines("
                "account_id, reason, group_ids_json, threshold_ms, observed_count, "
                "quarantined_at, last_probe_at, last_probe_latency_ms, "
                "last_probe_result, updated_at"
                ") VALUES($1, $2, $3, $4, $5, $6, NULL, NULL, $7, $8) "
                "ON CONFLICT(account_id) DO NOTHING",
                intent["account_id"],
                intent["reason"],
                intent["group_ids_json"],
                intent["threshold_ms"],
                intent["observed_count"],
                intent["created_at"],
                QuarantineProbeResult.NEVER.value,
                self._clock(),
            )
            await connection.execute(
                "DELETE FROM account_quarantine_intents WHERE account_id = $1",
                account_id,
            )
            marker = await connection.fetchrow(
                "SELECT * FROM account_quarantines WHERE account_id = $1",
                account_id,
            )
        if marker is None:
            raise RuntimeError("promoted quarantine row disappeared")
        return self._quarantine_from_row(marker)

    async def remove_account_quarantine_intent(self, account_id: str) -> bool:
        async with self._database.acquire() as connection:
            removed = await connection.execute(
                "DELETE FROM account_quarantine_intents WHERE account_id = $1",
                account_id,
            )
        return _rowcount(removed) == 1

    async def account_quarantine_intent_count(self) -> int:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT COUNT(*) AS count FROM account_quarantine_intents"
            )
        return int(row["count"] if row is not None else 0)

    async def begin_account_quarantine_restore(
        self,
        account_id: str,
    ) -> AccountQuarantineRestoreIntent:
        async with self._database.transaction() as connection:
            marker = await connection.fetchrow(
                "SELECT 1 FROM account_quarantines WHERE account_id = $1 FOR UPDATE",
                account_id,
            )
            if marker is None:
                raise ServiceError(
                    "QUARANTINE_NOT_FOUND",
                    "The account quarantine does not exist",
                )
            await connection.execute(
                "INSERT INTO account_quarantine_restore_intents("
                "account_id, created_at) VALUES($1, $2) "
                "ON CONFLICT(account_id) DO NOTHING",
                account_id,
                self._clock(),
            )
            row = await connection.fetchrow(
                "SELECT * FROM account_quarantine_restore_intents WHERE account_id = $1",
                account_id,
            )
        if row is None:
            raise RuntimeError("restore intent disappeared after insert")
        return self._quarantine_restore_intent_from_row(row)

    async def list_account_quarantine_restore_intents(
        self,
        limit: int,
    ) -> list[AccountQuarantineRestoreIntent]:
        if not 1 <= limit <= self.MAX_ACCOUNT_QUARANTINES:
            raise ServiceError(
                "INVALID_PAGE_SIZE",
                "Account quarantine restore intent limit is outside the safe range",
            )
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                "SELECT * FROM account_quarantine_restore_intents "
                "ORDER BY created_at, account_id LIMIT $1",
                limit,
            )
        return [self._quarantine_restore_intent_from_row(row) for row in rows]

    async def complete_account_quarantine_restore(
        self,
        account_id: str,
    ) -> AccountQuarantineRecord | None:
        async with self._database.transaction() as connection:
            intent = await connection.fetchrow(
                "SELECT 1 FROM account_quarantine_restore_intents WHERE account_id = $1",
                account_id,
            )
            marker = await connection.fetchrow(
                "SELECT * FROM account_quarantines WHERE account_id = $1 FOR UPDATE",
                account_id,
            )
            if intent is None or marker is None:
                return None
            parsed = self._quarantine_from_row(marker)
            await connection.execute(
                "DELETE FROM account_quarantines WHERE account_id = $1",
                account_id,
            )
        return parsed

    async def cancel_account_quarantine_restore(self, account_id: str) -> bool:
        async with self._database.acquire() as connection:
            removed = await connection.execute(
                "DELETE FROM account_quarantine_restore_intents WHERE account_id = $1",
                account_id,
            )
        return _rowcount(removed) == 1

    async def account_quarantine_restore_intent_count(self) -> int:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT COUNT(*) AS count FROM account_quarantine_restore_intents"
            )
        return int(row["count"] if row is not None else 0)

    async def update_account_quarantine_probe(
        self,
        account_id: str,
        *,
        probed_at: datetime,
        latency_ms: int | None,
        result: QuarantineProbeResult,
    ) -> AccountQuarantineRecord:
        if result is QuarantineProbeResult.NEVER:
            raise ValueError("a completed quarantine probe cannot use NEVER")
        if probed_at.tzinfo is None:
            raise ValueError("probed_at must be timezone-aware")
        if latency_ms is not None and latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        async with self._database.transaction() as connection:
            existing = await connection.fetchrow(
                "SELECT reason, threshold_ms, last_probe_at, recovery_success_streak "
                "FROM account_quarantines WHERE account_id = $1 FOR UPDATE",
                account_id,
            )
            if existing is None:
                raise ServiceError(
                    "QUARANTINE_NOT_FOUND",
                    "The account quarantine does not exist",
                )
            previous_probe = _datetime(existing["last_probe_at"])
            effective_probed_at = probed_at
            if previous_probe is not None and effective_probed_at <= previous_probe:
                effective_probed_at = previous_probe + timedelta(seconds=1)
            success_streak = 0
            if result is QuarantineProbeResult.PASSING:
                if existing["reason"] != AccountQuarantineReason.SLOW_FIRST_TOKEN.value:
                    raise ValueError("only slow-first-token quarantines can be passing")
                if latency_ms is None or latency_ms > int(existing["threshold_ms"]):
                    raise ValueError("a passing probe must satisfy the latency threshold")
                success_streak = int(existing["recovery_success_streak"]) + 1
                if success_streak != 1:
                    raise ValueError("a second passing probe must restore the account")
            elif result is QuarantineProbeResult.SLOW and latency_ms is None:
                raise ValueError("a slow probe requires measured latency")
            updated = await connection.execute(
                "UPDATE account_quarantines SET last_probe_at = $1, "
                "last_probe_latency_ms = $2, last_probe_result = $3, "
                "recovery_success_streak = $4, updated_at = $5 "
                "WHERE account_id = $6",
                effective_probed_at,
                latency_ms,
                result.value,
                success_streak,
                self._clock(),
                account_id,
            )
            if _rowcount(updated) != 1:
                raise ServiceError(
                    "QUARANTINE_NOT_FOUND",
                    "The account quarantine does not exist",
                )
            row = await connection.fetchrow(
                "SELECT * FROM account_quarantines WHERE account_id = $1",
                account_id,
            )
        if row is None:
            raise RuntimeError("quarantine row disappeared after probe update")
        return self._quarantine_from_row(row)

    async def remove_verified_account_quarantine(self, account_id: str) -> bool:
        async with self._database.transaction() as connection:
            removed = await connection.execute(
                "DELETE FROM account_quarantines WHERE account_id = $1",
                account_id,
            )
        return _rowcount(removed) == 1

    async def account_quarantine_count(
        self,
        reason: AccountQuarantineReason | None = None,
    ) -> int:
        async with self._database.acquire() as connection:
            if reason is None:
                row = await connection.fetchrow("SELECT COUNT(*) AS count FROM account_quarantines")
            else:
                row = await connection.fetchrow(
                    "SELECT COUNT(*) AS count FROM account_quarantines WHERE reason = $1",
                    reason.value,
                )
        return int(row["count"] if row is not None else 0)

    async def bind_actor(self, actor_key: str, user_id: str, masked_email: str) -> AccountBinding:
        now = self._clock()
        try:
            async with self._database.acquire() as connection:
                await connection.execute(
                    "INSERT INTO account_bindings(actor_key, user_id, masked_email, bound_at) "
                    "VALUES($1, $2, $3, $4)",
                    actor_key,
                    user_id,
                    masked_email,
                    now,
                )
        except asyncpg.UniqueViolationError as exc:
            raise ServiceError(
                "BINDING_CONFLICT", "The actor or Sub2API account is already bound"
            ) from exc
        return AccountBinding(
            actor_key=actor_key,
            user_id=user_id,
            masked_email=masked_email,
            bound_at=self._clock(),
        )

    async def get_binding(self, actor_key: str) -> AccountBinding | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM account_bindings WHERE actor_key = $1", actor_key
            )
        if row is None:
            return None
        bound_at = _datetime(row["bound_at"])
        assert bound_at is not None
        return AccountBinding(
            actor_key=row["actor_key"],
            user_id=row["user_id"],
            masked_email=row["masked_email"],
            bound_at=bound_at,
        )

    async def unbind_actor(self, actor_key: str) -> None:
        async with self._database.acquire() as connection:
            await connection.execute("DELETE FROM account_bindings WHERE actor_key = $1", actor_key)

    async def claim_actor_nonce(
        self,
        nonce: str,
        expires_at: datetime,
        *,
        claimed_at: datetime | None = None,
    ) -> bool:
        now = claimed_at or self._clock()
        async with self._database.transaction() as connection:
            await connection.execute("DELETE FROM actor_nonces WHERE expires_at <= $1", now)
            try:
                await connection.execute(
                    "INSERT INTO actor_nonces(nonce, expires_at) VALUES($1, $2)",
                    nonce,
                    expires_at,
                )
            except asyncpg.UniqueViolationError:
                # A replay of the same nonce: the transaction rolls back and
                # the caller treats it as already claimed.
                return False
        return True

    async def set_snapshot(self, key: str, payload: dict[str, Any]) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                "INSERT INTO probe_snapshots(snapshot_key, payload_json, updated_at) "
                "VALUES($1, $2, $3) "
                "ON CONFLICT(snapshot_key) DO UPDATE SET payload_json = excluded.payload_json, "
                "updated_at = excluded.updated_at",
                key,
                _json(payload),
                self._clock(),
            )

    async def publish_guardian_snapshot(
        self,
        payload: dict[str, Any],
        *,
        captured_at: datetime,
    ) -> str:
        if captured_at.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")
        serialized = _json(payload)
        if len(serialized.encode("utf-8")) > 2 * 1024 * 1024:
            raise ServiceError(
                "GUARDIAN_SNAPSHOT_TOO_LARGE",
                "The Guardian snapshot exceeds the storage limit",
            )
        payload_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        captured = captured_at
        snapshot_id = hashlib.sha256(f"1\0{captured}\0{payload_hash}".encode()).hexdigest()
        async with self._database.acquire() as connection:
            await connection.execute(
                "INSERT INTO guardian_input_snapshots"
                "(snapshot_id, schema_version, payload_json, payload_hash, captured_at, "
                "created_at) VALUES($1, 1, $2, $3, $4, $5) "
                "ON CONFLICT(snapshot_id) DO NOTHING",
                snapshot_id,
                serialized,
                payload_hash,
                captured,
                self._clock(),
            )
            await connection.execute(
                "INSERT INTO guardian_metadata(key, value) "
                "VALUES('shared_sampling_started', 'true') "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
            )
        return snapshot_id

    async def get_snapshot(self, key: str) -> dict[str, Any] | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT payload_json FROM probe_snapshots WHERE snapshot_key = $1", key
            )
        return json.loads(row["payload_json"]) if row is not None else None

    async def set_scheduler_value(self, key: str, value: object) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                "INSERT INTO scheduler_state(key, value, updated_at) VALUES($1, $2, $3) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                key,
                _json(value),
                self._clock(),
            )

    async def get_scheduler_value(self, key: str) -> object | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow("SELECT value FROM scheduler_state WHERE key = $1", key)
        return json.loads(row["value"]) if row is not None else None

    async def audit(self, principal: str, action: str, subject: str | None, outcome: str) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                "INSERT INTO audit_events(audit_id, principal, action, subject, outcome, "
                "created_at) "
                "VALUES($1, $2, $3, $4, $5, $6)",
                str(uuid.uuid4()),
                principal,
                action,
                subject,
                outcome,
                self._clock(),
            )

    async def cleanup_retention(
        self,
        *,
        now: datetime | None = None,
        batch_size: int = 20_000,
    ) -> dict[str, int]:
        """Delete bounded terminal history in row batches."""
        reference = now or self._clock()
        if reference.tzinfo is None:
            raise ValueError("retention time must be timezone-aware")
        if not 1 <= batch_size <= 100_000:
            raise ValueError("batch_size must be between 1 and 100000")
        return await self._cleanup_retention_async(reference, batch_size)

    async def _cleanup_retention_async(
        self,
        now: datetime,
        batch_size: int,
    ) -> dict[str, int]:
        cutoffs = {
            "jobs": now - timedelta(days=30),
            "audits": now - timedelta(days=365),
            "now": now,
        }
        counts = {
            "expired_nonces": 0,
            "jobs": 0,
            "audit_events": 0,
        }
        remaining = batch_size
        # Postgres has no ``rowid``; ``ctid`` gives the same bounded-batch
        # delete without needing a secondary index on these columns.
        async with self._database.transaction() as connection:

            async def execute_bounded(
                key: str,
                sql: str,
                *params: object,
            ) -> None:
                nonlocal remaining
                if remaining <= 0:
                    return
                status = await connection.execute(sql, *params, remaining)
                changed = max(0, _rowcount(status))
                counts[key] += changed
                remaining -= changed

            await execute_bounded(
                "expired_nonces",
                "DELETE FROM actor_nonces WHERE ctid IN "
                "(SELECT ctid FROM actor_nonces WHERE expires_at <= $1 "
                "ORDER BY expires_at LIMIT $2)",
                cutoffs["now"],
            )
            await execute_bounded(
                "jobs",
                "DELETE FROM jobs WHERE ctid IN "
                "(SELECT ctid FROM jobs WHERE status IN ($1, $2, $3, $4) "
                "AND finished_at IS NOT NULL AND finished_at < $5 "
                "ORDER BY finished_at LIMIT $6)",
                JobStatus.SUCCEEDED.value,
                JobStatus.FAILED.value,
                JobStatus.CANCELLED.value,
                JobStatus.INTERRUPTED.value,
                cutoffs["jobs"],
            )
            await execute_bounded(
                "audit_events",
                "DELETE FROM audit_events WHERE ctid IN "
                "(SELECT ctid FROM audit_events WHERE created_at < $1 "
                "ORDER BY created_at LIMIT $2)",
                cutoffs["audits"],
            )
        counts["deleted_total"] = sum(counts.values())
        counts["processed_total"] = batch_size - remaining
        return counts

    @staticmethod
    def _job_from_row(row: Any) -> JobRecord:
        created_at = _datetime(row["created_at"])
        updated_at = _datetime(row["updated_at"])
        assert created_at is not None and updated_at is not None
        return JobRecord(
            job_id=row["job_id"],
            job_type=JobType(row["job_type"]),
            status=JobStatus(row["status"]),
            payload=json.loads(row["payload_json"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error_code=row["error_code"],
            error_message=row["error_message"],
            cancel_requested=bool(row["cancel_requested"]),
            created_at=created_at,
            updated_at=updated_at,
            started_at=_datetime(row["started_at"]),
            finished_at=_datetime(row["finished_at"]),
        )

    @staticmethod
    def _quarantine_from_row(row: Any) -> AccountQuarantineRecord:
        try:
            group_ids = json.loads(row["group_ids_json"])
            return AccountQuarantineRecord.model_validate(
                {
                    "account_id": row["account_id"],
                    "reason": row["reason"],
                    "group_ids": group_ids,
                    "threshold_ms": row["threshold_ms"],
                    "observed_count": row["observed_count"],
                    "quarantined_at": _datetime(row["quarantined_at"]),
                    "last_probe_at": _datetime(row["last_probe_at"]),
                    "last_probe_latency_ms": row["last_probe_latency_ms"],
                    "last_probe_result": row["last_probe_result"],
                    "recovery_success_streak": row["recovery_success_streak"],
                }
            )
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ServiceError(
                "QUARANTINE_DATA_INVALID",
                "Persisted account quarantine data is invalid",
            ) from exc

    @staticmethod
    def _quarantine_intent_from_row(row: Any) -> AccountQuarantineIntent:
        try:
            return AccountQuarantineIntent.model_validate(
                {
                    "account_id": row["account_id"],
                    "reason": row["reason"],
                    "group_ids": json.loads(row["group_ids_json"]),
                    "threshold_ms": row["threshold_ms"],
                    "observed_count": row["observed_count"],
                    "previous_status": row["previous_status"],
                    "previous_schedulable": bool(row["previous_schedulable"]),
                    "created_at": _datetime(row["created_at"]),
                }
            )
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ServiceError(
                "QUARANTINE_DATA_INVALID",
                "Persisted account quarantine intent is invalid",
            ) from exc

    @staticmethod
    def _quarantine_restore_intent_from_row(
        row: Any,
    ) -> AccountQuarantineRestoreIntent:
        try:
            return AccountQuarantineRestoreIntent.model_validate(
                {
                    "account_id": row["account_id"],
                    "created_at": _datetime(row["created_at"]),
                }
            )
        except (ValidationError, ValueError, TypeError) as exc:
            raise ServiceError(
                "QUARANTINE_DATA_INVALID",
                "Persisted account quarantine restore intent is invalid",
            ) from exc
