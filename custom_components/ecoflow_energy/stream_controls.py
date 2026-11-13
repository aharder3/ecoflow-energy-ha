"""Native Stream controls (BK-series): operating mode and three charge plans.

Created once per config entry, on the first Stream device with an app-channel
connection:

- Operating mode (select): self-powered, custom, AI (``106 { <mode>: 1 }``,
  see ``ecoflow/stream_mode.py``). The setting applies to both devices of a pair.
- For each of the plans 2, 3 and 4: a switch that activates the plan, and
  selects for its start, end and source (solar only, or grid and solar).

Switching a plan on first switches to custom mode, then sends the plan with
flag 4 set; switching it off sends the same plan without flag 4, which is what
the vendor app does. Changing start, end or source of a plan that is on sends
the plan again. Plan 4 is created on its first activation; plans 2 and 3 are
changed. Other plans (the discharge plans, for one) are never touched.

The device reports neither the mode nor the plan state back, so every entity
shows the value last sent from Home Assistant and restores it after a restart.
A change made in the vendor app is therefore not reflected here.
"""

from __future__ import annotations

import asyncio
import logging
import time
from functools import partial
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_TYPE_STREAM
from .ecoflow.stream_mode import build_mode_frame
from .ecoflow.stream_schedule_request import build_schedule_request_frame
from .schedule_service import _next_sequence

_LOGGER = logging.getLogger(__name__)

PLAN_IDS = (2, 3, 4)
# Plans the app may not have yet: the first activation creates them.
CREATE_FIRST = frozenset({4})
PLAN_SOC_PCT = 95
PLAN_POWER_W = 1050
MODE_SWITCH_PAUSE_S = 2.0

MODE_LABELS = {
    "self_powered": "Self-powered",
    "custom": "Custom",
    "ai": "AI",
}
SOURCE_LABELS = {
    "solar": "Solar only",
    "grid_and_solar": "Grid and solar",
}
_TIMES = [f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in (0, 30)]
START_OPTIONS = _TIMES
END_OPTIONS = [*_TIMES, "24:00"]

_HUBS: dict[str, StreamControls] = {}


def _key_for(labels: dict[str, str], label: str) -> str:
    return next(key for key, value in labels.items() if value == label)


