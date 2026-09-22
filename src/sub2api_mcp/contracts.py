"""Stable public and persistence contracts for the scheduler service."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JobType(StrEnum):
    PROBE = "PROBE"
    RECOVERY = "RECOVERY"
    MAINTENANCE = "MAINTENANCE"
    # Retained only so historical rows remain readable after video generation
    # was removed from the runtime.
    VIDEO = "VIDEO"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


TERMINAL_JOB_STATUSES = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INTERRUPTED}
)


class JobRecord(StrictModel):
    job_id: str
    job_type: JobType
    status: JobStatus
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    cancel_requested: bool = False
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobPage(StrictModel):
    items: list[JobRecord]
    next_cursor: str | None = None


class AccountBinding(StrictModel):
    actor_key: str
    user_id: str
    masked_email: str
    bound_at: datetime


class AccountQuarantineReason(StrEnum):
    SLOW_FIRST_TOKEN = "SLOW_FIRST_TOKEN"
    CHANNEL_TEST_FAILED = "CHANNEL_TEST_FAILED"


class QuarantineProbeResult(StrEnum):
    NEVER = "NEVER"
    PASSING = "PASSING"
    RECOVERED = "RECOVERED"
    FAILED = "FAILED"
    SLOW = "SLOW"
    INVALID = "INVALID"


class QuarantineProbeAttempt(StrictModel):
    account_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    result: QuarantineProbeResult
    latency_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    recovered: bool = False

    @model_validator(mode="after")
    def validate_probe_attempt(self) -> QuarantineProbeAttempt:
        if self.result is QuarantineProbeResult.NEVER:
            raise ValueError("a probe attempt cannot use NEVER")
        if self.result in {
            QuarantineProbeResult.PASSING,
            QuarantineProbeResult.SLOW,
        } and self.latency_ms is None:
            raise ValueError("latency probe attempts require measured latency")
        if self.recovered != (self.result is QuarantineProbeResult.RECOVERED):
            raise ValueError("successful probe attempts require verified recovery")
        return self


class AccountQuarantineRecord(StrictModel):
    account_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    reason: AccountQuarantineReason
    group_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    threshold_ms: int = Field(ge=1, le=3_600_000)
    observed_count: int = Field(ge=1, le=1_000_000)
    quarantined_at: datetime
    last_probe_at: datetime | None = None
    last_probe_latency_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    last_probe_result: QuarantineProbeResult = QuarantineProbeResult.NEVER
    recovery_success_streak: int = Field(default=0, ge=0, le=1)

    @field_validator("group_ids")
    @classmethod
    def validate_group_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not re.fullmatch(r"[1-9][0-9]{0,19}", item) for item in value):
            raise ValueError("group IDs must be positive decimal identifiers")
        normalized = tuple(sorted(set(value), key=int))
        if normalized != value:
            raise ValueError("group IDs must be unique and numerically sorted")
        return value

    @field_validator("quarantined_at", "last_probe_at")
    @classmethod
    def validate_quarantine_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("quarantine timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_probe_fields(self) -> AccountQuarantineRecord:
        if self.last_probe_result is QuarantineProbeResult.NEVER:
            if self.last_probe_at is not None or self.last_probe_latency_ms is not None:
                raise ValueError("an unprobed quarantine cannot have probe observations")
        elif self.last_probe_at is None:
            raise ValueError("last_probe_at is required after a quarantine probe")
        if (
            self.last_probe_result is QuarantineProbeResult.SLOW
            and self.last_probe_latency_ms is None
        ):
            raise ValueError("slow quarantine probes require measured latency")
        if self.last_probe_result is QuarantineProbeResult.PASSING:
            if (
                self.reason is not AccountQuarantineReason.SLOW_FIRST_TOKEN
                or self.recovery_success_streak != 1
                or self.last_probe_latency_ms is None
                or self.last_probe_latency_ms > self.threshold_ms
            ):
                raise ValueError("passing slow probes require one verified fast result")
        elif self.recovery_success_streak != 0:
            raise ValueError("only a passing slow probe can retain a success streak")
        return self


class AccountQuarantinePage(StrictModel):
    items: list[AccountQuarantineRecord]
    next_cursor: str | None = None


class AccountQuarantineIntent(StrictModel):
    account_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    reason: AccountQuarantineReason
    group_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    threshold_ms: int = Field(ge=1, le=3_600_000)
    observed_count: int = Field(ge=1, le=1_000_000)
    previous_status: str = Field(pattern=r"^(active|error)$")
    previous_schedulable: bool
    created_at: datetime

    @field_validator("group_ids")
    @classmethod
    def validate_intent_group_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not re.fullmatch(r"[1-9][0-9]{0,19}", item) for item in value):
            raise ValueError("group IDs must be positive decimal identifiers")
        if tuple(sorted(set(value), key=int)) != value:
            raise ValueError("group IDs must be unique and numerically sorted")
        return value

    @field_validator("created_at")
    @classmethod
    def validate_intent_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("quarantine intent timestamp must be timezone-aware")
        return value


class AccountQuarantineRestoreIntent(StrictModel):
    account_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_restore_intent_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("quarantine restore timestamp must be timezone-aware")
        return value

class MaintenanceOutcomeCode(StrEnum):
    QUARANTINED = "QUARANTINED"
    MIN_POOL_PROTECTED = "MIN_POOL_PROTECTED"
    MINIMUM_POOL_PROTECTED = "MIN_POOL_PROTECTED"
    NO_HEALTHY_ACCOUNT = "NO_HEALTHY_ACCOUNT"
    AMBIGUOUS_GROUP_MAPPING = "AMBIGUOUS_GROUP_MAPPING"
    SWEEP_LIMIT_REACHED = "SWEEP_LIMIT_REACHED"
    MUTATION_STATE_UNCERTAIN = "MUTATION_STATE_UNCERTAIN"


class MaintenanceOutcome(StrictModel):
    outcome: MaintenanceOutcomeCode
    account_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,19}$")
    account_name: str | None = Field(default=None, min_length=1, max_length=200)
    reason: AccountQuarantineReason | None = None
    group_ids: tuple[str, ...] = Field(default=(), max_length=100)
    group_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,19}$")
    group_name: str | None = Field(default=None, min_length=1, max_length=200)
    threshold_ms: int | None = Field(default=None, ge=1, le=3_600_000)
    observed_count: int | None = Field(default=None, ge=1, le=1_000_000)
    protected_group_ids: tuple[str, ...] = Field(default=(), max_length=100)

    @field_validator("protected_group_ids")
    @classmethod
    def validate_protected_group_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not re.fullmatch(r"[1-9][0-9]{0,19}", item) for item in value):
            raise ValueError("protected group IDs must be positive decimal identifiers")
        if tuple(sorted(set(value), key=int)) != value:
            raise ValueError("protected group IDs must be unique and numerically sorted")
        return value

    @field_validator("group_ids")
    @classmethod
    def validate_outcome_group_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not re.fullmatch(r"[1-9][0-9]{0,19}", item) for item in value):
            raise ValueError("group IDs must be positive decimal identifiers")
        if tuple(sorted(set(value), key=int)) != value:
            raise ValueError("group IDs must be unique and numerically sorted")
        return value

    @model_validator(mode="after")
    def validate_outcome_fields(self) -> MaintenanceOutcome:
        if self.outcome is MaintenanceOutcomeCode.QUARANTINED and (
            self.account_id is None
            or self.account_name is None
            or self.reason is None
            or not self.group_ids
            or self.threshold_ms is None
            or self.observed_count is None
        ):
            raise ValueError("quarantined outcomes require complete marker fields")
        if self.outcome is not MaintenanceOutcomeCode.QUARANTINED and self.group_ids:
            raise ValueError("non-quarantine outcomes cannot create marker groups")
        if (
            self.protected_group_ids
            and self.outcome is not MaintenanceOutcomeCode.MIN_POOL_PROTECTED
        ):
            raise ValueError("protected groups require a minimum-pool outcome")
        return self


class MaintenanceOutcomeBatch(StrictModel):
    items: list[MaintenanceOutcome] = Field(max_length=2000)


class AccountObservationStatus(StrEnum):
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"
    INACTIVE = "inactive"


class AccountObservation(StrictModel):
    account_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    group_ids: tuple[str, ...] = Field(default=(), max_length=100)
    status: AccountObservationStatus
    schedulable: bool
    expired: bool = False
    temporary_unavailable: bool = False
    # ``schedulable=false`` is ambiguous in Sub2API: it can be an explicit
    # human pause or an automatic protection applied after an upstream error,
    # rate limit, or overload.  Adapters set this provenance bit only when the
    # upstream metadata (or a previously observed error transition) supports
    # the automatic interpretation.  A missing/false value remains fail-safe
    # and is treated as a human pause by Guardian.
    automatic_pause: bool = False

    @field_validator("group_ids")
    @classmethod
    def validate_group_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not re.fullmatch(r"[1-9][0-9]{0,19}", item) for item in value):
            raise ValueError("group IDs must be positive decimal identifiers")
        if tuple(sorted(set(value), key=int)) != value:
            raise ValueError("group IDs must be unique and numerically sorted")
        return value


class ProbeResult(StrictModel):
    snapshot: dict[str, Any]
    report: str = Field(min_length=1, max_length=50000)
    image_base64: str | None = Field(default=None, max_length=16 * 1024 * 1024)
    guardian_snapshot: dict[str, Any] | None = None
    account_observations: tuple[AccountObservation, ...] = Field(
        default=(),
        max_length=10_000,
    )
    captured_at: datetime | None = None

    @model_validator(mode="after")
    def validate_guardian_snapshot_time(self) -> ProbeResult:
        if (self.guardian_snapshot is None) != (self.captured_at is None):
            raise ValueError("guardian_snapshot and captured_at must be supplied together")
        if self.captured_at is not None and self.captured_at.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")
        return self
