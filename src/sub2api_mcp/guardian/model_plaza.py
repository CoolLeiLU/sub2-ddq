"""Scheduled model-plaza refresh.

The Sub2API model plaza renders each group's model list from the bound
channel's ``model_mapping``.  On the configured daily slots Guardian probes
the upstream model catalog of every usable account in each monitored group
(via ``GET /admin/accounts/{id}/models`` — a cheap catalog call, not a
token-consuming chat test) and rewrites that mapping so the plaza only
shows models that can actually be served.

Write guards:

- only ``active`` channels bound to at least one monitored group;
- only channels whose ``model_mapping`` has exactly one platform key, so
  probed models can be attributed to a platform unambiguously;
- never wipe a mapping when every account probe for the group failed;
- only usable accounts (``active`` + ``schedulable``) contribute models —
  manually paused or disabled accounts are never probed for this feature.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from maintenance_gateway import AdminChannelSummary, AdminGroupSummary

from .contracts import GuardianAccountObservation, GuardianAccountStatus
from .repository import GuardianRepository

PLAZA_TIMEZONE = ZoneInfo("Asia/Shanghai")


class ModelPlazaOperations(Protocol):
    async def guardian_list_channels(self) -> list[AdminChannelSummary]: ...

    async def guardian_list_groups(self) -> list[AdminGroupSummary]: ...

    async def guardian_fetch_account_models(self, account_id: str) -> list[str]: ...

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


def usable_account_ids(
    observations: list[GuardianAccountObservation],
    monitored_group_ids: frozenset[str],
) -> dict[str, set[str]]:
    """Group -> account ids that can serve traffic right now."""

    usable: dict[str, set[str]] = {group_id: set() for group_id in monitored_group_ids}
    for observation in observations:
        if (
            observation.status is not GuardianAccountStatus.ACTIVE
            or not observation.schedulable
        ):
            continue
        for group_id in observation.group_ids:
            if group_id in usable:
                usable[group_id].add(observation.account_id)
    return usable


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
                group_id
                for group_id in channel.group_ids
                if group_id in monitored_group_ids
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
                f"{result['accounts_probed']} account(s) probed"
            ),
            details=result,
        )
        return result

    async def refresh(
        self,
        *,
        snapshot_id: str,
        monitored_group_ids: frozenset[str],
    ) -> dict[str, Any]:
        observations = await self._repository.list_account_observations(snapshot_id)
        usable = usable_account_ids(observations, monitored_group_ids)
        account_models: dict[str, set[str]] = {}
        failed_accounts: list[str] = []
        for account_id in sorted(
            {account for ids in usable.values() for account in ids},
            key=int,
        ):
            try:
                account_models[account_id] = set(
                    await self._operations.guardian_fetch_account_models(account_id)
                )
            except Exception:
                failed_accounts.append(account_id)
        group_models: dict[str, set[str]] = {}
        for group_id, account_ids in usable.items():
            models: set[str] = set()
            for account_id in account_ids:
                models |= account_models.get(account_id, set())
            group_models[group_id] = models
        channels = await self._operations.guardian_list_channels()
        bound_group_ids = {
            group_id for channel in channels for group_id in channel.group_ids
        }
        unbound = sorted(
            monitored_group_ids - bound_group_ids,
            key=int,
        )
        created: list[dict[str, Any]] = []
        if unbound:
            groups = {
                group.group_id: group
                for group in await self._operations.guardian_list_groups()
            }
            for group_id in unbound:
                entry: dict[str, Any] = {
                    "group_id": group_id,
                    "updated": False,
                    "reason": "",
                    "models": [],
                }
                meta = groups.get(group_id)
                probed_models = sorted(group_models.get(group_id, set()))
                if meta is None or meta.status != "active":
                    entry["reason"] = "group_inactive"
                elif not probed_models:
                    entry["reason"] = "empty_probe"
                else:
                    desired = {model: model for model in probed_models}
                    orphan = next(
                        (
                            channel
                            for channel in channels
                            if channel.name == meta.name
                            and not any(
                                bound in groups for bound in channel.group_ids
                            )
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
                            entry["channel_id"] = (
                                await self._operations.guardian_create_channel(
                                    name=meta.name,
                                    group_ids=[group_id],
                                    model_mapping={meta.platform: desired},
                                )
                            )
                    except Exception:
                        entry["reason"] = "create_failed"
                    else:
                        entry.update(
                            {
                                "updated": True,
                                "reason": (
                                    "rebound" if orphan is not None else "created"
                                ),
                                "name": meta.name,
                                "platform": meta.platform,
                                "models": probed_models,
                                "added": probed_models,
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
                {key: value for key, value in entry.items() if key != "desired"}
                for entry in plan
            ]
            + created,
            "groups": {
                group_id: sorted(models)
                for group_id, models in sorted(
                    group_models.items(), key=lambda item: int(item[0])
                )
            },
            "accounts_probed": len(account_models),
            "accounts_failed": failed_accounts,
        }