class StreamControls:
    """What the entities share: the device, the serials and the last values."""

    def __init__(
        self, hass: HomeAssistant, coordinator: Any, serials: list[str]
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.serial: str = coordinator.device_sn
        self.serials = serials
        self.entities: dict[str, Any] = {}
        self.created: set[int] = set()

    def _show(self, key: str, value: Any) -> None:
        entity = self.entities.get(key)
        if entity is not None:
            entity.show(value)

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
        """Send the mode frame and show the new mode."""
        frame = build_mode_frame(
            mode,
            device_serial=self.serial,
            sequence=_next_sequence(),
            timestamp=int(time.time()),
        )
        await self._send(frame)
        self._show("mode", MODE_LABELS[mode])
        _LOGGER.info("Stream mode set to %s (%s)", mode, self.serial[:4])

    def _plan_values(self, plan: int) -> tuple[str, str, str]:
        values = []
        for part in ("start", "end", "source"):
            entity = self.entities.get(f"plan{plan}_{part}")
            values.append(entity.current_option if entity is not None else None)
        start, end, label = values
        if start is None or end is None or label is None:
            raise ServiceValidationError(
                f"Choose start, end and source of plan {plan} first"
            )
        if start == end:
            raise ServiceValidationError(f"Start and end of plan {plan} are equal")
        return start, end, _key_for(SOURCE_LABELS, label)

    async def async_send_plan(self, plan: int, enabled: bool) -> None:
        """Send one plan with the values the entities hold."""
        start, end, source = self._plan_values(plan)
        operation = (
            "create" if plan in CREATE_FIRST and plan not in self.created else "change"
        )
        try:
            frame = build_schedule_request_frame(
                header_serial=self.serial,
                serials=self.serials,
                plan_id=plan,
                start=start,
                end=end,
                source=source,
                soc_pct=PLAN_SOC_PCT,
                power_w=PLAN_POWER_W,
                sequence=_next_sequence(),
                timestamp=int(time.time()),
                operation=operation,
                flag4=1 if enabled else None,
            )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        await self._send(frame)
        self.created.add(plan)
        _LOGGER.info(
            "Stream plan %s sent: %s-%s (%s, %s, %s)",
            plan,
            start,
            end,
            source,
            operation,
            "on" if enabled else "off",
        )

    async def async_set_plan_enabled(self, plan: int, enabled: bool) -> None:
        """Switch a plan on (custom mode first) or off."""
        if enabled:
            self._plan_values(plan)
            await self.async_set_mode("custom")
            await asyncio.sleep(MODE_SWITCH_PAUSE_S)
        await self.async_send_plan(plan, enabled)
        self._show(f"plan{plan}_enabled", enabled)

    async def async_plan_changed(self, plan: int) -> None:
        """Send the plan again when it is on and one of its values changed."""
        switch = self.entities.get(f"plan{plan}_enabled")
        if switch is not None and switch.is_on:
            await self.async_send_plan(plan, True)


class _StreamEntity(CoordinatorEntity):
    """Common parts of the select and switch entities."""

    _attr_has_entity_name = True
    _attr_assumed_state = True

    def __init__(self, controls: StreamControls, key: str, name: str, icon: str):
        super().__init__(controls.coordinator)
        self._controls = controls
        self._key = key
        self._attr_unique_id = f"{controls.serial}_stream_{key}"
        self._attr_name = name
        self._attr_icon = icon

    @property
    def available(self) -> bool:
        return self.coordinator.device_available and super().available

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.device_info

    async def async_will_remove_from_hass(self) -> None:
        self._controls.entities.pop(self._key, None)
        await super().async_will_remove_from_hass()


class _StreamSelect(_StreamEntity, SelectEntity, RestoreEntity):
    """A select that remembers what was last sent."""

    def __init__(self, controls, key, name, icon, options: list[str]) -> None:
        super().__init__(controls, key, name, icon)
        self._attr_options = options
        self._option: str | None = None

    @property
    def current_option(self) -> str | None:
        return self._option

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._controls.entities[self._key] = self
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self._option = last.state

    @callback
    def show(self, option: str) -> None:
        self._option = option
        self.async_write_ha_state()


class StreamModeSelect(_StreamSelect):
    """Operating mode of the Stream (both devices of a pair)."""

    def __init__(self, controls: StreamControls) -> None:
        super().__init__(
            controls, "mode", "Operating mode", "mdi:tune", list(MODE_LABELS.values())
        )

    async def async_select_option(self, option: str) -> None:
        await self._controls.async_set_mode(_key_for(MODE_LABELS, option))


class StreamPlanSelect(_StreamSelect):
    """Start, end or source of one plan."""

    def __init__(self, controls: StreamControls, plan: int, part: str) -> None:
        options = {
            "start": START_OPTIONS,
            "end": END_OPTIONS,
            "source": list(SOURCE_LABELS.values()),
        }[part]
        icon = {
            "start": "mdi:clock-start",
            "end": "mdi:clock-end",
            "source": "mdi:transmission-tower-import",
        }[part]
        # Entities are listed alphabetically by name, so "stop" keeps the end
        # select behind "start".
        label = {"start": "start", "end": "stop", "source": "source"}[part]
        super().__init__(
            controls,
            f"plan{plan}_{part}",
            f"Plan {plan} {label}",
            icon,
            list(options),
        )
        self._plan = plan

    async def async_select_option(self, option: str) -> None:
        self.show(option)
        await self._controls.async_plan_changed(self._plan)


class StreamPlanSwitch(_StreamEntity, SwitchEntity, RestoreEntity):
    """Activates or deactivates one plan."""

    def __init__(self, controls: StreamControls, plan: int) -> None:
        super().__init__(
            controls, f"plan{plan}_enabled", f"Plan {plan}", "mdi:calendar-clock"
        )
        self._plan = plan
        self._on: bool | None = None

    @property
    def is_on(self) -> bool | None:
        return self._on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"plan_created": self._plan in self._controls.created}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._controls.entities[self._key] = self
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._on = last.state == "on"
            if last.attributes.get("plan_created"):
                self._controls.created.add(self._plan)

    @callback
    def show(self, value: bool) -> None:
        self._on = value
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controls.async_set_plan_enabled(self._plan, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controls.async_set_plan_enabled(self._plan, False)


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


def build_stream_controls(
    hass: HomeAssistant, coordinators: dict[str, Any]
) -> list[SelectEntity]:
    """Return the mode select and the start, end and source select of each plan."""
    hub = _hub_for(hass, coordinators)
    if hub is None:
        return []
    entities: list[SelectEntity] = [StreamModeSelect(hub)]
    for plan in PLAN_IDS:
        entities.extend(StreamPlanSelect(hub, plan, part) for part in ("start", "end", "source"))
    return entities


def build_stream_switches(
    hass: HomeAssistant, coordinators: dict[str, Any]
) -> list[SwitchEntity]:
    """Return the activation switch of each plan."""
    hub = _hub_for(hass, coordinators)
    if hub is None:
        return []
    return [StreamPlanSwitch(hub, plan) for plan in PLAN_IDS]
