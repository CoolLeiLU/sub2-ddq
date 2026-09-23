"""Scheduled model-plaza refresh.

The Sub2API model plaza renders each group's model list from the bound
channel's ``model_mapping``.  On the configured daily slots Guardian asks
Sub2API itself which models each monitored group can serve: every enabled
channel monitor carries the API key it probes with, the key is resolved to
its plaintext via ``GET /admin/groups/{id}/api-keys`` (masked prefix
match), and ``GET {endpoint}/v1/models`` with that key returns the
group's live model catalog — already filtered by the key's own model
permissions.  The result rewrites the channel mapping so the plaza lists
exactly what the platform offers.

Write guards:

- only ``active`` channels bound to at least one monitored group;
- only channels whose ``model_mapping`` has exactly one platform key, so
  probed models can be attributed to a platform unambiguously;
- never wipe a mapping when no monitor key could be resolved or every
  model fetch for the group failed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from maintenance_gateway import (
    AdminChannelSummary,
    AdminGroupApiKey,
    AdminGroupSummary,
    AdminMonitorSummary,
)

from .repository import GuardianRepository

PLAZA_TIMEZONE = ZoneInfo("Asia/Shanghai")


class ModelPlazaOperations(Protocol):
    async def guardian_list_channels(self) -> list[AdminChannelSummary]: ...

    async def guardian_list_groups(self) -> list[AdminGroupSummary]: ...

    async def guardian_list_channel_monitors(self) -> list[AdminMonitorSummary]: ...

    async def guardian_list_group_api_keys(self, group_id: str) -> list[AdminGroupApiKey]: ...

    async def guardian_fetch_endpoint_models(self, endpoint: str, api_key: str) -> list[str]: ...

    async def guardian_update_channel_model_mapping(
        self,
        channel_id: str,
        model_mapping: dict[str, dict[str, str]],
    ) -> None: ...

    async def guardian_create_channel(
        self,
        *,
        name: str,
        group_ids: list[str],
        model_mapping: dict[str, dict[str, str]],
    ) -> str: ...

    async def guardian_rebind_channel(
        self,
        channel_id: str,
        *,
        group_ids: list[str],
        model_mapping: dict[str, dict[str, str]],
    ) -> None: ...


def latest_elapsed_slot(
    now: datetime,
    refresh_times: tuple[str, ...],
) -> datetime | None:
    """Most recent configured refresh time at or before ``now``."""

    local = now.astimezone(PLAZA_TIMEZONE)
    candidates: list[datetime] = []
    for item in refresh_times:
        hour, minute = (int(part) for part in item.split(":"))
        for day_offset in (0, 1):
            slot = (local - timedelta(days=day_offset)).replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )
            if slot <= local:
                candidates.append(slot)
    return max(candidates) if candidates else None


def channel_model_plan(
    channels: list[AdminChannelSummary],
    group_models: dict[str, set[str]],
    monitored_group_ids: frozenset[str],
) -> list[dict[str, Any]]:
    """Decide each channel's desired model_mapping without performing I/O."""

    plan: list[dict[str, Any]] = []
    for channel in channels:
        entry: dict[str, Any] = {
            "channel_id": channel.channel_id,
            "name": channel.name,
            "updated": False,
            "reason": "",
            "models": [],
        }
        if channel.status != "active":
            entry["reason"] = "channel_inactive"
        else:
            target_groups = [
                group_id for group_id in channel.group_ids if group_id in monitored_group_ids
            ]
            if not target_groups:
                entry["reason"] = "unmonitored_scope"
            elif len(channel.model_mapping) != 1:
                entry["reason"] = "ambiguous_platform"
            else:
                probed: set[str] = set()
                for group_id in target_groups:
                    probed |= group_models.get(group_id, set())
                models = sorted(probed)
                if not models:
                    entry["reason"] = "empty_probe"
                else:
                    platform = next(iter(channel.model_mapping))
                    existing: dict[str, str] = channel.model_mapping[platform]
                    desired = {model: existing.get(model, model) for model in models}
                    if desired == existing:
                        entry["reason"] = "unchanged"
                    else:
                        entry.update(
                            {
                                "updated": True,
                                "reason": "updated",
                                "platform": platform,
                                "desired": desired,
                                "models": models,
                                "added": sorted(set(desired) - set(existing)),
                                "removed": sorted(set(existing) - set(desired)),
                            }
                        )
        plan.append(entry)
    return plan


