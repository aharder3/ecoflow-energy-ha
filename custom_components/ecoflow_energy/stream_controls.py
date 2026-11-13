"""Native Stream controls (BK-series): operating mode and plans.

Created once per config entry, on the first Stream device with an app-channel
connection. Everything shown here is read back from the device
(``ecoflow/stream_status.py``), and nothing is assumed from what was sent:

- Operating mode (select): self-powered, custom, AI. The command is
  ``106 { <mode>: 1 }`` (see ``ecoflow/stream_mode.py``) and the device reports
  the new mode in field 393 of its status frame. The setting applies to both
  devices of a pair.
- For each charge plan the device reports (field 584): a switch for its
  on/off state, selects for its start, stop, source and repeat (daily, weekly,
  once), and one switch per weekday.
- For each discharge plan: the same, without the source. The power of the plan
  is shown as an attribute and sent back unchanged.

Entities appear when a plan appears in the report and report unavailable when
it leaves it.

The device numbers its plans across charge and discharge plans, and the vendor
app does not show those numbers. The entities are therefore named by position:
the first reported charge plan is "Plan 1", the next "Plan 2"; discharge plans
are counted the same way as "Discharge plan 1" and so on. Unique IDs keep the
device number, so a name can move when an earlier plan is deleted but no
entity is replaced.

Changing a plan sends the plan again with the reported values, changing only
what the user changed, repeat included. Switching a plan on first switches to
custom mode, because plans only run there. A plan is sent with flag 4 set when
it is on and without it when it is off, which is what the vendor app does.
Plans are only changed, never created or deleted.

Repeat: daily and weekly (with days) can be set. A plan that runs once keeps the
values the device reported; setting "once" from here is refused because the
date the app sends with it is not decoded.

The entities follow the report, so a change shows up after the device has
reported it, a few seconds after the command.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from functools import partial
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_TYPE_STREAM
from .ecoflow.stream_discharge import build_discharge_request_frame
from .ecoflow.stream_mode import build_mode_frame
from .ecoflow.stream_schedule_request import build_schedule_request_frame
from .ecoflow.stream_status import DAY_NAMES, days_to_mask
from .schedule_service import _next_sequence

_LOGGER = logging.getLogger(__name__)

PLAN_SOC_PCT = 95
PLAN_POWER_W = 1050
MODE_SWITCH_PAUSE_S = 2.0

KIND_CHARGE = "charge"
KIND_DISCHARGE = "discharge"
_PLAN_NAMES = {KIND_CHARGE: "Plan", KIND_DISCHARGE: "Discharge plan"}
_UNIQUE_PREFIX = {KIND_CHARGE: "plan", KIND_DISCHARGE: "discharge"}

MODE_LABELS = {
    "self_powered": "Self-powered",
    "custom": "Custom",
    "ai": "AI",
}
SOURCE_LABELS = {
    "solar": "Solar only",
    "grid_and_solar": "Grid and solar",
}
REPEAT_LABELS = {
    "daily": "Daily",
    "weekly": "Weekly",
    "once": "Once",
}
DAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_TIMES = [f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in (0, 30)]
START_OPTIONS = _TIMES
END_OPTIONS = [*_TIMES, "24:00"]

_HUBS: dict[str, StreamControls] = {}


def _key_for(labels: dict[str, str], label: str) -> str:
    return next(key for key, value in labels.items() if value == label)


def _repeat_fields(
    current: dict[str, Any], repeat: str | None, days: list[str] | None
) -> tuple[int, int]:
    """Return field 8 and field 9 for a plan sent again.

    Without a repeat or days change the reported values go back unchanged, so a
    change of start, stop or source never touches the repeat.
    """
    if days is not None:
        chosen = set(days)
        if not chosen:
            raise ServiceValidationError(
                "A plan needs at least one day; switch the plan off instead"
            )
        if len(chosen) == len(DAY_NAMES):
            return 1, 0
        return 2, days_to_mask(chosen)
    if repeat == "daily":
        return 1, 0
    if repeat == "weekly":
        if current.get("repeat") == "weekly":
            return 2, days_to_mask(current.get("days") or DAY_NAMES)
        return 2, days_to_mask(DAY_NAMES)
    if repeat == "once":
        raise ServiceValidationError(
            "A plan that runs once can only be set in the vendor app"
        )
    return current["repeat_kind"], current["repeat_value"]


class StreamControls:
    """What the entities share: the device, its serials and its reported state."""

    def __init__(
        self, hass: HomeAssistant, coordinator: Any, serials: list[str]
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.serial: str = coordinator.device_sn
        self.serials = serials
        self.created: dict[str, set[int]] = {
            "select": set(),
            "switch": set(),
            "discharge_select": set(),
            "discharge": set(),
        }

    @property
    def mode(self) -> str | None:
        """Return the reported operating mode."""
        value = (self.coordinator.data or {}).get("operating_mode")
        return value if isinstance(value, str) else None

    def plans_of_kind(self, kind: str) -> dict[int, dict[str, Any]]:
        """Return the reported plans of one kind by number."""
        reported = (self.coordinator.data or {}).get("stream_plans")
        if not isinstance(reported, list):
            return {}
        return {
            plan["id"]: plan
            for plan in reported
            if isinstance(plan, dict)
            and plan.get("kind") == kind
            and isinstance(plan.get("id"), int)
        }

    @property
    def plans(self) -> dict[int, dict[str, Any]]:
        """Return the reported charge plans by number."""
        return self.plans_of_kind(KIND_CHARGE)

    @property
    def discharge_plans(self) -> dict[int, dict[str, Any]]:
        """Return the reported discharge plans by number."""
        return self.plans_of_kind(KIND_DISCHARGE)

    def rank(self, kind: str, plan_id: int) -> int | None:
        """Return the position of a reported plan of its kind, counted from 1."""
        numbers = sorted(self.plans_of_kind(kind))
        return numbers.index(plan_id) + 1 if plan_id in numbers else None

    async def _send(self, frame: bytes) -> None:
        client = getattr(self.coordinator, "mqtt_client", None)
        if client is None or not client.is_connected():
            raise HomeAssistantError(
                f"Device {self.serial[:4]} is not connected over the app channel"
            )
        ok = await self.hass.async_add_executor_job(
            partial(client.send_proto_set, frame, wait=True)
        )
        if not ok:
            raise HomeAssistantError("The broker did not acknowledge the frame")

    async def async_set_mode(self, mode: str) -> None:
        """Send the mode frame; the select follows the device's report."""
        frame = build_mode_frame(
            mode,
            device_serial=self.serial,
            sequence=_next_sequence(),
            timestamp=int(time.time()),
        )
        await self._send(frame)
        _LOGGER.info("Stream mode %s sent (%s)", mode, self.serial[:4])

    async def async_change_plan(
        self,
        plan_id: int,
        *,
        plan_kind: str = KIND_CHARGE,
        enabled: bool | None = None,
        start: str | None = None,
        end: str | None = None,
        source: str | None = None,
        repeat: str | None = None,
        days: list[str] | None = None,
    ) -> None:
        """Send a reported plan again with the given values changed."""
        current = self.plans_of_kind(plan_kind).get(plan_id)
        if current is None:
            raise ServiceValidationError(f"Plan {plan_id} is not reported by the device")
        target_enabled = current["enabled"] if enabled is None else enabled
        repeat_kind, field9 = _repeat_fields(current, repeat, days)
        if plan_kind == KIND_DISCHARGE and not current.get("discharge_power"):
            raise ServiceValidationError(
                "The device has not reported the power of this plan"
            )
        if enabled and self.mode != "custom":
            await self.async_set_mode("custom")
            await asyncio.sleep(MODE_SWITCH_PAUSE_S)
        try:
            if plan_kind == KIND_DISCHARGE:
                frame = build_discharge_request_frame(
                    header_serial=self.serial,
                    plan_id=plan_id,
                    start=start or current["start"],
                    end=end or current["end"],
                    power_w=current["discharge_power"],
                    enabled=bool(target_enabled),
                    running=bool(current["running"]),
                    kind=repeat_kind,
                    field9=field9,
                    sequence=_next_sequence(),
                    timestamp=int(time.time()),
                )
            else:
                frame = build_schedule_request_frame(
                    header_serial=self.serial,
                    serials=self.serials,
                    plan_id=plan_id,
                    start=start or current["start"],
                    end=end or current["end"],
                    source=source or current["source"],
                    soc_pct=current.get("soc") or PLAN_SOC_PCT,
                    power_w=current.get("power") or PLAN_POWER_W,
                    sequence=_next_sequence(),
                    timestamp=int(time.time()),
                    operation="change",
                    flag4=1 if target_enabled else None,
                    kind=repeat_kind,
                    field9=field9,
                )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        await self._send(frame)
        _LOGGER.info(
            "Stream %s plan %s sent (%s)",
            plan_kind,
            plan_id,
            "on" if target_enabled else "off",
        )


