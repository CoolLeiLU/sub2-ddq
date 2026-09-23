"""Durable Guardian policy, channel, sample, run, and event persistence."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ..db import Database, placeholders
from ..errors import ServiceError
from .contracts import (
    AccountRecoveryClassification,
    AccountRecoveryResult,
    AccountRecoveryRunStatus,
    AccountRecoveryRunTrigger,
    ChannelPolicyOverride,
    GroupPolicyOverride,
    GuardianAccountObservation,
    GuardianAccountRecoveryRecord,
    GuardianAccountRecoveryRun,
    GuardianChannelErrorEpisode,
    GuardianEvidence,
    GuardianEvidenceBucket,
    GuardianFreshness,
    GuardianHealth,
    GuardianPolicy,
    GuardianProbeTemplate,
    GuardianSample,
    GuardianSampleSource,
    ManualControl,
    UpstreamGroupSummary,
    UpstreamProbeSnapshot,
)

GUARDIAN_SCHEMA_VERSION = 12

GUARDIAN_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS guardian_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guardian_policy (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    policy_json TEXT NOT NULL,
    revision INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS guardian_group_overrides (
    group_id TEXT PRIMARY KEY,
    policy_json TEXT NOT NULL,
    revision INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS guardian_channel_overrides (
    channel_id TEXT PRIMARY KEY,
    override_json TEXT NOT NULL,
    revision INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS guardian_channels (
    channel_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    group_id TEXT,
    upstream_status TEXT NOT NULL,
    upstream_schedulable BOOLEAN NOT NULL,
    health TEXT NOT NULL,
    score REAL NOT NULL,
    latency_ms INTEGER,
    desired_schedulable BOOLEAN NOT NULL,
    manual_control TEXT NOT NULL,
    details_json TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    freshness_state TEXT NOT NULL DEFAULT 'EXPIRED',
    last_evidence_at TIMESTAMPTZ,
    warmup_buckets INTEGER NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_guardian_channels_group
    ON guardian_channels(group_id, health, channel_id);
CREATE TABLE IF NOT EXISTS guardian_groups (
    group_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    total_count INTEGER NOT NULL DEFAULT 0,
    available_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    temporary_unavailable_count INTEGER NOT NULL DEFAULT 0,
    closed_count INTEGER NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    removed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS guardian_samples (
    sample_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    score INTEGER NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    ttfb_ms INTEGER,
    status_code INTEGER,
    message TEXT NOT NULL,
    source_event_id TEXT,
    bucket_at TIMESTAMPTZ,
    reliability REAL NOT NULL DEFAULT 1.0,
    ingested_at TIMESTAMPTZ,
    legacy BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_guardian_samples_channel
    ON guardian_samples(channel_id, occurred_at DESC, sample_id DESC);
CREATE TABLE IF NOT EXISTS guardian_runs (
    run_id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    dry_run BOOLEAN NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error_code TEXT,
    error_message TEXT,
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_guardian_runs_started
    ON guardian_runs(started_at DESC, run_id DESC);
CREATE TABLE IF NOT EXISTS guardian_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    channel_id TEXT,
    group_id TEXT,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_guardian_events_created
    ON guardian_events(created_at DESC, event_id DESC);
CREATE TABLE IF NOT EXISTS guardian_probe_ledger (
    ledger_id TEXT PRIMARY KEY,
    channel_id TEXT,
    model TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    estimated_cost REAL,
    priced BOOLEAN NOT NULL,
    budget_date TEXT,
    request_source TEXT,
    blocked_reason TEXT,
    occurred_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS guardian_leases (
    lease_key TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS guardian_idempotency (
    idempotency_key TEXT NOT NULL,
    action TEXT NOT NULL,
    subject TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(idempotency_key, action, subject)
);
CREATE TABLE IF NOT EXISTS guardian_input_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    claim_owner TEXT,
    claim_expires_at TIMESTAMPTZ,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_guardian_input_snapshots_claim
    ON guardian_input_snapshots(consumed_at, claim_expires_at, captured_at, snapshot_id);
CREATE TABLE IF NOT EXISTS guardian_traffic_buckets (
    channel_id TEXT NOT NULL,
    bucket_at TIMESTAMPTZ NOT NULL,
    event_count INTEGER NOT NULL,
    score_sum REAL NOT NULL,
    ttfb_p95_ms INTEGER,
    details_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(channel_id, bucket_at)
);
CREATE INDEX IF NOT EXISTS idx_guardian_traffic_buckets_recent
    ON guardian_traffic_buckets(bucket_at DESC, channel_id);
"""

GUARDIAN_ACCOUNT_RECOVERY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS guardian_account_observations (
    snapshot_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    group_ids_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'error', 'disabled', 'inactive')),
    schedulable BOOLEAN NOT NULL CHECK (schedulable IN (TRUE, FALSE)),
    expired BOOLEAN NOT NULL CHECK (expired IN (TRUE, FALSE)),
    temporary_unavailable BOOLEAN NOT NULL CHECK (temporary_unavailable IN (TRUE, FALSE)),
    automatic_pause BOOLEAN NOT NULL DEFAULT FALSE CHECK (automatic_pause IN (TRUE, FALSE)),
    observed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(snapshot_id, account_id)
);
CREATE INDEX IF NOT EXISTS idx_guardian_account_observations_latest
    ON guardian_account_observations(account_id, observed_at DESC, snapshot_id DESC);
CREATE INDEX IF NOT EXISTS idx_guardian_account_observations_retention
    ON guardian_account_observations(observed_at, snapshot_id, account_id);
CREATE TABLE IF NOT EXISTS guardian_channel_error_episodes (
    episode_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    group_id TEXT,
    opened_snapshot_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('OPEN', 'CLOSED')),
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_guardian_channel_error_episode_open
    ON guardian_channel_error_episodes(channel_id) WHERE status = 'OPEN';
CREATE INDEX IF NOT EXISTS idx_guardian_channel_error_episode_recent
    ON guardian_channel_error_episodes(opened_at DESC, episode_id DESC);