class ModelPlazaRefresher:
    def __init__(
        self,
        repository: GuardianRepository,
        operations: ModelPlazaOperations,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._operations = operations
        self._clock = clock or (lambda: datetime.now(UTC))

    async def refresh_if_due(
        self,
        *,
        snapshot_id: str,
        monitored_group_ids: frozenset[str],
        refresh_times: tuple[str, ...],
    ) -> dict[str, Any] | None:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("model plaza clock must be timezone-aware")
        slot = latest_elapsed_slot(now, refresh_times)
        if slot is None:
            return None
        last = await self._repository.model_plaza_last_refresh()
        if last is not None and last >= slot.astimezone(UTC):
            return None
        result = await self.refresh(
            snapshot_id=snapshot_id,
            monitored_group_ids=monitored_group_ids,
        )
        await self._repository.mark_model_plaza_refreshed(now)
        updated = [item for item in result["channels"] if item["updated"]]
        await self._repository.add_event(
            event_type="MODEL_PLAZA_REFRESHED",
            severity="INFO",
            message=(
                f"Model plaza refreshed: {len(updated)} channel(s) updated, "
                f"{result['groups_probed']} group(s) probed"
            ),
            details=result,
        )
        return result

    async def _group_models(
        self,
        group_id: str,
        monitor_ids: list[str],
        monitors: dict[str, AdminMonitorSummary],
        api_keys: list[AdminGroupApiKey] | None,
    ) -> tuple[set[str], str]:
        """Union ``/v1/models`` for every monitor bound to the group."""

        models: set[str] = set()
        failure = "no_monitor" if not monitor_ids else ""
        for monitor_id in monitor_ids:
            monitor = monitors.get(monitor_id)
            if monitor is None or not monitor.endpoint:
                failure = failure or "no_monitor"
                continue
            prefix = monitor.api_key_masked.split("*", 1)[0].strip()
            if not prefix:
                failure = failure or "key_not_found"
                continue
            if api_keys is None:
                failure = failure or "keys_fetch_failed"
                continue
            matched = next(
                (
                    key.key
                    for key in api_keys
                    if key.status == "active" and key.key.startswith(prefix)
                ),
                None,
            )
            if matched is None:
                failure = failure or "key_not_found"
                continue
            try:
                models |= set(
                    await self._operations.guardian_fetch_endpoint_models(monitor.endpoint, matched)
                )
            except Exception:
                failure = failure or "models_fetch_failed"
        return models, "" if models else failure

    async def refresh(
        self,
        *,
        snapshot_id: str,
        monitored_group_ids: frozenset[str],
    ) -> dict[str, Any]:
        templates = await self._repository.probe_templates_for_snapshot(snapshot_id)
        monitor_ids_by_group: dict[str, set[str]] = {}
        for template in templates:
            if template.group_id is not None and template.group_id in monitored_group_ids:
                monitor_ids_by_group.setdefault(template.group_id, set()).add(template.channel_id)
        monitors = {
            monitor.monitor_id: monitor
            for monitor in await self._operations.guardian_list_channel_monitors()
            if monitor.enabled
        }
        groups = {group.group_id: group for group in await self._operations.guardian_list_groups()}
        group_models: dict[str, set[str]] = {}
        group_failures: dict[str, str] = {}
        for group_id in sorted(monitored_group_ids, key=int):
            try:
                api_keys: (
                    list[AdminGroupApiKey] | None
                ) = await self._operations.guardian_list_group_api_keys(group_id)
            except Exception:
                api_keys = None
            models, failure = await self._group_models(
                group_id,
                sorted(monitor_ids_by_group.get(group_id, set()), key=int),
                monitors,
                api_keys,
            )
            group_models[group_id] = models
            if failure:
                group_failures[group_id] = failure
        channels = await self._operations.guardian_list_channels()
        bound_group_ids = {group_id for channel in channels for group_id in channel.group_ids}
        unbound = sorted(
            monitored_group_ids - bound_group_ids,
            key=int,
        )
        created: list[dict[str, Any]] = []
        for group_id in unbound:
            entry: dict[str, Any] = {
                "group_id": group_id,
                "updated": False,
                "reason": "",
                "models": [],
            }
            meta = groups.get(group_id)
            desired_models = sorted(group_models.get(group_id, set()))
            if meta is None or meta.status != "active":
                entry["reason"] = "group_inactive"
            elif not desired_models:
                entry["reason"] = group_failures.get(group_id, "empty_probe")
            else:
                desired = {model: model for model in desired_models}
                orphan = next(
                    (
                        channel
                        for channel in channels
                        if channel.name == meta.name
                        and not any(bound in groups for bound in channel.group_ids)
                    ),
                    None,
                )
                try:
                    if orphan is not None:
                        await self._operations.guardian_rebind_channel(
                            orphan.channel_id,
                            group_ids=[group_id],
                            model_mapping={meta.platform: desired},
                        )
                        entry["channel_id"] = orphan.channel_id
                    else:
                        entry["channel_id"] = await self._operations.guardian_create_channel(
                            name=meta.name,
                            group_ids=[group_id],
                            model_mapping={meta.platform: desired},
                        )
                except Exception:
                    entry["reason"] = "create_failed"
                else:
                    entry.update(
                        {
                            "updated": True,
                            "reason": ("rebound" if orphan is not None else "created"),
                            "name": meta.name,
                            "platform": meta.platform,
                            "models": desired_models,
                            "added": desired_models,
                            "removed": [],
                        }
                    )
            created.append(entry)
        plan = channel_model_plan(channels, group_models, monitored_group_ids)
        for entry in plan:
            if not entry["updated"]:
                continue
            await self._operations.guardian_update_channel_model_mapping(
                entry["channel_id"],
                {entry["platform"]: entry["desired"]},
            )
        return {
            "channels": [
                {key: value for key, value in entry.items() if key != "desired"} for entry in plan
            ]
            + created,
            "groups": {
                group_id: sorted(models)
                for group_id, models in sorted(group_models.items(), key=lambda item: int(item[0]))
            },
            "group_failures": group_failures,
            "groups_probed": len([group_id for group_id, models in group_models.items() if models]),
        }