class _StreamEntity(CoordinatorEntity):
    """Common parts of the select and switch entities."""

    _attr_has_entity_name = True

    def __init__(self, controls: StreamControls, key: str, name: str, icon: str):
        super().__init__(controls.coordinator)
        self._controls = controls
        self._attr_unique_id = f"{controls.serial}_stream_{key}"
        self._attr_name = name
        self._attr_icon = icon

    @property
    def available(self) -> bool:
        return self.coordinator.device_available and super().available

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.device_info


class StreamModeSelect(_StreamEntity, SelectEntity):
    """Operating mode of the Stream (both devices of a pair)."""

    def __init__(self, controls: StreamControls) -> None:
        super().__init__(controls, "mode", "Operating mode", "mdi:tune")
        self._attr_options = list(MODE_LABELS.values())

    @property
    def current_option(self) -> str | None:
        return MODE_LABELS.get(self._controls.mode or "")

    async def async_select_option(self, option: str) -> None:
        await self._controls.async_set_mode(_key_for(MODE_LABELS, option))


class _StreamPlanEntity(_StreamEntity):
    def __init__(
        self,
        controls: StreamControls,
        plan_id: int,
        part: str,
        label: str,
        icon: str,
        plan_kind: str = KIND_CHARGE,
    ) -> None:
        super().__init__(
            controls, f"{_UNIQUE_PREFIX[plan_kind]}{plan_id}_{part}", label, icon
        )
        self._plan_id = plan_id
        self._plan_kind = plan_kind
        self._label = label
        self._last_rank = controls.rank(plan_kind, plan_id) or plan_id

    @property
    def name(self) -> str:
        """Name by position among the reported plans of its kind, not by device number."""
        rank = self._controls.rank(self._plan_kind, self._plan_id)
        if rank is not None:
            self._last_rank = rank
        base = f"{_PLAN_NAMES[self._plan_kind]} {self._last_rank}"
        return f"{base} {self._label}" if self._label else base

    @property
    def _plan(self) -> dict[str, Any] | None:
        return self._controls.plans_of_kind(self._plan_kind).get(self._plan_id)

    @property
    def available(self) -> bool:
        return super().available and self._plan is not None