CREATE TABLE IF NOT EXISTS guardian_account_recovery_runs (
    run_id TEXT PRIMARY KEY,
    dedup_key TEXT NOT NULL UNIQUE,
    trigger TEXT NOT NULL CHECK (
        trigger IN (
            'BAD_ACCOUNT_STATE', 'CHANNEL_ERROR', 'HOURLY_ACTIVE_CHECK', 'MANUAL'
        )
    ),
    snapshot_id TEXT,
    episode_id TEXT,
    policy_revision INTEGER NOT NULL CHECK (policy_revision > 0),
    status TEXT NOT NULL CHECK (
        status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')
    ),
    result_json TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_guardian_account_recovery_runs_recent
    ON guardian_account_recovery_runs(started_at DESC, run_id DESC);
CREATE TABLE IF NOT EXISTS guardian_account_recovery_ledger (
    ledger_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL
        REFERENCES guardian_account_recovery_runs(run_id) ON DELETE CASCADE,
    dedup_key TEXT NOT NULL UNIQUE,
    account_id TEXT NOT NULL,
    channel_id TEXT,
    group_id TEXT,
    classification TEXT NOT NULL CHECK (
        classification IN (
            'AVAILABLE', 'MANUAL_PAUSE', 'UPSTREAM_ERROR',
            'DISABLED', 'SYSTEM_QUARANTINE', 'EXCLUDED'
        )
    ),
    result TEXT NOT NULL CHECK (
        result IN ('ENABLED', 'DISABLED', 'INDETERMINATE', 'SKIPPED')
    ),
    reason TEXT NOT NULL,
    tested BOOLEAN NOT NULL CHECK (tested IN (TRUE, FALSE)),
    occurred_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS guardian_account_preferences (
    account_id TEXT PRIMARY KEY,
    preferred_probe_model TEXT,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_guardian_account_recovery_ledger_run
    ON guardian_account_recovery_ledger(run_id, occurred_at, ledger_id);
CREATE INDEX IF NOT EXISTS idx_guardian_account_recovery_ledger_recent
    ON guardian_account_recovery_ledger(occurred_at, account_id) WHERE tested;
CREATE INDEX IF NOT EXISTS idx_guardian_samples_retention
    ON guardian_samples(occurred_at, sample_id);
CREATE INDEX IF NOT EXISTS idx_guardian_runs_retention
    ON guardian_runs(updated_at, run_id) WHERE status <> 'RUNNING';
CREATE INDEX IF NOT EXISTS idx_guardian_input_snapshots_retention
    ON guardian_input_snapshots(captured_at, snapshot_id) WHERE consumed_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_guardian_closed_episodes_retention
    ON guardian_channel_error_episodes(updated_at, episode_id) WHERE status = 'CLOSED';
CREATE INDEX IF NOT EXISTS idx_guardian_recovery_runs_retention
    ON guardian_account_recovery_runs(updated_at, run_id) WHERE status <> 'RUNNING';
CREATE INDEX IF NOT EXISTS idx_guardian_probe_ledger_occurred
    ON guardian_probe_ledger(occurred_at, ledger_id);
CREATE INDEX IF NOT EXISTS idx_guardian_idempotency_created
    ON guardian_idempotency(created_at, idempotency_key, action, subject);
"""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _dt(value: str | datetime | None) -> datetime | None:
    """Normalize a timestamp coming back from the database.

    PostgreSQL returns ``datetime`` objects for ``TIMESTAMPTZ`` columns, while
    the retained JSON/text paths and the SQLite import still hand over ISO
    strings, so both are accepted here.
    """

    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _rowcount(status: str | None) -> int:
    """Extract the affected row count from an ``asyncpg`` command status.

    ``asyncpg`` returns strings such as ``"UPDATE 3"`` or ``"DELETE 0"`` where
    SQLite exposed ``Cursor.rowcount``.  Returning 0 for an unparsable
    status keeps callers that only log the number safe.
    """

    if not status:
        return 0
    _, _, tail = status.rpartition(" ")
    try:
        return int(tail)
    except ValueError:
        return 0


def _snapshot_id(value: str) -> str:
    normalized = value.strip().lower()
    invalid_character = any(character not in "0123456789abcdef" for character in normalized)
    if len(normalized) != 64 or invalid_character:
        raise ValueError("snapshot ID must be a SHA-256 hex digest")
    return normalized


def _cursor(created_at: str, item_id: str) -> str:
    encoded = base64.urlsafe_b64encode(_json([created_at, item_id]).encode()).decode()
    return encoded.rstrip("=")


def _decode_cursor(value: str) -> tuple[str, str]:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw_decoded: object = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(raw_decoded, list):
            raise ValueError
        decoded = cast(list[object], raw_decoded)
        if len(decoded) != 2:
            raise ValueError
        first, second = decoded
        if not isinstance(first, str) or not isinstance(second, str):
            raise ValueError
        return first, second
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ServiceError("INVALID_CURSOR", "The Guardian cursor is invalid") from exc


class GuardianRepository:
    SCHEMA_VERSION = GUARDIAN_SCHEMA_VERSION

    def __init__(self, database: Database, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._database = database
        self._clock = clock

    async def initialize(self) -> None:
        """Create the schema and seed defaults.

        The legacy SQLite schema carried eleven incremental migrations
        (``_migrate_v1_to_v2_sync`` .. ``_migrate_v11_to_v12_sync``) that
        upgraded an existing file in place.  A fresh PostgreSQL deployment
        always starts at the current shape, so those steps are not reproduced
        here; data moves across via ``scripts/migrate_sqlite_to_postgres.py``.
        """

        now = self._clock()
        default = GuardianPolicy()
        async with self._database.transaction() as connection:
            for statement in GUARDIAN_SCHEMA_SQL.split(";"):
                if statement.strip():
                    await connection.execute(statement)
            for statement in GUARDIAN_ACCOUNT_RECOVERY_SCHEMA_SQL.split(";"):
                if statement.strip():
                    await connection.execute(statement)
            await connection.execute(
                "INSERT INTO guardian_metadata(key, value) VALUES('schema_version', $1) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                str(GUARDIAN_SCHEMA_VERSION),
            )
            await connection.execute(
                "INSERT INTO guardian_policy"
                "(singleton, policy_json, revision, updated_at) VALUES(1, $1, 1, $2) "
                "ON CONFLICT(singleton) DO NOTHING",
                default.model_dump_json(),
                now,
            )
            await connection.execute(
                "UPDATE guardian_runs SET status = 'INTERRUPTED', "
                "error_code = 'SERVICE_RESTARTED', "
                "error_message = 'The service restarted during this Guardian run', "
                "finished_at = $1, updated_at = $2 WHERE status = 'RUNNING'",
                now,
                now,
            )
            await connection.execute(
                "UPDATE guardian_account_recovery_runs SET status = 'INTERRUPTED', "
                "finished_at = $1, updated_at = $2 WHERE status = 'RUNNING'",
                now,
                now,
            )

    async def get_policy(self) -> GuardianPolicy:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT policy_json, revision FROM guardian_policy WHERE singleton = 1"
            )
        if row is None:
            raise RuntimeError("Guardian repository has not been initialized")
        data = cast(dict[str, Any], json.loads(row["policy_json"]))
        data["revision"] = int(row["revision"])
        return GuardianPolicy.model_validate(data)

    async def pending_input_snapshot_count(self) -> int:
        async with self._database.acquire() as connection:
            value = await connection.fetchval(
                "SELECT COUNT(*) FROM guardian_input_snapshots WHERE consumed_at IS NULL"
            )
        return int(value or 0)

    async def monitored_group_ids_for_snapshot(
        self,
        snapshot_id: str,
        *,
        excluded_channel_ids: frozenset[str] = frozenset(),
        excluded_group_ids: frozenset[str] = frozenset(),
    ) -> frozenset[str] | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT payload_json FROM guardian_input_snapshots WHERE snapshot_id = $1",
                _snapshot_id(snapshot_id),
            )
            excluded_monitor_rows = await connection.fetch(
                "SELECT channel_id FROM guardian_channels WHERE manual_control = 'EXCLUDED'"
            )
        if row is None:
            return None
        try:
            snapshot = UpstreamProbeSnapshot.model_validate_json(row["payload_json"])
        except ValidationError:
            return None
        # Only groups reachable through a monitored channel are in scope:
        # excluded channels never seed their group, and account-bound groups
        # join only when an account is shared with a monitored group.  Groups
        # that lost their channel entirely (closed upstream) drop out so
        # account recovery does not test or mutate accounts Guardian cannot
        # actually route traffic to.
        excluded_monitor_ids = {
            str(excluded_row["channel_id"]) for excluded_row in excluded_monitor_rows
        } | set(excluded_channel_ids)
        entry_group_ids = {
            entry.group_id
            for entry in snapshot.entries
            if entry.group_id is not None and entry.monitor_id not in excluded_monitor_ids
        } - set(excluded_group_ids)
        group_ids = set(entry_group_ids)
        for account in snapshot.accounts:
            if entry_group_ids & set(account.group_ids):
                group_ids.update(account.group_ids)
        return frozenset(group_ids - set(excluded_group_ids))

    async def probe_templates_for_snapshot(
        self,
        snapshot_id: str,
    ) -> tuple[GuardianProbeTemplate, ...]:
        """Return the channel monitor models captured in one shared snapshot.

        The snapshot is the single source of truth for recovery runs.  Reading
        it here keeps account tests aligned with the monitor that produced the
        account observations, including after a process restart.
        """

        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT payload_json FROM guardian_input_snapshots WHERE snapshot_id = $1",
                _snapshot_id(snapshot_id),
            )
            if row is None:
                return ()
            try:
                snapshot = UpstreamProbeSnapshot.model_validate_json(row["payload_json"])
            except ValidationError as exc:
                raise ServiceError(
                    "GUARDIAN_SNAPSHOT_DATA_INVALID",
                    "Persisted Guardian probe snapshot data is invalid",
                ) from exc
            channel_rows = await connection.fetch(
                "SELECT channel_id, override_json FROM guardian_channel_overrides"
            )
            group_rows = await connection.fetch(
                "SELECT group_id, policy_json FROM guardian_group_overrides"
            )
        channel_overrides = {
            str(row["channel_id"]): ChannelPolicyOverride.model_validate_json(row["override_json"])
            for row in channel_rows
        }
        group_overrides = {
            str(row["group_id"]): GroupPolicyOverride.model_validate_json(row["policy_json"])
            for row in group_rows
        }
        templates: list[GuardianProbeTemplate] = []
        for entry in snapshot.entries:
            channel_override = channel_overrides.get(entry.monitor_id)
            group_override = (
                group_overrides.get(entry.group_id) if entry.group_id is not None else None
            )
            effective_model = (entry.probe_model or "").strip()
            channel_model = (
                channel_override.probe_model.strip()
                if channel_override is not None and channel_override.probe_model
                else ""
            )
            group_model = (
                group_override.probe_model.strip()
                if group_override is not None and group_override.probe_model
                else ""
            )
            if channel_model:
                effective_model = channel_model
            elif group_model:
                effective_model = group_model
            if not effective_model:
                continue
            templates.append(
                GuardianProbeTemplate(
                    channel_id=entry.monitor_id,
                    group_id=entry.group_id,
                    model_id=effective_model,
                    api_mode=entry.probe_api_mode,
                    template_id=entry.probe_template_id,
                )
            )
        templates.sort(key=lambda item: (item.group_id or "", item.channel_id))
        return tuple(templates)

    async def supersede_expired_input_snapshots(
        self,
        *,
        captured_before: datetime,
    ) -> int:
        if captured_before.tzinfo is None:
            raise ValueError("snapshot expiry cutoff must be timezone-aware")
        now = self._clock().astimezone(UTC)
        cutoff = captured_before.astimezone(UTC)
        # The newest unconsumed snapshot is the one Guardian is about to read;
        # everything older that is not currently claimed by a live worker is
        # superseded.  ``FOR UPDATE`` on the candidate row keeps two workers
        # from superseding each other's claim.
        async with self._database.transaction() as connection:
            latest = await connection.fetchrow(
                "SELECT snapshot_id FROM guardian_input_snapshots "
                "WHERE consumed_at IS NULL "
                "ORDER BY captured_at DESC, snapshot_id DESC LIMIT 1 "
                "FOR UPDATE"
            )
            if latest is None:
                return 0
            result = await connection.execute(
                "UPDATE guardian_input_snapshots "
                "SET consumed_at = $1, claim_owner = NULL, claim_expires_at = NULL "
                "WHERE consumed_at IS NULL AND captured_at < $2 AND snapshot_id <> $3 "
                "AND (claim_owner IS NULL OR claim_expires_at <= $4)",
                now,
                cutoff,
                latest["snapshot_id"],
                now,
            )
        return _rowcount(result)

    async def shared_sampling_started(self) -> bool:
        async with self._database.acquire() as connection:
            value = await connection.fetchval(
                "SELECT value FROM guardian_metadata WHERE key = 'shared_sampling_started'"
            )
        return bool(value == "true")

    async def model_plaza_last_refresh(self) -> datetime | None:
        async with self._database.acquire() as connection:
            value = await connection.fetchval(
                "SELECT value FROM guardian_metadata WHERE key = 'model_plaza_last_refresh'"
            )
        if value is None:
            return None
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    async def mark_model_plaza_refreshed(self, refreshed_at: datetime) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                "INSERT INTO guardian_metadata(key, value) VALUES($1, $2) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                "model_plaza_last_refresh",
                # guardian_metadata.value is TEXT and also holds the schema
                # version, so this one key keeps its ISO string form.
                _iso(refreshed_at),
            )

    async def claim_input_snapshot(
        self,
        owner: str,
        *,
        lease_seconds: int,
    ) -> dict[str, Any] | None:
        if not owner or len(owner) > 200:
            raise ValueError("invalid snapshot claim owner")
        now_value = self._clock().astimezone(UTC)
        expires_at = now_value + timedelta(seconds=max(1, lease_seconds))
        # ``SKIP LOCKED`` reproduces SQLite's serialized claim: two workers
        # picking snapshots concurrently each take a different row instead of
        # blocking on the same one.
        async with self._database.transaction() as connection:
            row = await connection.fetchrow(
                "SELECT snapshot_id FROM guardian_input_snapshots "
                "WHERE consumed_at IS NULL AND "
                "(claim_owner IS NULL OR claim_expires_at <= $1) "
                "ORDER BY captured_at, snapshot_id LIMIT 1 "
                "FOR UPDATE SKIP LOCKED",
                now_value,
            )
            if row is None:
                return None
            await connection.execute(
                "UPDATE guardian_input_snapshots "
                "SET claim_owner = $1, claim_expires_at = $2 "
                "WHERE snapshot_id = $3 AND consumed_at IS NULL",
                owner,
                expires_at,
                row["snapshot_id"],
            )
            claimed = await connection.fetchrow(
                "SELECT snapshot_id, payload_json, captured_at "
                "FROM guardian_input_snapshots WHERE snapshot_id = $1",
                row["snapshot_id"],
            )
        assert claimed is not None
        payload: object = json.loads(claimed["payload_json"])
        if not isinstance(payload, dict):
            raise RuntimeError("Guardian input snapshot payload is invalid")
        return {
            "snapshot_id": claimed["snapshot_id"],
            "payload": cast(dict[str, Any], payload),
            "captured_at": claimed["captured_at"],
        }

    async def consume_input_snapshot(self, snapshot_id: str, owner: str) -> bool:
        async with self._database.acquire() as connection:
            status = await connection.execute(
                "UPDATE guardian_input_snapshots "
                "SET consumed_at = $1, claim_owner = NULL, claim_expires_at = NULL "
                "WHERE snapshot_id = $2 AND claim_owner = $3 AND consumed_at IS NULL",
                self._clock(),
                snapshot_id,
                owner,
            )
        return _rowcount(status) == 1

    async def release_input_snapshot(self, snapshot_id: str, owner: str) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                "UPDATE guardian_input_snapshots "
                "SET claim_owner = NULL, claim_expires_at = NULL "
                "WHERE snapshot_id = $1 AND claim_owner = $2 AND consumed_at IS NULL",
                snapshot_id,
                owner,
            )

    async def upsert_account_observations(
        self,
        *,
        snapshot_id: str,
        observed_at: datetime,
        observations: list[GuardianAccountObservation],
    ) -> int:
        normalized_snapshot_id = _snapshot_id(snapshot_id)
        if observed_at.tzinfo is None:
            raise ValueError("account observation time must be timezone-aware")
        if len(observations) > 10_000:
            raise ValueError("account observation count exceeds the safe limit")
        account_ids = [item.account_id for item in observations]
        if len(account_ids) != len(set(account_ids)):
            raise ValueError("account observations contain duplicate account IDs")
        inserted = 0
        async with self._database.transaction() as connection:
            for observation in observations:
                observation = await self._normalize_account_observation_sync(
                    connection,
                    observation,
                    snapshot_id=normalized_snapshot_id,
                    observed_at=observed_at,
                )
                existing = await connection.fetchrow(
                    "SELECT * FROM guardian_account_observations "
                    "WHERE snapshot_id = $1 AND account_id = $2",
                    normalized_snapshot_id,
                    observation.account_id,
                )
                if existing is not None:
                    if (
                        self._account_observation_from_row(existing) != observation
                        or existing["observed_at"] != observed_at
                    ):
                        raise ServiceError(
                            "ACCOUNT_OBSERVATION_CONFLICT",
                            "The account observation changed for the same snapshot",
                        )
                    continue
                await connection.execute(
                    "INSERT INTO guardian_account_observations("
                    "snapshot_id, account_id, group_ids_json, status, schedulable, "
                    "expired, temporary_unavailable, automatic_pause, observed_at"
                    ") VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9) "
                    "ON CONFLICT(snapshot_id, account_id) DO NOTHING",
                    normalized_snapshot_id,
                    observation.account_id,
                    _json(list(observation.group_ids)),
                    observation.status.value,
                    observation.schedulable,
                    observation.expired,
                    observation.temporary_unavailable,
                    observation.automatic_pause,
                    observed_at,
                )
                inserted += 1
        return inserted

    @staticmethod
    async def _normalize_account_observation_sync(
        connection: Any,
        observation: GuardianAccountObservation,
        *,
        snapshot_id: str,
        observed_at: datetime,
    ) -> GuardianAccountObservation:
        """Infer automatic pause provenance only from safe local evidence.

        Sub2API versions before the provenance fields were introduced expose
        ``active + schedulable=false`` for both human pauses and automatic
        protection.  An explicit adapter marker wins.  Otherwise we retain a
        marker only when a recent snapshot for the same account was in the
        upstream ``error`` state or was already identified as automatic.  A
        first-seen, unannotated pause remains protected as a manual pause.
        """

        if (
            observation.status.value != "active"
            or observation.schedulable
            or observation.automatic_pause
        ):
            return observation
        row = await connection.fetchrow(
            "SELECT status, automatic_pause, observed_at "
            "FROM guardian_account_observations "
            "WHERE account_id = $1 AND snapshot_id <> $2 "
            "ORDER BY observed_at DESC, snapshot_id DESC LIMIT 1",
            observation.account_id,
            snapshot_id,
        )
        if row is None:
            return observation
        previous_at = _dt(row["observed_at"])
        current_at = observed_at.astimezone(UTC)
        if previous_at is None:
            return observation
        age_seconds = (current_at - previous_at.astimezone(UTC)).total_seconds()
        # Retention keeps account observations for two days.  Do not let an
        # ancient error turn a newly created human pause into an auto-owned
        # account after the evidence has aged out.
        if age_seconds < 0 or age_seconds > 2 * 24 * 60 * 60:
            return observation
        if bool(row["automatic_pause"]) or row["status"] == "error":
            return observation.model_copy(update={"automatic_pause": True})
        return observation

    async def list_account_observations(
        self,
        snapshot_id: str,
    ) -> list[GuardianAccountObservation]:
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                "SELECT * FROM guardian_account_observations WHERE snapshot_id = $1 "
                "ORDER BY CAST(account_id AS INTEGER)",
                _snapshot_id(snapshot_id),
            )
        return [self._account_observation_from_row(row) for row in rows]

    async def latest_abnormal_account_snapshot(self) -> str | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "WITH latest AS ("
                "SELECT snapshot_id FROM guardian_account_observations "
                "ORDER BY observed_at DESC, snapshot_id DESC LIMIT 1"
                ") SELECT observations.snapshot_id "
                "FROM guardian_account_observations AS observations "
                "JOIN latest ON latest.snapshot_id = observations.snapshot_id "
                "WHERE ((observations.status IN ('error', 'disabled', 'inactive') "
                "AND observations.expired = FALSE "
                "AND observations.temporary_unavailable = FALSE) "
                "OR (observations.status = 'active' "
                "AND observations.schedulable = FALSE "
                "AND observations.automatic_pause = TRUE "
                "AND observations.expired = FALSE "
                "AND observations.temporary_unavailable = FALSE)) LIMIT 1"
            )
        return cast(str, row["snapshot_id"]) if row is not None else None

    async def open_channel_error_episode(
        self,
        *,
        channel_id: str,
        group_id: str | None,
        snapshot_id: str,
        opened_at: datetime,
    ) -> GuardianChannelErrorEpisode:
        if not 1 <= len(channel_id) <= 128:
            raise ValueError("channel ID is outside the safe range")
        if group_id is not None and (
            not group_id.isdigit() or int(group_id) <= 0 or len(group_id) > 20
        ):
            raise ValueError("group ID must be a positive decimal identifier")
        if opened_at.tzinfo is None:
            raise ValueError("episode opened_at must be timezone-aware")
        normalized_snapshot_id = _snapshot_id(snapshot_id)
        episode_id = str(uuid.uuid4())
        now = self._clock()
        # The partial unique index on an OPEN episode per channel is the real
        # guard; ON CONFLICT DO NOTHING makes a concurrent second writer fall
        # through to the read below instead of raising.
        async with self._database.transaction() as connection:
            await connection.execute(
                "INSERT INTO guardian_channel_error_episodes("
                "episode_id, channel_id, group_id, opened_snapshot_id, status, "
                "opened_at, closed_at, updated_at"
                ") VALUES($1, $2, $3, $4, 'OPEN', $5, NULL, $6) "
                "ON CONFLICT DO NOTHING",
                episode_id,
                channel_id,
                group_id,
                normalized_snapshot_id,
                opened_at,
                now,
            )
            row = await connection.fetchrow(
                "SELECT * FROM guardian_channel_error_episodes "
                "WHERE channel_id = $1 AND status = 'OPEN'",
                channel_id,
            )
        if row is None:
            raise ServiceError(
                "CHANNEL_ERROR_EPISODE_CONFLICT",
                "The open channel error episode could not be read back",
            )
        episode = self._channel_error_episode_from_row(row)
        if episode.group_id != group_id:
            raise ServiceError(
                "CHANNEL_ERROR_EPISODE_CONFLICT",
                "The open channel error episode has a different group mapping",
            )
        return episode

    async def get_open_channel_error_episode(
        self,
        channel_id: str,
    ) -> GuardianChannelErrorEpisode | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM guardian_channel_error_episodes "
                "WHERE channel_id = $1 AND status = 'OPEN'",
                channel_id,
            )
        return self._channel_error_episode_from_row(row) if row is not None else None

    async def latest_open_channel_error_episode(
        self,
    ) -> GuardianChannelErrorEpisode | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM guardian_channel_error_episodes "
                "WHERE status = 'OPEN' "
                "ORDER BY opened_at DESC, episode_id DESC LIMIT 1"
            )
        return self._channel_error_episode_from_row(row) if row is not None else None

    async def list_open_channel_error_episodes(
        self,
        *,
        limit: int = 20,
    ) -> list[GuardianChannelErrorEpisode]:
        if not 1 <= limit <= 100:
            raise ValueError("open episode limit must be between 1 and 100")
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                "SELECT * FROM guardian_channel_error_episodes "
                "WHERE status = 'OPEN' "
                "ORDER BY opened_at DESC, episode_id DESC LIMIT $1",
                limit,
            )
        return [self._channel_error_episode_from_row(row) for row in rows]

    async def close_channel_error_episode(
        self,
        channel_id: str,
        *,
        closed_at: datetime,
    ) -> bool:
        if closed_at.tzinfo is None:
            raise ValueError("episode closed_at must be timezone-aware")
        async with self._database.acquire() as connection:
            status = await connection.execute(
                "UPDATE guardian_channel_error_episodes SET status = 'CLOSED', "
                "closed_at = $1, updated_at = $2 "
                "WHERE channel_id = $3 AND status = 'OPEN'",
                closed_at,
                self._clock(),
                channel_id,
            )
        return _rowcount(status) == 1

    async def create_account_recovery_run(
        self,
        *,
        dedup_key: str,
        trigger: AccountRecoveryRunTrigger,
        snapshot_id: str | None,
        episode_id: str | None,
        policy_revision: int,
        started_at: datetime,
    ) -> GuardianAccountRecoveryRun:
        if not 1 <= len(dedup_key) <= 512:
            raise ValueError("account recovery dedup key is outside the safe range")
        normalized_snapshot_id = _snapshot_id(snapshot_id) if snapshot_id is not None else None
        if episode_id is not None and not 1 <= len(episode_id) <= 128:
            raise ValueError("episode ID is outside the safe range")
        if policy_revision < 1:
            raise ValueError("policy revision must be positive")
        if started_at.tzinfo is None:
            raise ValueError("account recovery start time must be timezone-aware")
        run_id = str(uuid.uuid4())
        # The UNIQUE constraint on dedup_key replaces the read-then-insert the
        # SQLite version performed under a write lock: a concurrent creator
        # inserts nothing and the SELECT below returns the winner's row.
        async with self._database.transaction() as connection:
            await connection.execute(
                "INSERT INTO guardian_account_recovery_runs("
                "run_id, dedup_key, trigger, snapshot_id, episode_id, policy_revision, "
                "status, result_json, started_at, finished_at, updated_at"
                ") VALUES($1, $2, $3, $4, $5, $6, 'RUNNING', NULL, $7, NULL, $8) "
                "ON CONFLICT(dedup_key) DO NOTHING",
                run_id,
                dedup_key,
                trigger.value,
                normalized_snapshot_id,
                episode_id,
                policy_revision,
                started_at,
                self._clock(),
            )
            row = await connection.fetchrow(
                "SELECT * FROM guardian_account_recovery_runs WHERE dedup_key = $1",
                dedup_key,
            )
        if row is None:
            raise RuntimeError("account recovery run could not be created")
        return self._account_recovery_run_from_row(row)

    async def finish_account_recovery_run(
        self,
        run_id: str,
        *,
        status: str,
        result: dict[str, int],
        finished_at: datetime,
    ) -> GuardianAccountRecoveryRun:
        parsed_status = AccountRecoveryRunStatus(status)
        if parsed_status is AccountRecoveryRunStatus.RUNNING:
            raise ValueError("a finished account recovery run cannot remain running")
        if finished_at.tzinfo is None:
            raise ValueError("account recovery finish time must be timezone-aware")
        # ``FOR UPDATE`` serializes two finishers on the same run, which the
        # SQLite write lock provided implicitly.
        async with self._database.transaction() as connection:
            existing = await connection.fetchrow(
                "SELECT * FROM guardian_account_recovery_runs WHERE run_id = $1 FOR UPDATE",
                run_id,
            )
            if existing is None:
                raise ServiceError(
                    "ACCOUNT_RECOVERY_RUN_NOT_FOUND",
                    "The account recovery run does not exist",
                )
            current = self._account_recovery_run_from_row(existing)
            if current.status is not AccountRecoveryRunStatus.RUNNING:
                if current.status is parsed_status and current.result == result:
                    return current
                raise ServiceError(
                    "ACCOUNT_RECOVERY_RUN_CONFLICT",
                    "The account recovery run is already complete",
                )
            await connection.execute(
                "UPDATE guardian_account_recovery_runs SET status = $1, result_json = $2, "
                "finished_at = $3, updated_at = $4 WHERE run_id = $5",
                parsed_status.value,
                _json(result),
                finished_at,
                self._clock(),
                run_id,
            )
            row = await connection.fetchrow(
                "SELECT * FROM guardian_account_recovery_runs WHERE run_id = $1",
                run_id,
            )
        if row is None:
            raise RuntimeError("account recovery run disappeared while finishing")
        return self._account_recovery_run_from_row(row)

    async def get_account_recovery_run(
        self,
        run_id: str,
    ) -> GuardianAccountRecoveryRun | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM guardian_account_recovery_runs WHERE run_id = $1",
                run_id,
            )
        return self._account_recovery_run_from_row(row) if row is not None else None

    async def list_account_recovery_runs(
        self,
        limit: int,
    ) -> list[GuardianAccountRecoveryRun]:
        if not 1 <= limit <= 100:
            raise ValueError("account recovery run limit must be between 1 and 100")
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                "SELECT * FROM guardian_account_recovery_runs "
                "ORDER BY started_at DESC, run_id DESC LIMIT $1",
                limit,
            )
        return [self._account_recovery_run_from_row(row) for row in rows]

    async def latest_account_recovery_run(
        self,
        trigger: AccountRecoveryRunTrigger,
    ) -> GuardianAccountRecoveryRun | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM guardian_account_recovery_runs WHERE trigger = $1 "
                "ORDER BY started_at DESC, run_id DESC LIMIT 1",
                trigger.value,
            )
        return self._account_recovery_run_from_row(row) if row is not None else None

    async def record_account_recovery_result(
        self,
        *,
        run_id: str,
        dedup_key: str,
        account_id: str,
        channel_id: str | None,
        group_id: str | None,
        classification: AccountRecoveryClassification,
        result: AccountRecoveryResult,
        reason: str,
        tested: bool,
        occurred_at: datetime,
    ) -> bool:
        record = GuardianAccountRecoveryRecord(
            ledger_id=str(uuid.uuid4()),
            run_id=run_id,
            dedup_key=dedup_key,
            account_id=account_id,
            channel_id=channel_id,
            group_id=group_id,
            classification=classification,
            result=result,
            reason=reason,
            tested=tested,
            occurred_at=occurred_at,
        )
        # The UNIQUE ledger dedup key makes the insert idempotent; a duplicate
        # writes nothing and is compared against the stored row below.
        async with self._database.transaction() as connection:
            existing = await connection.fetchrow(
                "SELECT * FROM guardian_account_recovery_ledger WHERE dedup_key = $1",
                dedup_key,
            )
            if existing is not None:
                stored = self._account_recovery_record_from_row(existing)
                if stored.model_dump(exclude={"ledger_id"}) != record.model_dump(
                    exclude={"ledger_id"}
                ):
                    raise ServiceError(
                        "ACCOUNT_RECOVERY_RESULT_CONFLICT",
                        "The account recovery result changed for the same operation",
                    )
                return False
            run = await connection.fetchrow(
                "SELECT 1 FROM guardian_account_recovery_runs WHERE run_id = $1",
                run_id,
            )
            if run is None:
                raise ServiceError(
                    "ACCOUNT_RECOVERY_RUN_NOT_FOUND",
                    "The account recovery run does not exist",
                )
            await connection.execute(
                "INSERT INTO guardian_account_recovery_ledger("
                "ledger_id, run_id, dedup_key, account_id, channel_id, group_id, "
                "classification, result, reason, tested, occurred_at"
                ") VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) "
                "ON CONFLICT(dedup_key) DO NOTHING",
                record.ledger_id,
                record.run_id,
                record.dedup_key,
                record.account_id,
                record.channel_id,
                record.group_id,
                record.classification.value,
                record.result.value,
                record.reason,
                record.tested,
                record.occurred_at,
            )
        return True

    async def list_account_recovery_results(
        self,
        run_id: str,
    ) -> list[GuardianAccountRecoveryRecord]:
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                "SELECT * FROM guardian_account_recovery_ledger WHERE run_id = $1 "
                "ORDER BY occurred_at, ledger_id",
                run_id,
            )
        return [self._account_recovery_record_from_row(row) for row in rows]

    async def list_recent_tested_account_ids(
        self,
        since: datetime,
    ) -> frozenset[str]:
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                "SELECT DISTINCT account_id FROM guardian_account_recovery_ledger "
                "WHERE tested AND occurred_at >= $1 ORDER BY account_id",
                since,
            )
        return frozenset(str(row["account_id"]) for row in rows)

    async def update_policy(
        self, policy: GuardianPolicy, *, expected_revision: int
    ) -> GuardianPolicy:
        # ``FOR UPDATE`` keeps the revision check and the write atomic against
        # a concurrent PATCH, matching SQLite's serialized write lock.
        async with self._database.transaction() as connection:
            row = await connection.fetchrow(
                "SELECT revision FROM guardian_policy WHERE singleton = 1 FOR UPDATE"
            )
            if row is None:
                raise RuntimeError("Guardian repository has not been initialized")
            if int(row["revision"]) != expected_revision:
                raise ServiceError(
                    "POLICY_REVISION_CONFLICT",
                    "The Guardian policy was modified by another session",
                )
            saved = policy.model_copy(update={"revision": expected_revision + 1})
            await connection.execute(
                "UPDATE guardian_policy SET policy_json = $1, revision = $2, updated_at = $3 "
                "WHERE singleton = 1",
                saved.model_dump_json(),
                saved.revision,
                self._clock(),
            )
        return saved

    async def upsert_group_override(self, group_id: str, policy: dict[str, Any]) -> dict[str, Any]:
        now = self._clock()
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT revision FROM guardian_group_overrides WHERE group_id = $1",
                group_id,
            )
            revision = int(row["revision"]) + 1 if row is not None else 1
            await connection.execute(
                "INSERT INTO guardian_group_overrides"
                "(group_id, policy_json, revision, updated_at) VALUES($1, $2, $3, $4) "
                "ON CONFLICT(group_id) DO UPDATE SET policy_json = excluded.policy_json, "
                "revision = excluded.revision, updated_at = excluded.updated_at",
                group_id,
                _json(policy),
                revision,
                now,
            )
        return {"group_id": group_id, "policy": policy, "revision": revision, "updated_at": now}

    async def delete_group_override(self, group_id: str) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                "DELETE FROM guardian_group_overrides WHERE group_id = $1", group_id
            )

    async def list_group_overrides(self) -> dict[str, dict[str, Any]]:
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                "SELECT * FROM guardian_group_overrides ORDER BY group_id"
            )
        return {
            row["group_id"]: {
                "policy": json.loads(row["policy_json"]),
                "revision": int(row["revision"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    async def upsert_channel_override(
        self, channel_id: str, override: ChannelPolicyOverride
    ) -> ChannelPolicyOverride:
        now = self._clock()
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT revision FROM guardian_channel_overrides WHERE channel_id = $1",
                channel_id,
            )
            revision = int(row["revision"]) + 1 if row is not None else 1
            await connection.execute(
                "INSERT INTO guardian_channel_overrides"
                "(channel_id, override_json, revision, updated_at) VALUES($1, $2, $3, $4) "
                "ON CONFLICT(channel_id) DO UPDATE SET override_json = excluded.override_json, "
                "revision = excluded.revision, updated_at = excluded.updated_at",
                channel_id,
                override.model_dump_json(),
                revision,
                now,
            )
        return override

    async def get_channel_override(self, channel_id: str) -> ChannelPolicyOverride | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT override_json FROM guardian_channel_overrides WHERE channel_id = $1",
                channel_id,
            )
        return (
            ChannelPolicyOverride.model_validate_json(row["override_json"])
            if row is not None
            else None
        )

    async def upsert_channel(
        self,
        channel_id: str,
        name: str,
        group_id: str | None,
        upstream_status: str,
        upstream_schedulable: bool,
        health: GuardianHealth,
        score: float,
        latency_ms: int | None,
        desired_schedulable: bool,
        manual_control: ManualControl,
        details: dict[str, Any],
        seen_at: datetime,
        confidence: float,
        freshness_state: GuardianFreshness,
        last_evidence_at: datetime | None,
        warmup_buckets: int,
    ) -> dict[str, Any]:
        now = self._clock()
        seen = seen_at
        async with self._database.acquire() as connection:
            existing = await connection.fetchrow(
                "SELECT first_seen_at FROM guardian_channels WHERE channel_id = $1",
                channel_id,
            )
            first_seen = existing["first_seen_at"] if existing is not None else seen
            await connection.execute(
                "INSERT INTO guardian_channels(channel_id, name, group_id, upstream_status, "
                "upstream_schedulable, health, score, latency_ms, desired_schedulable, "
                "manual_control, details_json, confidence, freshness_state, "
                "last_evidence_at, warmup_buckets, first_seen_at, last_seen_at, updated_at) "
                "VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, "
                "$15, $16, $17, $18) "
                "ON CONFLICT(channel_id) DO UPDATE SET name = excluded.name, "
                "group_id = excluded.group_id, upstream_status = excluded.upstream_status, "
                "upstream_schedulable = excluded.upstream_schedulable, health = excluded.health, "
                "score = excluded.score, latency_ms = excluded.latency_ms, "
                "desired_schedulable = excluded.desired_schedulable, "
                "manual_control = excluded.manual_control, details_json = excluded.details_json, "
                "confidence = excluded.confidence, "
                "freshness_state = excluded.freshness_state, "
                "last_evidence_at = excluded.last_evidence_at, "
                "warmup_buckets = excluded.warmup_buckets, "
                "last_seen_at = excluded.last_seen_at, updated_at = excluded.updated_at",
                channel_id,
                name,
                group_id,
                upstream_status,
                upstream_schedulable,
                health.value,
                score,
                latency_ms,
                desired_schedulable,
                manual_control.value,
                _json(details),
                confidence,
                freshness_state.value,
                last_evidence_at if last_evidence_at is not None else None,
                warmup_buckets,
                first_seen,
                seen,
                now,
            )
            row = await connection.fetchrow(
                "SELECT * FROM guardian_channels WHERE channel_id = $1", channel_id
            )
        assert row is not None
        return self._channel(row)

    async def get_channel(self, channel_id: str) -> dict[str, Any] | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT c.*, o.override_json AS channel_override_json "
                "FROM guardian_channels c LEFT JOIN guardian_channel_overrides o "
                "ON o.channel_id = c.channel_id WHERE c.channel_id = $1",
                channel_id,
            )
        return self._channel(row) if row is not None else None

    async def list_channels(
        self,
        limit: int,
        cursor: str | None,
        group_id: str | None,
        health: str | None,
        query: str | None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise ServiceError("INVALID_PAGE_SIZE", "Page size must be between 1 and 200")
        conditions: list[str] = ["c.removed_at IS NULL"]
        params: list[object] = []
        if group_id:
            params.append(group_id)
            conditions.append(f"c.group_id = ${len(params)}")
        if health:
            params.append(health)
            conditions.append(f"c.health = ${len(params)}")
        if query:
            pattern = f"%{query[:100]}%"
            params.extend((pattern, pattern))
            conditions.append(
                f"(c.name LIKE ${len(params) - 1} OR c.channel_id LIKE ${len(params)})"
            )
        if cursor:
            channel_cursor, _ = _decode_cursor(cursor)
            params.append(channel_cursor)
            conditions.append(f"c.channel_id > ${len(params)}")
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit + 1)
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                "SELECT c.*, o.override_json AS channel_override_json "
                "FROM guardian_channels c LEFT JOIN guardian_channel_overrides o "
                f"ON o.channel_id = c.channel_id {where} "
                f"ORDER BY c.channel_id LIMIT ${len(params)}",
                *params,
            )
        selected = rows[:limit]
        next_cursor = (
            _cursor(selected[-1]["channel_id"], selected[-1]["channel_id"])
            if len(rows) > limit and selected
            else None
        )
        return {
            "items": [self._channel(row) for row in selected],
            "next_cursor": next_cursor,
        }

    async def reconcile_channels(
        self,
        live_channel_ids: set[str] | frozenset[str],
        removed_at: datetime,
    ) -> None:
        ids = {str(channel_id) for channel_id in live_channel_ids}
        removed_at_value = removed_at
        async with self._database.acquire() as connection:
            if ids:
                ordered = sorted(ids)
                statement = (
                    "UPDATE guardian_channels SET removed_at = NULL "
                    "WHERE removed_at IS NOT NULL AND channel_id IN "
                    f"({placeholders(1, len(ordered))})"
                )
                await connection.execute(statement, *ordered)
                await connection.execute(
                    "UPDATE guardian_channels SET removed_at = $1, updated_at = $2 "
                    "WHERE removed_at IS NULL AND channel_id NOT IN "
                    f"({placeholders(3, len(ordered))})",
                    removed_at_value,
                    self._clock(),
                    *ordered,
                )
            else:
                await connection.execute(
                    "UPDATE guardian_channels SET removed_at = $1, updated_at = $2 "
                    "WHERE removed_at IS NULL",
                    removed_at_value,
                    self._clock(),
                )

    async def upsert_groups(
        self,
        groups: list[UpstreamGroupSummary],
        observed_at: datetime,
    ) -> None:
        seen = observed_at
        live_ids = [group.group_id for group in groups]
        async with self._database.acquire() as connection:
            for group in groups:
                await connection.execute(
                    "INSERT INTO guardian_groups(group_id, name, total_count, "
                    "available_count, error_count, temporary_unavailable_count, "
                    "closed_count, first_seen_at, last_seen_at, removed_at) "
                    "VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9, NULL) "
                    "ON CONFLICT(group_id) DO UPDATE SET name = excluded.name, "
                    "total_count = excluded.total_count, "
                    "available_count = excluded.available_count, "
                    "error_count = excluded.error_count, "
                    "temporary_unavailable_count = excluded.temporary_unavailable_count, "
                    "closed_count = excluded.closed_count, "
                    "last_seen_at = excluded.last_seen_at, removed_at = NULL",
                    group.group_id,
                    group.name,
                    group.total_count,
                    group.available_count,
                    group.error_count,
                    group.temporary_unavailable_count,
                    group.closed_count,
                    seen,
                    seen,
                )
            if live_ids:
                ordered = sorted(str(item) for item in live_ids)
                await connection.execute(
                    "UPDATE guardian_groups SET removed_at = $1 "
                    "WHERE removed_at IS NULL AND group_id NOT IN "
                    f"({placeholders(2, len(ordered))})",
                    seen,
                    *ordered,
                )
            else:
                await connection.execute(
                    "UPDATE guardian_groups SET removed_at = $1 WHERE removed_at IS NULL",
                    seen,
                )

    async def list_groups(self) -> list[dict[str, Any]]:
        overrides = self._list_group_overrides_sync()
        async with self._database.acquire() as connection:
            group_rows = await connection.fetch(
                "SELECT * FROM guardian_groups WHERE removed_at IS NULL ORDER BY group_id"
            )
            channel_rows = await connection.fetch(
                "SELECT COALESCE(group_id, 'ungrouped') AS group_id, "
                "MAX(json_extract(details_json, '$.group_name')) AS group_name, "
                "COUNT(*) AS channel_count, "
                "SUM(CASE WHEN desired_schedulable THEN 1 ELSE 0 END) AS available_count, "
                "AVG(score) AS score, AVG(latency_ms) AS latency_ms "
                "FROM guardian_channels WHERE removed_at IS NULL "
                "GROUP BY COALESCE(group_id, 'ungrouped') "
                "ORDER BY group_id"
            )
        channel_stats = {
            row["group_id"]: row for row in channel_rows if row["group_id"] != "ungrouped"
        }
        merged_ids = sorted(
            set(channel_stats) | {row["group_id"] for row in group_rows},
            key=lambda value: (not value.isdigit(), value),
        )
        items: list[dict[str, Any]] = []
        for group_id in merged_ids:
            upstream = next((row for row in group_rows if row["group_id"] == group_id), None)
            stats = channel_stats.get(group_id)
            items.append(
                {
                    "group_id": group_id,
                    "name": (
                        upstream["name"]
                        if upstream is not None
                        else stats["group_name"]
                        if stats is not None and stats["group_name"]
                        else f"分组 {group_id}"
                    ),
                    "channel_count": int(stats["channel_count"]) if stats else 0,
                    "available_count": (int(stats["available_count"] or 0) if stats else 0),
                    "score": (round(float(stats["score"] or 0), 6) if stats else 0.0),
                    "latency_ms": (
                        round(float(stats["latency_ms"]), 3)
                        if stats is not None and stats["latency_ms"] is not None
                        else None
                    ),
                    "upstream_total_count": (
                        int(upstream["total_count"]) if upstream is not None else None
                    ),
                    "upstream_available_count": (
                        int(upstream["available_count"]) if upstream is not None else None
                    ),
                    "upstream_error_count": (
                        int(upstream["error_count"]) if upstream is not None else None
                    ),
                    "override": overrides.get(group_id),
                }
            )
        return items

    async def set_manual_control(
        self, channel_id: str, control: ManualControl | str
    ) -> dict[str, Any]:
        parsed = ManualControl(control)
        health_by_control = {
            ManualControl.NONE: GuardianHealth.PENDING,
            ManualControl.PAUSED: GuardianHealth.MANUALLY_PAUSED,
            ManualControl.EXCLUDED: GuardianHealth.EXCLUDED,
            ManualControl.FUSED: GuardianHealth.FUSED,
        }
        async with self._database.acquire() as connection:
            updated = await connection.execute(
                "UPDATE guardian_channels SET manual_control = $1, health = $2, "
                "desired_schedulable = CASE WHEN $3 = 'NONE' "
                "THEN upstream_schedulable ELSE FALSE END, updated_at = $4 "
                "WHERE channel_id = $5",
                parsed.value,
                health_by_control[parsed].value,
                parsed.value,
                self._clock(),
                channel_id,
            )
            if updated.rowcount != 1:
                raise ServiceError("CHANNEL_NOT_FOUND", "The Guardian channel does not exist")
            row = await connection.fetchrow(
                "SELECT * FROM guardian_channels WHERE channel_id = $1", channel_id
            )
        assert row is not None
        return self._channel(row)

    async def merge_channel_details(
        self, channel_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT details_json FROM guardian_channels WHERE channel_id = $1",
                channel_id,
            )
            if row is None:
                raise ServiceError("CHANNEL_NOT_FOUND", "The Guardian channel does not exist")
            details = cast(dict[str, Any], json.loads(row["details_json"]))
            details.update(updates)
            await connection.execute(
                "UPDATE guardian_channels SET details_json = $1, updated_at = $2 "
                "WHERE channel_id = $3",
                _json(details),
                self._clock(),
                channel_id,
            )
            saved = await connection.fetchrow(
                "SELECT c.*, o.override_json AS channel_override_json "
                "FROM guardian_channels c LEFT JOIN guardian_channel_overrides o "
                "ON o.channel_id = c.channel_id WHERE c.channel_id = $1",
                channel_id,
            )
        assert saved is not None
        return self._channel(saved)

    async def append_sample(self, sample: GuardianSample) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                "INSERT INTO guardian_samples(sample_id, channel_id, source, event_type, "
                "score, occurred_at, ttfb_ms, status_code, message) "
                "VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                str(uuid.uuid4()),
                sample.channel_id,
                sample.source.value,
                sample.event_type.value,
                sample.score,
                sample.occurred_at,
                sample.ttfb_ms,
                sample.status_code,
                sample.message,
            )
            await connection.execute(
                "DELETE FROM guardian_samples WHERE channel_id = $1 AND sample_id NOT IN "
                "(SELECT sample_id FROM guardian_samples WHERE channel_id = $2 "
                "ORDER BY occurred_at DESC, sample_id DESC LIMIT 10000)",
                sample.channel_id,
                sample.channel_id,
            )

    async def append_evidence(
        self,
        evidence: GuardianEvidence,
        *,
        bucket_at: datetime,
    ) -> bool:
        if bucket_at.tzinfo is None:
            raise ValueError("bucket_at must be timezone-aware")
        async with self._database.acquire() as connection:
            status = await connection.execute(
                "INSERT INTO guardian_samples"
                "(sample_id, channel_id, source, event_type, score, occurred_at, ttfb_ms, "
                "status_code, message, source_event_id, bucket_at, reliability, ingested_at, "
                "legacy) VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, FALSE) "
                "ON CONFLICT(sample_id) DO NOTHING",
                str(uuid.uuid4()),
                evidence.channel_id,
                evidence.source.value,
                evidence.event_type.value,
                evidence.score,
                evidence.occurred_at,
                evidence.ttfb_ms,
                evidence.status_code,
                evidence.message,
                evidence.source_event_id,
                bucket_at,
                evidence.reliability,
                self._clock(),
            )
        return _rowcount(status) == 1

    async def list_evidence(
        self,
        channel_id: str,
        since: datetime,
    ) -> list[GuardianEvidence]:
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                "SELECT * FROM guardian_samples WHERE channel_id = $1 AND NOT legacy "
                "AND occurred_at >= $2 ORDER BY occurred_at DESC, sample_id DESC",
                channel_id,
                since,
            )
        evidence: list[GuardianEvidence] = []
        for row in rows:
            occurred_at = _dt(row["occurred_at"])
            assert occurred_at is not None
            # Retention intentionally redacts old source_event_id values.  A
            # stable local identity keeps those samples readable and avoids a
            # scoring-cycle failure after redaction.
            source_event_id = row["source_event_id"] or f"stored:{row['sample_id']}"
            evidence.append(
                GuardianEvidence(
                    source_event_id=source_event_id,
                    channel_id=row["channel_id"],
                    source=row["source"],
                    event_type=row["event_type"],
                    score=int(row["score"]),
                    occurred_at=occurred_at,
                    reliability=float(row["reliability"]),
                    event_count=1,
                    ttfb_ms=row["ttfb_ms"],
                    status_code=row["status_code"],
                    message=row["message"],
                )
            )
        return evidence

    async def list_traffic_buckets(
        self,
        channel_id: str,
        since: datetime,
    ) -> list[GuardianEvidenceBucket]:
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                "SELECT * FROM guardian_traffic_buckets WHERE channel_id = $1 "
                "AND bucket_at >= $2 ORDER BY bucket_at DESC",
                channel_id,
                since,
            )
        buckets: list[GuardianEvidenceBucket] = []
        for row in rows:
            bucket_at = _dt(row["bucket_at"])
            assert bucket_at is not None
            event_count = int(row["event_count"])
            buckets.append(
                GuardianEvidenceBucket(
                    channel_id=channel_id,
                    bucket_at=bucket_at,
                    score=float(row["score_sum"]) / event_count,
                    quality=min(1.0, event_count / 5),
                    sources=frozenset({GuardianSampleSource.TRAFFIC}),
                    event_count=event_count,
                    ttfb_p95_ms=row["ttfb_p95_ms"],
                )
            )
        return buckets

    async def upsert_traffic_buckets(
        self,
        buckets: list[GuardianEvidenceBucket],
    ) -> None:
        now = self._clock()
        async with self._database.acquire() as connection:
            for bucket in buckets:
                if bucket.sources != frozenset({GuardianSampleSource.TRAFFIC}):
                    raise ValueError("only TRAFFIC buckets can be persisted as traffic")
                await connection.execute(
                    "INSERT INTO guardian_traffic_buckets"
                    "(channel_id, bucket_at, event_count, score_sum, ttfb_p95_ms, "
                    "details_json, created_at, updated_at) VALUES($1, $2, $3, $4, $5, $6, $7, $8) "
                    "ON CONFLICT(channel_id, bucket_at) DO UPDATE SET "
                    "event_count = excluded.event_count, score_sum = excluded.score_sum, "
                    "ttfb_p95_ms = excluded.ttfb_p95_ms, "
                    "details_json = excluded.details_json, updated_at = excluded.updated_at",
                    bucket.channel_id,
                    bucket.bucket_at,
                    bucket.event_count,
                    bucket.score * bucket.event_count,
                    bucket.ttfb_p95_ms,
                    _json({"quality": bucket.quality}),
                    now,
                    now,
                )

    async def list_samples(self, channel_id: str, limit: int) -> list[GuardianSample]:
        if not 1 <= limit <= 10_000:
            raise ServiceError("INVALID_PAGE_SIZE", "Sample size must be between 1 and 10000")
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                "SELECT * FROM guardian_samples WHERE channel_id = $1 "
                "ORDER BY occurred_at DESC, sample_id DESC LIMIT $2",
                channel_id,
                limit,
            )
        samples: list[GuardianSample] = []
        for row in rows:
            occurred_at = _dt(row["occurred_at"])
            assert occurred_at is not None
            samples.append(
                GuardianSample(
                    channel_id=row["channel_id"],
                    source=row["source"],
                    event_type=row["event_type"],
                    score=int(row["score"]),
                    occurred_at=occurred_at,
                    ttfb_ms=row["ttfb_ms"],
                    status_code=row["status_code"],
                    message=row["message"],
                )
            )
        return samples

    async def create_run(
        self, *, dry_run: bool, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        key = idempotency_key.strip()[:128] if idempotency_key else None
        now = self._clock()
        run_id = str(uuid.uuid4())
        async with self._database.transaction() as connection:
            if key:
                existing = await connection.fetchrow(
                    "SELECT * FROM guardian_runs WHERE idempotency_key = $1",
                    key,
                )
                if existing is not None:
                    result = self._run(existing)
                    result["created"] = False
                    return result
            await connection.execute(
                "INSERT INTO guardian_runs(run_id, idempotency_key, dry_run, status, "
                "started_at, updated_at) VALUES($1, $2, $3, 'RUNNING', $4, $5)",
                run_id,
                key,
                dry_run,
                now,
                now,
            )
            row = await connection.fetchrow("SELECT * FROM guardian_runs WHERE run_id = $1", run_id)
        if row is None:
            raise RuntimeError("Guardian run disappeared after insert")
        result = self._run(row)
        result["created"] = True
        return result

    async def finish_run(
        self,
        run_id: str,
        status: str,
        result: dict[str, Any] | None,
        error_code: str | None,
        error_message: str | None,
    ) -> dict[str, Any]:
        if status not in {"SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"}:
            raise ValueError("invalid Guardian run terminal status")
        now = self._clock()
        async with self._database.acquire() as connection:
            updated = await connection.execute(
                "UPDATE guardian_runs SET status = $1, result_json = $2, error_code = $3, "
                "error_message = $4, finished_at = $5, updated_at = $6 "
                "WHERE run_id = $7 AND status = 'RUNNING'",
                status,
                _json(result) if result is not None else None,
                error_code,
                error_message,
                now,
                now,
                run_id,
            )
            if updated.rowcount != 1:
                raise ServiceError("INVALID_RUN_STATE", "The Guardian run is not running")
            row = await connection.fetchrow("SELECT * FROM guardian_runs WHERE run_id = $1", run_id)
        assert row is not None
        return self._run(row)

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow("SELECT * FROM guardian_runs WHERE run_id = $1", run_id)
        return self._run(row) if row is not None else None

    async def list_runs(self, limit: int) -> list[dict[str, Any]]:
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                "SELECT * FROM guardian_runs ORDER BY started_at DESC, run_id DESC LIMIT $1",
                max(1, min(limit, 100)),
            )
        return [self._run(row) for row in rows]

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        async with self._database.acquire() as connection:
            updated = await connection.execute(
                "UPDATE guardian_runs SET cancel_requested = TRUE, updated_at = $1 "
                "WHERE run_id = $2 AND status = 'RUNNING'",
                self._clock(),
                run_id,
            )
            if updated.rowcount != 1:
                raise ServiceError("INVALID_RUN_STATE", "The Guardian run is not running")
            row = await connection.fetchrow("SELECT * FROM guardian_runs WHERE run_id = $1", run_id)
        assert row is not None
        return self._run(row)

    async def add_event(
        self,
        event_type: str,
        severity: str,
        message: str,
        channel_id: str | None,
        group_id: str | None,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        event_id = str(uuid.uuid4())
        now = self._clock()
        async with self._database.acquire() as connection:
            await connection.execute(
                "INSERT INTO guardian_events(event_id, event_type, severity, channel_id, "
                "group_id, message, details_json, created_at) "
                "VALUES($1, $2, $3, $4, $5, $6, $7, $8)",
                event_id,
                event_type[:64],
                severity[:16],
                channel_id,
                group_id,
                message[:1000],
                _json(details),
                now,
            )
            await connection.execute(
                "DELETE FROM guardian_events WHERE event_id NOT IN "
                "(SELECT event_id FROM guardian_events "
                "ORDER BY created_at DESC, event_id DESC LIMIT 100000)"
            )
        return {
            "event_id": event_id,
            "event_type": event_type[:64],
            "severity": severity[:16],
            "channel_id": channel_id,
            "group_id": group_id,
            "message": message[:1000],
            "details": details,
            "created_at": now,
        }

    async def list_events(
        self,
        limit: int,
        cursor: str | None,
        event_type: str | None,
        severity: str | None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise ServiceError("INVALID_PAGE_SIZE", "Page size must be between 1 and 200")
        conditions: list[str] = []
        params: list[object] = []
        if event_type:
            params.append(event_type[:64])
            conditions.append(f"event_type = ${len(params)}")
        if severity:
            params.append(severity[:16])
            conditions.append(f"severity = ${len(params)}")
        if cursor:
            created_at, event_id = _decode_cursor(cursor)
            params.extend((created_at, created_at, event_id))
            conditions.append(
                f"(created_at < ${len(params) - 2} "
                f"OR (created_at = ${len(params) - 2} AND event_id < ${len(params)}))"
            )
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit + 1)
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT * FROM guardian_events {where} "
                f"ORDER BY created_at DESC, event_id DESC LIMIT ${len(params)}",
                *params,
            )
        selected = rows[:limit]
        return {
            "items": [self._event(row) for row in selected],
            "next_cursor": (
                _cursor(selected[-1]["created_at"], selected[-1]["event_id"])
                if len(rows) > limit and selected
                else None
            ),
        }

    async def acquire_lease(self, lease_key: str, owner: str, *, seconds: int) -> bool:
        now = self._clock().astimezone(UTC)
        expires_at = now + timedelta(seconds=seconds)
        # ``FOR UPDATE`` on the existing lease row serializes two contenders,
        # which SQLite's write lock provided implicitly; when no row exists the
        # INSERT .. ON CONFLICT handles the race instead.
        async with self._database.transaction() as connection:
            row = await connection.fetchrow(
                "SELECT owner, expires_at FROM guardian_leases WHERE lease_key = $1 FOR UPDATE",
                lease_key,
            )
            if row is not None and row["owner"] != owner and row["expires_at"] > now:
                return False
            await connection.execute(
                "INSERT INTO guardian_leases(lease_key, owner, expires_at) "
                "VALUES($1, $2, $3) "
                "ON CONFLICT(lease_key) DO UPDATE SET owner = excluded.owner, "
                "expires_at = excluded.expires_at",
                lease_key,
                owner,
                expires_at,
            )
        return True

    async def release_lease(self, lease_key: str, owner: str) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                "DELETE FROM guardian_leases WHERE lease_key = $1 AND owner = $2",
                lease_key,
                owner,
            )

    async def overview(self) -> dict[str, Any]:
        counts, runs, policy = await asyncio.gather(
            self._overview_counts_sync(),
            self.list_runs(limit=1),
            self.get_policy(),
        )
        return {
            "enabled": policy.enabled,
            "policy_revision": policy.revision,
            "channel_count": counts["channel_count"],
            "group_count": counts["group_count"],
            "health_counts": counts["health_counts"],
            "last_run": runs[0] if runs else None,
        }

    async def _overview_counts_sync(self) -> dict[str, Any]:
        async with self._database.acquire() as connection:
            totals = await connection.fetchrow(
                "SELECT COUNT(*) AS channel_count, "
                "COUNT(DISTINCT COALESCE(group_id, 'ungrouped')) AS group_count "
                "FROM guardian_channels"
            )
            rows = await connection.fetch(
                "SELECT health, COUNT(*) AS count FROM guardian_channels GROUP BY health"
            )
        return {
            "channel_count": int(totals["channel_count"] if totals else 0),
            "group_count": int(totals["group_count"] if totals else 0),
            "health_counts": {str(row["health"]): int(row["count"]) for row in rows},
        }

    async def probe_spend(self) -> dict[str, Any]:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT COUNT(*) AS probes, SUM(estimated_cost) AS cost, "
                "SUM(CASE WHEN NOT priced THEN 1 ELSE 0 END) AS unpriced "
                "FROM guardian_probe_ledger"
            )
        return {
            "probe_count": int(row["probes"] or 0),
            "estimated_cost": float(row["cost"] or 0),
            "unpriced_count": int(row["unpriced"] or 0),
            "currency": "USD",
        }

    async def sampling_status(self) -> dict[str, Any]:
        async with self._database.acquire() as connection:
            snapshots = await connection.fetchrow(
                "SELECT COUNT(*) AS total, "
                "COUNT(CASE WHEN consumed_at IS NULL THEN 1 END) AS pending, "
                "MAX(captured_at) AS latest FROM guardian_input_snapshots"
            )
            traffic = await connection.fetchrow(
                "SELECT COUNT(*) AS count, MAX(bucket_at) AS latest FROM guardian_traffic_buckets"
            )
            freshness = await connection.fetch(
                "SELECT freshness_state, COUNT(*) AS count FROM guardian_channels "
                "GROUP BY freshness_state"
            )
        return {
            "shared_snapshots": int(snapshots["total"] or 0),
            "pending_snapshots": int(snapshots["pending"] or 0),
            "latest_snapshot_at": snapshots["latest"],
            "traffic_buckets": int(traffic["count"] or 0),
            "latest_traffic_bucket_at": traffic["latest"],
            "channels_by_freshness": {
                row["freshness_state"]: int(row["count"]) for row in freshness
            },
        }

    async def record_recovery_probe(
        self,
        channel_id: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        estimated_cost: float | None,
        priced: bool,
        occurred_at: datetime,
        blocked_reason: str | None,
    ) -> None:
        if occurred_at.tzinfo is None:
            raise ValueError("probe ledger time must be timezone-aware")
        async with self._database.acquire() as connection:
            await connection.execute(
                "INSERT INTO guardian_probe_ledger"
                "(ledger_id, channel_id, model, input_tokens, output_tokens, estimated_cost, "
                "priced, budget_date, request_source, blocked_reason, occurred_at) "
                "VALUES($1, $2, $3, $4, $5, $6, $7, $8, 'RECOVERY_PROBE', $9, $10)",
                str(uuid.uuid4()),
                channel_id,
                model[:200],
                input_tokens,
                output_tokens,
                estimated_cost,
                priced,
                occurred_at.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(),
                blocked_reason[:200] if blocked_reason else None,
                occurred_at,
            )

    async def record_recovery_probe_blocked(
        self,
        *,
        channel_id: str,
        reason: str,
        occurred_at: datetime,
    ) -> None:
        await self.record_recovery_probe(
            channel_id,
            "",
            None,
            None,
            None,
            False,
            occurred_at,
            reason,
        )

    async def recovery_probe_budget_summary(self, budget_date: str) -> dict[str, Any]:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT COUNT(CASE WHEN blocked_reason IS NULL THEN 1 END) AS requests, "
                "SUM(CASE WHEN blocked_reason IS NULL "
                "THEN COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0) ELSE 0 END) "
                "AS tokens, SUM(CASE WHEN blocked_reason IS NULL THEN estimated_cost ELSE 0 END) "
                "AS cost, COUNT(CASE WHEN blocked_reason IS NOT NULL THEN 1 END) AS blocked "
                "FROM guardian_probe_ledger "
                "WHERE request_source = 'RECOVERY_PROBE' AND budget_date = $1",
                budget_date,
            )
        return {
            "request_count": int(row["requests"] or 0),
            "total_tokens": int(row["tokens"] or 0),
            "estimated_cost": float(row["cost"] or 0),
            "blocked_count": int(row["blocked"] or 0),
        }

    async def cleanup_retention(
        self,
        *,
        now: datetime | None = None,
        batch_size: int = 500,
    ) -> dict[str, int]:
        """Remove or redact eligible evidence within one global bounded batch."""
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
            "dedup": now - timedelta(days=7),
            "account_observations": now - timedelta(days=2),
            "runs": now - timedelta(days=7),
            "traffic": now - timedelta(days=30),
            "events": now - timedelta(days=90),
            "probes": now - timedelta(days=90),
            "recovery": now - timedelta(days=90),
            "samples": now - timedelta(days=90),
            "snapshots": now - timedelta(days=90),
        }
        counts = {
            "account_observations": 0,
            "runs": 0,
            "events": 0,
            "probe_ledger": 0,
            "closed_episodes": 0,
            "recovery_runs": 0,
            "idempotency": 0,
            "samples": 0,
            "traffic_buckets": 0,
            "snapshots": 0,
            "snapshot_payloads_redacted": 0,
            "source_ids_redacted": 0,
        }
        remaining = batch_size
        # Postgres exposes the physical row id as ``ctid``; it plays the role
        # ``rowid`` had in the batched deletes below.  One transaction keeps the
        # whole cleanup atomic, matching the former BEGIN IMMEDIATE block.
        async with self._database.transaction() as connection:
            queued_recovery_guard = (
                "AND NOT EXISTS (SELECT 1 FROM jobs j "
                "WHERE j.job_type = 'RECOVERY' AND j.status IN ('QUEUED', 'RUNNING') "
                "AND j.payload_json::jsonb ->> 'snapshot_id' = o.snapshot_id) "
            )

            async def execute_bounded(
                key: str,
                sql: str,
                cutoff: datetime,
            ) -> None:
                nonlocal remaining
                if remaining <= 0:
                    return
                status = await connection.execute(sql, cutoff, remaining)
                changed = max(0, _rowcount(status))
                counts[key] += changed
                remaining -= changed

            await execute_bounded(
                "account_observations",
                "DELETE FROM guardian_account_observations WHERE ctid IN "
                "(SELECT o.ctid FROM guardian_account_observations o "
                "WHERE o.observed_at < $1 "
                "AND NOT EXISTS (SELECT 1 FROM guardian_channel_error_episodes e "
                "WHERE e.status = 'OPEN' AND e.opened_snapshot_id = o.snapshot_id) "
                "AND NOT EXISTS (SELECT 1 FROM guardian_account_recovery_runs r "
                "WHERE r.status = 'RUNNING' AND r.snapshot_id = o.snapshot_id) "
                f"{queued_recovery_guard}"
                "ORDER BY o.observed_at LIMIT $2)",
                cutoffs["account_observations"],
            )
            await execute_bounded(
                "runs",
                "DELETE FROM guardian_runs WHERE ctid IN "
                "(SELECT ctid FROM guardian_runs WHERE status <> 'RUNNING' "
                "AND COALESCE(finished_at, updated_at) < $1 "
                "ORDER BY updated_at LIMIT $2)",
                cutoffs["runs"],
            )
            await execute_bounded(
                "events",
                "DELETE FROM guardian_events WHERE ctid IN "
                "(SELECT ctid FROM guardian_events WHERE created_at < $1 "
                "ORDER BY created_at LIMIT $2)",
                cutoffs["events"],
            )
            await execute_bounded(
                "probe_ledger",
                "DELETE FROM guardian_probe_ledger WHERE ctid IN "
                "(SELECT ctid FROM guardian_probe_ledger WHERE occurred_at < $1 "
                "ORDER BY occurred_at LIMIT $2)",
                cutoffs["probes"],
            )
            await execute_bounded(
                "closed_episodes",
                "DELETE FROM guardian_channel_error_episodes WHERE ctid IN "
                "(SELECT ctid FROM guardian_channel_error_episodes "
                "WHERE status = 'CLOSED' AND COALESCE(closed_at, updated_at) < $1 "
                "ORDER BY updated_at LIMIT $2)",
                cutoffs["recovery"],
            )
            await execute_bounded(
                "recovery_runs",
                "DELETE FROM guardian_account_recovery_runs WHERE ctid IN "
                "(SELECT ctid FROM guardian_account_recovery_runs "
                "WHERE status <> 'RUNNING' AND COALESCE(finished_at, updated_at) < $1 "
                "ORDER BY updated_at LIMIT $2)",
                cutoffs["recovery"],
            )
            await execute_bounded(
                "idempotency",
                "DELETE FROM guardian_idempotency WHERE ctid IN "
                "(SELECT ctid FROM guardian_idempotency WHERE created_at < $1 "
                "ORDER BY created_at LIMIT $2)",
                cutoffs["dedup"],
            )
            await execute_bounded(
                "samples",
                "DELETE FROM guardian_samples WHERE ctid IN "
                "(SELECT ctid FROM guardian_samples WHERE occurred_at < $1 "
                "ORDER BY occurred_at LIMIT $2)",
                cutoffs["samples"],
            )
            await execute_bounded(
                "traffic_buckets",
                "DELETE FROM guardian_traffic_buckets WHERE ctid IN "
                "(SELECT ctid FROM guardian_traffic_buckets WHERE bucket_at < $1 "
                "ORDER BY bucket_at LIMIT $2)",
                cutoffs["traffic"],
            )
            await execute_bounded(
                "snapshots",
                "DELETE FROM guardian_input_snapshots WHERE ctid IN "
                "(SELECT ctid FROM guardian_input_snapshots "
                "WHERE consumed_at IS NOT NULL AND captured_at < $1 "
                "ORDER BY captured_at LIMIT $2)",
                cutoffs["snapshots"],
            )
            await execute_bounded(
                "snapshot_payloads_redacted",
                "UPDATE guardian_input_snapshots SET payload_json = '{}' WHERE ctid IN "
                "(SELECT ctid FROM guardian_input_snapshots "
                "WHERE consumed_at IS NOT NULL AND captured_at < $1 AND payload_json <> '{}' "
                "ORDER BY captured_at LIMIT $2)",
                cutoffs["dedup"],
            )
            await execute_bounded(
                "source_ids_redacted",
                "UPDATE guardian_samples SET source_event_id = NULL WHERE ctid IN "
                "(SELECT ctid FROM guardian_samples "
                "WHERE occurred_at < $1 AND source_event_id IS NOT NULL "
                "ORDER BY occurred_at LIMIT $2)",
                cutoffs["dedup"],
            )
        counts["deleted_total"] = sum(
            counts[key]
            for key in (
                "account_observations",
                "runs",
                "events",
                "probe_ledger",
                "closed_episodes",
                "recovery_runs",
                "idempotency",
                "samples",
                "traffic_buckets",
                "snapshots",
            )
        )
        counts["processed_total"] = batch_size - remaining
        return counts

    async def get_idempotent_result(
        self, idempotency_key: str, action: str, subject: str | None
    ) -> dict[str, Any] | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT result_json FROM guardian_idempotency "
                "WHERE idempotency_key = $1 AND action = $2 AND subject = $3",
                idempotency_key,
                action,
                subject or "",
            )
        return cast(dict[str, Any], json.loads(row["result_json"])) if row is not None else None

    async def save_idempotent_result(
        self,
        idempotency_key: str,
        action: str,
        subject: str | None,
        result: dict[str, Any],
    ) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                "INSERT INTO guardian_idempotency"
                "(idempotency_key, action, subject, result_json, created_at) "
                "VALUES($1, $2, $3, $4, $5) "
                "ON CONFLICT(idempotency_key, action, subject) DO NOTHING",
                idempotency_key,
                action,
                subject or "",
                _json(result),
                self._clock(),
            )
            # Postgres has no ``rowid``; trim by the composite primary key's
            # ordering column instead of SQLite's implicit row identity.
            await connection.execute(
                "DELETE FROM guardian_idempotency WHERE ctid IN "
                "(SELECT ctid FROM guardian_idempotency "
                "ORDER BY created_at DESC LIMIT 10000 OFFSET 10000)"
            )

    async def get_account_preferred_model(self, account_id: str) -> str | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT preferred_probe_model FROM guardian_account_preferences "
                "WHERE account_id = $1",
                account_id,
            )
            if row is None or not row["preferred_probe_model"]:
                return None
            return str(row["preferred_probe_model"])

    async def set_account_preferred_model(self, account_id: str, model: str | None) -> None:
        now = self._clock()
        async with self._database.acquire() as connection:
            if model:
                await connection.execute(
                    "INSERT INTO guardian_account_preferences("
                    "account_id, preferred_probe_model, updated_at) VALUES($1, $2, $3) "
                    "ON CONFLICT(account_id) DO UPDATE SET "
                    "preferred_probe_model = excluded.preferred_probe_model, "
                    "updated_at = excluded.updated_at",
                    account_id,
                    model,
                    now,
                )
            else:
                await connection.execute(
                    "DELETE FROM guardian_account_preferences WHERE account_id = $1",
                    account_id,
                )

    @staticmethod
    def _account_observation_from_row(
        row: Any,
    ) -> GuardianAccountObservation:
        try:
            row_keys = row.keys()
            return GuardianAccountObservation.model_validate(
                {
                    "account_id": row["account_id"],
                    "group_ids": json.loads(row["group_ids_json"]),
                    "status": row["status"],
                    "schedulable": bool(row["schedulable"]),
                    "expired": bool(row["expired"]),
                    "temporary_unavailable": bool(row["temporary_unavailable"]),
                    "automatic_pause": (
                        bool(row["automatic_pause"]) if "automatic_pause" in row_keys else False
                    ),
                }
            )
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ServiceError(
                "ACCOUNT_OBSERVATION_DATA_INVALID",
                "Persisted Guardian account observation data is invalid",
            ) from exc

    @staticmethod
    def _channel_error_episode_from_row(
        row: Any,
    ) -> GuardianChannelErrorEpisode:
        try:
            return GuardianChannelErrorEpisode.model_validate(
                {
                    "episode_id": row["episode_id"],
                    "channel_id": row["channel_id"],
                    "group_id": row["group_id"],
                    "opened_snapshot_id": row["opened_snapshot_id"],
                    "status": row["status"],
                    "opened_at": _dt(row["opened_at"]),
                    "closed_at": _dt(row["closed_at"]),
                }
            )
        except (ValidationError, ValueError, TypeError) as exc:
            raise ServiceError(
                "CHANNEL_ERROR_EPISODE_DATA_INVALID",
                "Persisted Guardian channel error episode data is invalid",
            ) from exc

    @staticmethod
    def _account_recovery_run_from_row(
        row: Any,
    ) -> GuardianAccountRecoveryRun:
        try:
            return GuardianAccountRecoveryRun.model_validate(
                {
                    "run_id": row["run_id"],
                    "dedup_key": row["dedup_key"],
                    "trigger": row["trigger"],
                    "snapshot_id": row["snapshot_id"],
                    "episode_id": row["episode_id"],
                    "policy_revision": row["policy_revision"],
                    "status": row["status"],
                    "result": (
                        json.loads(row["result_json"]) if row["result_json"] is not None else None
                    ),
                    "started_at": _dt(row["started_at"]),
                    "finished_at": _dt(row["finished_at"]),
                }
            )
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ServiceError(
                "ACCOUNT_RECOVERY_RUN_DATA_INVALID",
                "Persisted Guardian account recovery run data is invalid",
            ) from exc

    @staticmethod
    def _account_recovery_record_from_row(
        row: Any,
    ) -> GuardianAccountRecoveryRecord:
        try:
            return GuardianAccountRecoveryRecord.model_validate(
                {
                    "ledger_id": row["ledger_id"],
                    "run_id": row["run_id"],
                    "dedup_key": row["dedup_key"],
                    "account_id": row["account_id"],
                    "channel_id": row["channel_id"],
                    "group_id": row["group_id"],
                    "classification": row["classification"],
                    "result": row["result"],
                    "reason": row["reason"],
                    "tested": bool(row["tested"]),
                    "occurred_at": _dt(row["occurred_at"]),
                }
            )
        except (ValidationError, ValueError, TypeError) as exc:
            raise ServiceError(
                "ACCOUNT_RECOVERY_RESULT_DATA_INVALID",
                "Persisted Guardian account recovery result data is invalid",
            ) from exc

    @staticmethod
    def _channel(row: Any) -> dict[str, Any]:
        try:
            override_json = row["channel_override_json"]
        except IndexError:
            override_json = None
        return {
            "channel_id": row["channel_id"],
            "name": row["name"],
            "group_id": row["group_id"],
            "upstream_status": row["upstream_status"],
            "upstream_schedulable": bool(row["upstream_schedulable"]),
            "health": row["health"],
            "score": float(row["score"]),
            "confidence": float(row["confidence"]),
            "freshness_state": row["freshness_state"],
            "last_evidence_at": row["last_evidence_at"],
            "warmup_buckets": int(row["warmup_buckets"]),
            "latency_ms": row["latency_ms"],
            "desired_schedulable": bool(row["desired_schedulable"]),
            "manual_control": row["manual_control"],
            "details": json.loads(row["details_json"]),
            "override": json.loads(override_json) if override_json else None,
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
            "updated_at": row["updated_at"],
            "removed_at": row["removed_at"],
        }

    @staticmethod
    def _run(row: Any) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "dry_run": bool(row["dry_run"]),
            "status": row["status"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "cancel_requested": bool(row["cancel_requested"]),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _event(row: Any) -> dict[str, Any]:
        return {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "severity": row["severity"],
            "channel_id": row["channel_id"],
            "group_id": row["group_id"],
            "message": row["message"],
            "details": json.loads(row["details_json"]),
            "created_at": row["created_at"],
        }
