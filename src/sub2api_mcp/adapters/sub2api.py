"""Adapter around the existing validated Sub2API scheduling domain modules."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from bindings import mask_email
from maintenance import (
    AccountDisableResult,
    AccountDispatchState,
    MaintenanceAdjustment,
    MaintenanceMutationObserver,
    MaintenancePolicy,
    MaintenanceServiceFactory,
)
from maintenance_gateway import (
    AdminChannelSummary,
    AdminGroupApiKey,
    AdminGroupSummary,
    AdminMonitorSummary,
)
from monitor import Sub2APIClient
from notification_image import render_status_report_image
from probe import ChannelProbe, GroupAccountCounts, ProbeSnapshot, format_status_report
from pydantic import TypeAdapter

from ..actor_bridge import ActorAccount
from ..config import Settings
from ..contracts import (
    AccountObservation,
    AccountObservationStatus,
    AccountQuarantineIntent,
    AccountQuarantineReason,
    AccountQuarantineRecord,
    MaintenanceOutcome,
    MaintenanceOutcomeCode,
    ProbeResult,
    QuarantineProbeAttempt,
    QuarantineProbeResult,
)
from ..guardian.contracts import (
    AccountMutationResult,
    AccountTestExecutionResult,
    GuardianAccountMutationOutcome,
    GuardianAccountObservation,
    GuardianAccountStatus,
    GuardianAccountTestOutcome,
    UpstreamProbeSnapshot,
)

_SNAPSHOT_ADAPTER = TypeAdapter(dict[str, Any])

_REASON_MAP = {
    "channel_test_failed": AccountQuarantineReason.CHANNEL_TEST_FAILED,
    "slow_first_token": AccountQuarantineReason.SLOW_FIRST_TOKEN,
}


def _monitor_observed_at(
    value: str,
    *,
    captured_at: datetime,
) -> datetime | None:
    """Parse the upstream monitor's own observation timestamp.

    The channel-monitor endpoint is cached by Sub2API and can legitimately be
    older than the admin request that retrieves it.  Invalid or future values
    fail the snapshot so they cannot move Guardian evidence into the future.
    """

    if not value:
        raise ValueError("upstream monitor observation time is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid upstream monitor observation time") from None
    if parsed.tzinfo is None:
        raise ValueError("upstream monitor observation time must be timezone-aware")
    observed_at = parsed.astimezone(UTC)
    if observed_at > captured_at:
        raise ValueError("upstream monitor observation time is in the future")
    return observed_at


def _monitor_probe_is_fresh(
    probe: ChannelProbe,
    *,
    now: datetime,
    max_age_seconds: int,
) -> bool:
    try:
        observed_at = _monitor_observed_at(
            probe.channel.last_checked_at,
            captured_at=now,
        )
    except ValueError:
        return False
    return (
        observed_at is not None
        and (now - observed_at).total_seconds() <= max_age_seconds
    )

BeforeQuarantine = Callable[[dict[str, object]], Awaitable[None]]
AfterQuarantine = Callable[[str, bool, bool], Awaitable[None]]
BeforeRestore = Callable[[str], Awaitable[None]]
AfterRestore = Callable[[str, bool, bool], Awaitable[None]]


class _MaintenanceObserver(MaintenanceMutationObserver):
    def __init__(
        self,
        before_quarantine: BeforeQuarantine,
        after_quarantine: AfterQuarantine,
    ) -> None:
        self._before_quarantine = before_quarantine
        self._after_quarantine = after_quarantine

    async def before_disable(self, adjustment: MaintenanceAdjustment) -> None:
        reason = _REASON_MAP.get(adjustment.reason)
        if reason is None:
            raise ValueError("unsupported quarantine reason")
        await self._before_quarantine(
            {
                "account_id": adjustment.account_id,
                "reason": reason.value,
                "group_ids": list(adjustment.group_ids),
                "threshold_ms": adjustment.threshold_ms,
                "observed_count": adjustment.observed_count,
                "previous_status": adjustment.previous_status,
                "previous_schedulable": adjustment.previous_schedulable,
            }
        )

    async def after_disable(
        self,
        adjustment: MaintenanceAdjustment,
        result: AccountDisableResult,
    ) -> None:
        await self._after_quarantine(
            adjustment.account_id,
            result.success,
            result.state_uncertain,
        )


class LegacySub2APIAdapter:
    """Reuse the plugin's hardened API parsing and account-mutation invariants."""

    def __init__(
        self,
        client: Sub2APIClient,
        *,
        maintenance_policy: MaintenancePolicy | None = None,
        probe_cache_ttl_seconds: int = 120,
        probe_freshness_seconds: int = 180,
    ) -> None:
        self._client = client
        self._maintenance_policy = maintenance_policy or MaintenancePolicy()
        self._probe_cache_ttl_seconds = max(30, int(probe_cache_ttl_seconds))
        self._probe_freshness_seconds = max(30, int(probe_freshness_seconds))
        self._maintenance = MaintenanceServiceFactory.create(client, self._maintenance_policy)
        self._last_probes: list[ChannelProbe] = []
        self._last_probe_captured_at: datetime | None = None

    async def probe(self) -> ProbeResult:
        probes, accounts, groups = await self._client.fetch_probe_with_accounts()
        # The timestamp is part of the shared-evidence contract.  Capture it
        # after all upstream pages have been read so a slow or retried request
        # cannot make fresh data look older than it actually is.
        captured_at = datetime.now(UTC)
        self._last_probes = probes
        self._last_probe_captured_at = captured_at
        snapshot = _SNAPSHOT_ADAPTER.validate_json(ProbeSnapshot.from_probes(probes).to_bytes())
        image_base64: str | None = None
        try:
            image_data_uri = render_status_report_image(
                probes,
                triggered_at=captured_at,
            )
            prefix = "data:image/png;base64,"
            if image_data_uri.startswith(prefix):
                image_base64 = image_data_uri[len(prefix) :]
        except Exception:
            image_base64 = None
        return ProbeResult(
            snapshot=snapshot,
            report=format_status_report(probes, triggered_at=captured_at),
            image_base64=image_base64,
            guardian_snapshot=self._build_guardian_snapshot(
                probes,
                groups,
                captured_at=captured_at,
            ),
            account_observations=tuple(
                AccountObservation(
                    account_id=account.account_id,
                    group_ids=account.group_ids,
                    status=AccountObservationStatus(account.status),
                    schedulable=account.schedulable,
                    expired=account.expired,
                    temporary_unavailable=account.temporary_unavailable,
                    automatic_pause=account.automatic_pause,
                )
                for account in sorted(accounts, key=lambda item: int(item.account_id))
            ),
            captured_at=captured_at,
        )

    async def guardian_snapshot(self) -> dict[str, Any]:
        """Return the richer, still-secret-free snapshot used by Guardian."""
        probes = await self._client.fetch_probe()
        captured_at = datetime.now(UTC)
        self._last_probes = probes
        self._last_probe_captured_at = captured_at
        return self._build_guardian_snapshot(probes, captured_at=captured_at)

    async def _monitored_group_ids(self) -> frozenset[str]:
        probes = self._last_probes or await self._client.fetch_probe()
        self._last_probes = probes
        # Usage-log binding resolves only the base group a shared channel
        # served; vip variants and groups without a bound channel stay
        # unresolved.  The admin group list is the authoritative managed
        # scope.
        bound = frozenset(
            probe.accounts.group_id
            for probe in probes
            if probe.accounts is not None
        )
        return bound | await self._client.fetch_known_group_ids()

    @staticmethod
    def _guardian_account_block_reason(state: AccountDispatchState) -> str | None:
        if not state.success:
            return "account_state_unavailable"
        if state.expired:
            return "expired"
        # An automatic pause is exactly the state Guardian is allowed to
        # probe.  The same account can still expose a future rate-limit or
        # overload deadline; do not turn that server-owned protection into a
        # permanent skip.  Non-active accounts with a stale deadline are also
        # eligible for the recovery path because their status is already an
        # explicit system-abnormal signal.
        if (
            state.temporary_unavailable
            and state.status == "active"
            and not state.automatic_pause
        ):
            return "temporary_unavailable"
        if (
            state.status == "active"
            and state.schedulable is False
            and not state.automatic_pause
        ):
            return "manual_pause"
        return None

    def _monitor_model_for_account(
        self,
        initial_account: GuardianAccountObservation,
    ) -> str:
        """Resolve a model from the latest channel-monitor inventory.

        Account tests are account-scoped while the monitor is channel-scoped.
        Use the monitor model only when the account maps unambiguously to one
        model; falling back to Sub2API's account default is safer than sending
        a model from an unrelated channel for shared accounts.
        """

        group_ids = frozenset(initial_account.group_ids)
        if not group_ids:
            return ""
        models = {
            probe.channel.model.strip()
            for probe in self._last_probes
            if probe.accounts is not None
            and probe.accounts.group_id in group_ids
            and probe.channel.model.strip()
        }
        return next(iter(models)) if len(models) == 1 else ""

    def _monitor_model_for_groups(self, group_ids: Iterable[str]) -> str:
        """Resolve one monitor model for a set of quarantined account groups."""

        target_groups = frozenset(group_ids)
        if not target_groups:
            return ""
        models = {
            probe.channel.model.strip()
            for probe in self._last_probes
            if probe.accounts is not None
            and probe.accounts.group_id in target_groups
            and probe.channel.model.strip()
        }
        return next(iter(models)) if len(models) == 1 else ""

    async def guardian_test_account(
        self,
        account_id: str,
        *,
        initial_account: GuardianAccountObservation,
        model_id: str = "",
        prompt: str = "hi",
        mode: str = "",
    ) -> GuardianAccountTestOutcome:
        if initial_account.account_id != account_id:
            return GuardianAccountTestOutcome(
                account_id=account_id,
                result=AccountTestExecutionResult.INDETERMINATE,
                reason="test_context_invalid",
            )
        initial_is_manual_pause = (
            initial_account.status is GuardianAccountStatus.ACTIVE
            and initial_account.schedulable is False
            and not initial_account.automatic_pause
        )
        if initial_is_manual_pause:
            return GuardianAccountTestOutcome(
                account_id=account_id,
                result=AccountTestExecutionResult.SKIPPED,
                reason="manual_pause",
                observed_status=initial_account.status,
                observed_schedulable=initial_account.schedulable,
                observed_automatic_pause=initial_account.automatic_pause,
            )
        if initial_account.expired:
            return GuardianAccountTestOutcome(
                account_id=account_id,
                result=AccountTestExecutionResult.SKIPPED,
                reason="expired",
                observed_status=initial_account.status,
                observed_schedulable=initial_account.schedulable,
                observed_automatic_pause=initial_account.automatic_pause,
            )
        if initial_account.temporary_unavailable and not (
            initial_account.automatic_pause
            or initial_account.status
            in {
                GuardianAccountStatus.ERROR,
                GuardianAccountStatus.DISABLED,
                GuardianAccountStatus.INACTIVE,
            }
        ):
            return GuardianAccountTestOutcome(
                account_id=account_id,
                result=AccountTestExecutionResult.SKIPPED,
                reason="temporary_unavailable",
                observed_status=initial_account.status,
                observed_schedulable=initial_account.schedulable,
                observed_automatic_pause=initial_account.automatic_pause,
            )
        state = await self._client.fetch_account_dispatch_state(account_id)
        blocked = (
            self._guardian_account_block_reason(state)
            if state.success
            else "account_state_unavailable"
        )
        if (
            blocked == "manual_pause"
            and initial_account.status
            in {
                GuardianAccountStatus.ERROR,
                GuardianAccountStatus.DISABLED,
                GuardianAccountStatus.INACTIVE,
            }
        ):
            blocked = None
        if blocked == "manual_pause" and initial_account.automatic_pause:
            # Some Sub2API versions expose the automatic reason on the list
            # endpoint but omit it from the single-account readback.  Keep the
            # provenance from the canonical snapshot in that case.
            blocked = None
        if (
            blocked == "account_state_unavailable"
            and initial_account.status is not GuardianAccountStatus.ACTIVE
        ):
            blocked = None
        if blocked is not None:
            return GuardianAccountTestOutcome(
                account_id=account_id,
                result=(
                    AccountTestExecutionResult.INDETERMINATE
                    if blocked == "account_state_unavailable"
                    else AccountTestExecutionResult.SKIPPED
                ),
                reason=blocked,
                observed_status=initial_account.status,
                observed_schedulable=initial_account.schedulable,
                observed_automatic_pause=initial_account.automatic_pause
                or state.automatic_pause,
            )
        model_id = model_id.strip()
        if not model_id:
            model_id = self._monitor_model_for_account(initial_account)
        tested = await self._client.test_account_availability(
            account_id,
            model_id=model_id,
            prompt=prompt,
            mode=mode,
        )
        if tested.account_id != account_id:
            return GuardianAccountTestOutcome(
                account_id=account_id,
                result=AccountTestExecutionResult.INDETERMINATE,
                reason="test_identity_mismatch",
            )
        if tested.success:
            result = AccountTestExecutionResult.SUCCESS
        elif tested.definitive_failure:
            result = AccountTestExecutionResult.DEFINITIVE_FAILURE
        else:
            result = AccountTestExecutionResult.INDETERMINATE
        return GuardianAccountTestOutcome(
            account_id=account_id,
            result=result,
            reason=tested.reason,
            first_event_ms=tested.first_event_ms,
            attempted=True,
            observed_status=initial_account.status,
            observed_schedulable=initial_account.schedulable,
            observed_automatic_pause=initial_account.automatic_pause
            or state.automatic_pause,
        )

    async def guardian_enable_account(
        self,
        account_id: str,
        *,
        tested: GuardianAccountTestOutcome,
    ) -> GuardianAccountMutationOutcome:
        if (
            tested.account_id != account_id
            or tested.observed_status is None
            or tested.observed_schedulable is None
        ):
            return GuardianAccountMutationOutcome(
                account_id=account_id,
                result=AccountMutationResult.INDETERMINATE,
                reason="test_context_invalid",
            )
        if (
            tested.observed_status is GuardianAccountStatus.ACTIVE
            and tested.observed_schedulable is False
            and not tested.observed_automatic_pause
        ):
            return GuardianAccountMutationOutcome(
                account_id=account_id,
                result=AccountMutationResult.BLOCKED,
                reason="manual_pause",
            )
        if tested.result is not AccountTestExecutionResult.SUCCESS:
            return GuardianAccountMutationOutcome(
                account_id=account_id,
                result=AccountMutationResult.INDETERMINATE,
                reason="test_context_invalid",
            )
        state = await self._client.fetch_account_dispatch_state(account_id)
        blocked = self._guardian_account_block_reason(state)
        if blocked == "manual_pause" and (
            tested.observed_automatic_pause
            or tested.observed_status
            in {
                GuardianAccountStatus.ERROR,
                GuardianAccountStatus.DISABLED,
                GuardianAccountStatus.INACTIVE,
            }
        ):
            blocked = None
        if blocked == "temporary_unavailable" and (
            tested.observed_automatic_pause
            or tested.observed_status
            in {
                GuardianAccountStatus.ERROR,
                GuardianAccountStatus.DISABLED,
                GuardianAccountStatus.INACTIVE,
            }
        ):
            # A successful account test is the explicit proof that this
            # previously automatic/system-protected account may be returned
            # to the dispatch pool.  ``restore_account`` clears the upstream
            # runtime protection before setting schedulable=true.
            blocked = None
        if blocked is not None:
            return GuardianAccountMutationOutcome(
                account_id=account_id,
                result=(
                    AccountMutationResult.INDETERMINATE
                    if blocked == "account_state_unavailable"
                    else AccountMutationResult.BLOCKED
                ),
                reason=blocked,
            )
        if state.status == "active" and state.schedulable is True:
            return GuardianAccountMutationOutcome(
                account_id=account_id,
                result=AccountMutationResult.NO_CHANGE,
                reason="already_enabled",
            )
        started_at = datetime.now(UTC)
        restored = await self._client.restore_account(
            account_id,
            now=started_at,
            deadline=started_at + timedelta(seconds=30),
        )
        return GuardianAccountMutationOutcome(
            account_id=account_id,
            result=(
                AccountMutationResult.APPLIED
                if restored.success
                else AccountMutationResult.INDETERMINATE
                if restored.state_uncertain
                else AccountMutationResult.BLOCKED
            ),
            reason=restored.reason,
            attempted=True,
        )

    async def guardian_disable_account(
        self,
        account_id: str,
    ) -> GuardianAccountMutationOutcome:
        state = await self._client.fetch_account_dispatch_state(account_id)
        blocked = self._guardian_account_block_reason(state)
        if (
            state.success
            and state.status == "active"
            and state.schedulable is False
            and state.automatic_pause
        ):
            # A failed probe must not convert an upstream automatic pause into
            # a permanent inactive state.  Leave Sub2API's protection intact
            # and let the next hourly pass try again.
            return GuardianAccountMutationOutcome(
                account_id=account_id,
                result=AccountMutationResult.BLOCKED,
                reason="automatic_pause_preserved",
            )
        if blocked is not None:
            return GuardianAccountMutationOutcome(
                account_id=account_id,
                result=(
                    AccountMutationResult.INDETERMINATE
                    if blocked == "account_state_unavailable"
                    else AccountMutationResult.BLOCKED
                ),
                reason=blocked,
            )
        if state.status in {"inactive", "disabled"} and state.schedulable is False:
            return GuardianAccountMutationOutcome(
                account_id=account_id,
                result=AccountMutationResult.NO_CHANGE,
                reason="already_disabled",
            )
        disabled = await self._client.disable_account(account_id)
        return GuardianAccountMutationOutcome(
            account_id=account_id,
            result=(
                AccountMutationResult.APPLIED
                if disabled.success
                else AccountMutationResult.INDETERMINATE
                if disabled.state_uncertain
                else AccountMutationResult.BLOCKED
            ),
            reason=disabled.reason,
            attempted=True,
        )

    async def guardian_list_channels(self) -> list[AdminChannelSummary]:
        return await self._client.list_channels()

    async def guardian_update_channel_model_mapping(
        self,
        channel_id: str,
        model_mapping: dict[str, dict[str, str]],
    ) -> None:
        await self._client.update_channel_model_mapping(channel_id, model_mapping)

    async def guardian_create_channel(
        self,
        *,
        name: str,
        group_ids: list[str],
        model_mapping: dict[str, dict[str, str]],
    ) -> str:
        return await self._client.create_channel(
            name=name,
            group_ids=group_ids,
            model_mapping=model_mapping,
        )

    async def guardian_list_channel_monitors(self) -> list[AdminMonitorSummary]:
        return await self._client.list_channel_monitors()

    async def guardian_list_group_api_keys(
        self, group_id: str
    ) -> list[AdminGroupApiKey]:
        return await self._client.list_group_api_keys(group_id)

    async def guardian_fetch_endpoint_models(
        self, endpoint: str, api_key: str
    ) -> list[str]:
        return await self._client.fetch_endpoint_models(endpoint, api_key)

    async def guardian_rebind_channel(
        self,
        channel_id: str,
        *,
        group_ids: list[str],
        model_mapping: dict[str, dict[str, str]],
    ) -> None:
        await self._client.rebind_channel(
            channel_id,
            group_ids=group_ids,
            model_mapping=model_mapping,
        )

    async def guardian_list_groups(self) -> list[AdminGroupSummary]:
        return await self._client.list_groups()

    @staticmethod
    def _build_guardian_snapshot(
        probes: list[ChannelProbe],
        groups: list[GroupAccountCounts] | None = None,
        *,
        captured_at: datetime | None = None,
    ) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        for probe in probes:
            channel = probe.channel
            accounts = probe.accounts
            observed_at = (
                _monitor_observed_at(channel.last_checked_at, captured_at=captured_at)
                if captured_at is not None
                else None
            )
            entry: dict[str, Any] = {
                "monitor_id": channel.monitor_id,
                "name": channel.name,
                "status": channel.status,
                "group_id": accounts.group_id if accounts is not None else None,
                "group_name": accounts.name if accounts is not None else None,
                "available_count": (
                    accounts.available_count if accounts is not None else None
                ),
                "error_count": accounts.error_count if accounts is not None else None,
                "temporary_unavailable_count": (
                    accounts.temporary_unavailable_count if accounts is not None else None
                ),
                "closed_count": accounts.closed_count if accounts is not None else None,
                "latency_ms": channel.latency_ms,
                "upstream_schedulable": channel.enabled,
            }
            if observed_at is not None:
                entry["observed_at"] = observed_at
            if channel.model:
                entry["probe_model"] = channel.model
            if channel.api_mode:
                entry["probe_api_mode"] = channel.api_mode
            if channel.template_id is not None:
                entry["probe_template_id"] = channel.template_id
            entries.append(entry)
        entries.sort(key=lambda item: (str(item["monitor_id"]), str(item["name"])))
        snapshot = UpstreamProbeSnapshot.model_validate(
            {
                "version": 1,
                "entries": entries,
                "groups": [
                    {
                        "group_id": group.group_id,
                        "name": group.name,
                        "total_count": group.total_count,
                        "available_count": group.available_count,
                        "error_count": group.error_count,
                        "temporary_unavailable_count": group.temporary_unavailable_count,
                        "closed_count": group.closed_count,
                    }
                    for group in (groups or [])
                ],
            }
        )
        return snapshot.model_dump(mode="json")

    async def maintain(
        self,
        probe: ProbeResult,
        *,
        excluded_account_ids: frozenset[str] = frozenset(),
        before_quarantine: BeforeQuarantine | None = None,
        after_quarantine: AfterQuarantine | None = None,
    ) -> list[dict[str, object]]:
        if not (
            self._maintenance_policy.channel_account_sweep_enabled
            or self._maintenance_policy.log_account_guard_enabled
        ):
            return []
        now = datetime.now(UTC)
        cached_at = self._last_probe_captured_at
        cache_matches_probe = (
            probe.captured_at is None
            or cached_at is not None
            and cached_at == probe.captured_at
        )
        cache_is_fresh = (
            cached_at is not None
            and (now - cached_at).total_seconds() <= self._probe_cache_ttl_seconds
        )
        if self._last_probes and cache_matches_probe and cache_is_fresh:
            probes = self._last_probes
        else:
            probes = await self._client.fetch_probe()
            self._last_probes = probes
            now = datetime.now(UTC)
            self._last_probe_captured_at = now
        probes = [
            item
            for item in probes
            if _monitor_probe_is_fresh(
                item,
                now=now,
                max_age_seconds=self._probe_freshness_seconds,
            )
        ]
        observer = (
            _MaintenanceObserver(before_quarantine, after_quarantine)
            if before_quarantine is not None and after_quarantine is not None
            else None
        )
        if (before_quarantine is None) != (after_quarantine is None):
            raise ValueError("both quarantine callbacks are required")
        report = await self._maintenance.run(
            probes,
            now=now,
            excluded_account_ids=excluded_account_ids,
            observer=observer,
        )
        outcomes = [
            MaintenanceOutcome(
                outcome=MaintenanceOutcomeCode.QUARANTINED,
                account_id=item.account_id,
                account_name=item.account_name,
                reason=_REASON_MAP[item.reason],
                group_ids=item.group_ids,
                threshold_ms=item.threshold_ms,
                observed_count=item.observed_count,
            )
            for item in report.adjustments
            if item.reason in _REASON_MAP
        ]
        for notice in report.notices:
            outcomes.append(
                MaintenanceOutcome(
                    outcome=MaintenanceOutcomeCode(notice.code),
                    account_id=notice.account_id or None,
                    account_name=notice.account_name or None,
                    reason=_REASON_MAP.get(notice.reason),
                    group_id=notice.group_id or None,
                    group_name=notice.group_name or None,
                    protected_group_ids=notice.group_ids,
                )
            )
        return [
            item.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
            for item in outcomes
        ]

    async def reconcile_quarantine_intent(
        self,
        intent: AccountQuarantineIntent,
    ) -> str:
        if not set(intent.group_ids) <= await self._monitored_group_ids():
            return "KEEP"
        state = await self._client.fetch_account_dispatch_state(intent.account_id)
        if not state.success:
            return "KEEP"
        if (
            state.status == intent.previous_status
            and state.schedulable is intent.previous_schedulable
        ):
            return "CLEAR"
        if state.status in {"inactive", "disabled"}:
            accounts = await self._client.fetch_account_group_states(now=datetime.now(UTC))
            current = next(
                (item for item in accounts if item.account_id == intent.account_id),
                None,
            )
            known_group_ids = await self._client.fetch_known_group_ids()
            if (
                current is None
                or current.group_ids != intent.group_ids
                or not set(current.group_ids) <= known_group_ids
            ):
                return "KEEP"
            disabled = await self._client.disable_account(intent.account_id)
            return "PROMOTE" if disabled.success else "KEEP"
        if state.status == "active" and state.schedulable is False:
            return "KEEP"
        return "CLEAR"

    async def probe_quarantined(
        self,
        marker: AccountQuarantineRecord,
        *,
        before_restore: BeforeRestore | None = None,
        after_restore: AfterRestore | None = None,
    ) -> QuarantineProbeAttempt:
        if (before_restore is None) != (after_restore is None):
            raise ValueError("both quarantine restore callbacks are required")
        if not set(marker.group_ids) <= await self._monitored_group_ids():
            return QuarantineProbeAttempt(
                account_id=marker.account_id,
                result=QuarantineProbeResult.INVALID,
            )
        state = await self._client.fetch_account_dispatch_state(marker.account_id)
        if not state.success:
            return QuarantineProbeAttempt(
                account_id=marker.account_id,
                result=QuarantineProbeResult.INVALID,
            )
        if state.status not in {"inactive", "disabled"} or state.schedulable is not False:
            return QuarantineProbeAttempt(
                account_id=marker.account_id,
                result=QuarantineProbeResult.INVALID,
            )
        tested = await self._client.test_account_availability(
            marker.account_id,
            model_id=self._monitor_model_for_groups(marker.group_ids),
        )
        if not tested.success:
            return QuarantineProbeAttempt(
                account_id=marker.account_id,
                result=(
                    QuarantineProbeResult.FAILED
                    if tested.definitive_failure
                    else QuarantineProbeResult.INVALID
                ),
                latency_ms=tested.first_event_ms,
            )
        if marker.reason is AccountQuarantineReason.SLOW_FIRST_TOKEN:
            if tested.first_event_ms is None:
                return QuarantineProbeAttempt(
                    account_id=marker.account_id,
                    result=QuarantineProbeResult.INVALID,
                )
            if tested.first_event_ms > marker.threshold_ms:
                return QuarantineProbeAttempt(
                    account_id=marker.account_id,
                    result=QuarantineProbeResult.SLOW,
                    latency_ms=tested.first_event_ms,
                )
            if marker.recovery_success_streak == 0:
                return QuarantineProbeAttempt(
                    account_id=marker.account_id,
                    result=QuarantineProbeResult.PASSING,
                    latency_ms=tested.first_event_ms,
                )
        restore_started = datetime.now(UTC)
        if before_restore is not None:
            await before_restore(marker.account_id)
        restored = await self._client.restore_account(
            marker.account_id,
            now=restore_started,
            deadline=restore_started + timedelta(seconds=30),
        )
        if after_restore is not None:
            await after_restore(
                marker.account_id,
                restored.success,
                restored.state_uncertain,
            )
        return QuarantineProbeAttempt(
            account_id=marker.account_id,
            result=(
                QuarantineProbeResult.RECOVERED
                if restored.success
                else QuarantineProbeResult.FAILED
            ),
            latency_ms=tested.first_event_ms,
            recovered=restored.success,
        )

    async def reconcile_quarantine_restore(
        self,
        marker: AccountQuarantineRecord,
    ) -> str:
        if not set(marker.group_ids) <= await self._monitored_group_ids():
            return "KEEP"
        account_id = marker.account_id
        state = await self._client.fetch_account_dispatch_state(account_id)
        if not state.success:
            return "KEEP"
        if state.status == "active" and state.schedulable is True:
            return "RECOVERED"
        if state.status in {"inactive", "disabled"} and state.schedulable is False:
            return "CANCEL"
        tested = await self._client.test_account_availability(
            account_id,
            model_id=self._monitor_model_for_groups(marker.group_ids),
        )
        if not tested.success:
            return "KEEP"
        if marker.reason is AccountQuarantineReason.SLOW_FIRST_TOKEN and (
            tested.first_event_ms is None
            or tested.first_event_ms > marker.threshold_ms
        ):
            return "KEEP"
        restore_started = datetime.now(UTC)
        restored = await self._client.restore_account(
            account_id,
            now=restore_started,
            deadline=restore_started + timedelta(seconds=30),
        )
        return "RECOVERED" if restored.success else "KEEP"

    async def find_active_account(self, email: str) -> ActorAccount | None:
        account = await self._client.find_account_by_email(email)
        if account is None:
            return None
        return ActorAccount(
            user_id=account.user_id,
            email_masked=mask_email(account.email),
            status=account.status,
        )

    async def account_report(self, user_id: str) -> str:
        account, today_usage, month_usage = await asyncio.gather(
            self._client.fetch_account(user_id),
            self._client.fetch_account_usage(user_id, "today"),
            self._client.fetch_account_usage(user_id, "month"),
        )
        if account.user_id != user_id:
            raise ValueError("Sub2API returned a different account")
        status_label = {
            "active": "正常",
            "disabled": "停用",
            "suspended": "冻结",
        }.get(account.status, "未知")
        return "\n".join(
            [
                "智算账户",
                f"邮箱：{mask_email(account.email)}",
                f"状态：{status_label}",
                f"余额：${account.balance:.2f}",
                f"今日使用金额：${today_usage.total_actual_cost:.4f}",
                f"今日请求数量：{today_usage.total_requests:,}",
                f"今日 Token 数量：{today_usage.total_tokens:,}",
                f"本月使用金额：${month_usage.total_actual_cost:.4f}",
            ]
        )


def build_sub2api_adapter(settings: Settings) -> LegacySub2APIAdapter:
    """Build the adapter from validated settings without leaking the admin key."""

    client = Sub2APIClient(
        settings.sub2api_admin_key.get_secret_value(),
        base_url=settings.sub2api_base_url,
        timeout_seconds=settings.sub2api_timeout_seconds,
    )
    policy = MaintenancePolicy(
        channel_account_sweep_enabled=settings.channel_account_sweep_enabled,
        channel_account_sweep_max_accounts=settings.channel_account_sweep_max_accounts,
        log_account_guard_enabled=settings.log_account_guard_enabled,
        log_error_threshold=settings.log_error_threshold,
        slow_first_token_event_threshold=settings.slow_first_token_event_threshold,
        slow_first_token_ms=settings.slow_first_token_ms,
        slow_first_token_window_minutes=settings.slow_first_token_window_minutes,
    )
    return LegacySub2APIAdapter(
        client,
        maintenance_policy=policy,
        probe_cache_ttl_seconds=max(30, settings.probe_interval_seconds * 2),
        probe_freshness_seconds=max(180, settings.probe_interval_seconds * 3),
    )