class StreamPlanSelect(_StreamPlanEntity, SelectEntity):
    """Start, stop, source or repeat of one reported plan."""

    def __init__(
        self,
        controls: StreamControls,
        plan_id: int,
        part: str,
        plan_kind: str = KIND_CHARGE,
    ) -> None:
        options = {
            "start": START_OPTIONS,
            "end": END_OPTIONS,
            "source": list(SOURCE_LABELS.values()),
            "repeat": list(REPEAT_LABELS.values()),
        }[part]
        icon = {
            "start": "mdi:clock-start",
            "end": "mdi:clock-end",
            "source": "mdi:transmission-tower-import",
            "repeat": "mdi:calendar-sync",
        }[part]
        # Entities are listed alphabetically by name, so "stop" keeps the end
        # select behind "start".
        label = {
            "start": "start",
            "end": "stop",
            "source": "source",
            "repeat": "repeat",
        }[part]
        super().__init__(controls, plan_id, part, label, icon, plan_kind)
        self._part = part
        self._attr_options = list(options)

    @property
    def current_option(self) -> str | None:
        plan = self._plan
        if plan is None:
            return None
        value = plan.get("end" if self._part == "end" else self._part)
        if self._part == "source":
            value = SOURCE_LABELS.get(value)
        elif self._part == "repeat":
            value = REPEAT_LABELS.get(value)
        return value if value in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        kind = self._plan_kind
        if self._part == "source":
            await self._controls.async_change_plan(
                self._plan_id, plan_kind=kind, source=_key_for(SOURCE_LABELS, option)
            )
        elif self._part == "repeat":
            await self._controls.async_change_plan(
                self._plan_id, plan_kind=kind, repeat=_key_for(REPEAT_LABELS, option)
            )
        elif self._part == "start":
            await self._controls.async_change_plan(
                self._plan_id, plan_kind=kind, start=option
            )
        else:
            await self._controls.async_change_plan(
                self._plan_id, plan_kind=kind, end=option
            )


class StreamPlanSwitch(_StreamPlanEntity, SwitchEntity):
    """On or off state of one reported plan."""

    def __init__(
        self, controls: StreamControls, plan_id: int, plan_kind: str = KIND_CHARGE
    ) -> None:
        super().__init__(
            controls, plan_id, "enabled", "", "mdi:calendar-clock", plan_kind
        )

    @property
    def is_on(self) -> bool | None:
        plan = self._plan
        return None if plan is None else bool(plan["enabled"])

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        plan = self._plan
        if plan is None:
            return None
        attributes: dict[str, Any] = {"running": bool(plan["running"])}
        if self._plan_kind == KIND_DISCHARGE:
            attributes["power_w"] = plan.get("discharge_power")
        return attributes

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controls.async_change_plan(
            self._plan_id, plan_kind=self._plan_kind, enabled=True
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controls.async_change_plan(
            self._plan_id, plan_kind=self._plan_kind, enabled=False
        )


class StreamPlanDaySwitch(_StreamPlanEntity, SwitchEntity):
    """One weekday of a reported plan."""

    def __init__(
        self,
        controls: StreamControls,
        plan_id: int,
        index: int,
        plan_kind: str = KIND_CHARGE,
    ) -> None:
        super().__init__(
            controls,
            plan_id,
            f"day{index}",
            DAY_LABELS[index],
            "mdi:calendar-today",
            plan_kind,
        )
        self._index = index

    @property
    def is_on(self) -> bool | None:
        plan = self._plan
        if plan is None:
            return None
        return DAY_NAMES[self._index] in plan["days"]

    async def _set_day(self, on: bool) -> None:
        plan = self._plan
        if plan is None:
            raise ServiceValidationError("The plan is not reported by the device")
        if plan["repeat"] == "once":
            raise ServiceValidationError(
                "This plan runs once; choose Daily or Weekly first"
            )
        days = set(plan["days"])
        if on:
            days.add(DAY_NAMES[self._index])
        else:
            days.discard(DAY_NAMES[self._index])
        ordered = [day for day in DAY_NAMES if day in days]
        await self._controls.async_change_plan(
            self._plan_id, plan_kind=self._plan_kind, days=ordered
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set_day(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set_day(False)


def _hub_for(hass: HomeAssistant, coordinators: dict[str, Any]) -> StreamControls | None:
    """Return the hub of the first Stream device on the app channel."""
    streams = [
        coordinator
        for coordinator in coordinators.values()
        if getattr(coordinator, "device_type", None) == DEVICE_TYPE_STREAM
        and getattr(coordinator, "enhanced_mode", False)
    ]
    if not streams:
        return None
    hub = _HUBS.get(streams[0].device_sn)
    if hub is None or hub.coordinator is not streams[0]:
        hub = StreamControls(
            hass, streams[0], [coordinator.device_sn for coordinator in streams]
        )
        _HUBS[streams[0].device_sn] = hub
    return hub


def _follow_plans(
    hub: StreamControls,
    kind: str,
    factory: Callable[[int], list[Entity]],
    plans_of: Callable[[], dict[int, dict[str, Any]]] | None = None,
) -> list[Entity]:
    """Return the entities of the plans reported now and add later ones as they appear."""
    platform = entity_platform.async_get_current_platform()

    def _new_entities() -> list[Entity]:
        reported = plans_of() if plans_of is not None else hub.plans
        fresh = [plan_id for plan_id in sorted(reported) if plan_id not in hub.created[kind]]
        hub.created[kind].update(fresh)
        return [entity for plan_id in fresh for entity in factory(plan_id)]

    def _on_update() -> None:
        entities = _new_entities()
        if entities:
            platform.async_schedule_add_entities(entities)

    platform.config_entry.async_on_unload(hub.coordinator.async_add_listener(_on_update))
    return _new_entities()


def build_stream_controls(
    hass: HomeAssistant, coordinators: dict[str, Any]
) -> list[SelectEntity]:
    """Return the mode select and the selects of each reported plan."""
    hub = _hub_for(hass, coordinators)
    if hub is None:
        return []
    entities: list[Entity] = [StreamModeSelect(hub)]
    entities.extend(
        _follow_plans(
            hub,
            "select",
            lambda plan_id: [
                StreamPlanSelect(hub, plan_id, part)
                for part in ("start", "end", "source", "repeat")
            ],
        )
    )
    entities.extend(
        _follow_plans(
            hub,
            "discharge_select",
            lambda plan_id: [
                StreamPlanSelect(hub, plan_id, part, KIND_DISCHARGE)
                for part in ("start", "end", "repeat")
            ],
            plans_of=lambda: hub.discharge_plans,
        )
    )
    return [entity for entity in entities if isinstance(entity, SelectEntity)]


def build_stream_switches(
    hass: HomeAssistant, coordinators: dict[str, Any]
) -> list[SwitchEntity]:
    """Return the switches of each reported plan."""
    hub = _hub_for(hass, coordinators)
    if hub is None:
        return []
    entities = _follow_plans(
        hub,
        "switch",
        lambda plan_id: [
            StreamPlanSwitch(hub, plan_id),
            *[StreamPlanDaySwitch(hub, plan_id, index) for index in range(7)],
        ],
    )
    entities.extend(
        _follow_plans(
            hub,
            "discharge",
            lambda plan_id: [
                StreamPlanSwitch(hub, plan_id, KIND_DISCHARGE),
                *[
                    StreamPlanDaySwitch(hub, plan_id, index, KIND_DISCHARGE)
                    for index in range(7)
                ],
            ],
            plans_of=lambda: hub.discharge_plans,
        )
    )
    return [entity for entity in entities if isinstance(entity, SwitchEntity)]
