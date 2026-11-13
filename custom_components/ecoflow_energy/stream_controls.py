"""Native Stream controls (BK-series): operating mode and grid charging.

Four select entities, created once per config entry on the first Stream
device with an app-channel connection:

- Operating mode: self-powered, custom, AI (``106 { <mode>: 1 }``, see
  ``ecoflow/stream_mode.py``). The setting applies to both devices of a pair.
- Grid charging: "Solar only" or "Grid and solar". Choosing either one first
  switches to custom mode, then sends the charge plan with the source.
- Charge window start / end: the window the plan uses, in half-hour steps.

The device reports neither the mode nor the plan source back, so every entity
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
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_TYPE_STREAM
from .ecoflow.stream_mode import MODES, build_mode_frame
from .ecoflow.stream_schedule_request import build_schedule_request_frame
from .schedule_service import _next_sequence

_LOGGER = logging.getLogger(__name__)

PLAN_ID = 2
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


def _key_for(labels: dict[str, str], label: str) -> str:
    return next(key for key, value in labels.items() if value == label)


class StreamControls:
    """What the four selects share: the device, the serials and the last values."""

    def __init__(
        self, hass: HomeAssistant, coordinator: Any, serials: list[str]
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.serial: str = coordinator.device_sn
        self.serials = serials
        self.entities: dict[str, _StreamControlSelect] = {}

    def _show(self, key: str, option: str) -> None:
        entity = self.entities.get(key)
        if entity is not None:
            entity.show(option)

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

    def _window(self) -> tuple[str, str]:
        start = self.entities.get("window_start")
        end = self.entities.get("window_end")
        start_value = start.current_option if start else None
        end_value = end.current_option if end else None
        if start_value is None or end_value is None:
            raise ServiceValidationError(
                "Choose the charge window start and end before switching grid charging"
            )
        if start_value == end_value:
            raise ServiceValidationError("The charge window start and end are equal")
        return start_value, end_value

    async def async_set_source(self, source: str) -> None:
        """Switch to custom mode, then send the plan with this source."""
        start, end = self._window()
        try:
            frame = build_schedule_request_frame(
                header_serial=self.serial,
                serials=self.serials,
                plan_id=PLAN_ID,
                start=start,
                end=end,
                source=source,
                soc_pct=PLAN_SOC_PCT,
                power_w=PLAN_POWER_W,
                sequence=_next_sequence(),
                timestamp=int(time.time()),
                operation="change",
            )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

        await self.async_set_mode("custom")
        await asyncio.sleep(MODE_SWITCH_PAUSE_S)
        await self._send(frame)
        self._show("grid_charge", SOURCE_LABELS[source])
        _LOGGER.info(
            "Stream plan %s sent: %s-%s (%s)", PLAN_ID, start, end, source
        )


class _StreamControlSelect(CoordinatorEntity, SelectEntity, RestoreEntity):
    """A select that remembers what was last sent."""

    _attr_has_entity_name = True
    _attr_assumed_state = True

    def __init__(
        self,
        controls: StreamControls,
        key: str,
        name: str,
        icon: str,
        options: list[str],
    ) -> None:
        super().__init__(controls.coordinator)
        self._controls = controls
        self._key = key
        self._attr_unique_id = f"{controls.serial}_stream_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_options = options
        self._option: str | None = None

    @property
    def available(self) -> bool:
        return self.coordinator.device_available and super().available

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.device_info

    @property
    def current_option(self) -> str | None:
        return self._option

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._controls.entities[self._key] = self
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self._option = last.state

    async def async_will_remove_from_hass(self) -> None:
        self._controls.entities.pop(self._key, None)
        await super().async_will_remove_from_hass()

    @callback
    def show(self, option: str) -> None:
        self._option = option
        self.async_write_ha_state()


class StreamModeSelect(_StreamControlSelect):
    """Operating mode of the Stream (both devices of a pair)."""

    def __init__(self, controls: StreamControls) -> None:
        super().__init__(
            controls, "mode", "Operating mode", "mdi:tune", list(MODE_LABELS.values())
        )

    async def async_select_option(self, option: str) -> None:
        await self._controls.async_set_mode(_key_for(MODE_LABELS, option))


class StreamGridChargeSelect(_StreamControlSelect):
    """Charge plan source; choosing one also switches to custom mode."""

    def __init__(self, controls: StreamControls) -> None:
        super().__init__(
            controls,
            "grid_charge",
            "Battery charging source",
            "mdi:transmission-tower-import",
            list(SOURCE_LABELS.values()),
        )

    async def async_select_option(self, option: str) -> None:
        await self._controls.async_set_source(_key_for(SOURCE_LABELS, option))


class StreamWindowSelect(_StreamControlSelect):
    """Start or end of the charge window; applied with the next source choice."""

    def __init__(self, controls: StreamControls, *, end: bool) -> None:
        super().__init__(
            controls,
            "window_end" if end else "window_start",
            "Charge window end" if end else "Charge window start",
            "mdi:clock-end" if end else "mdi:clock-start",
            END_OPTIONS if end else START_OPTIONS,
        )

    async def async_select_option(self, option: str) -> None:
        self.show(option)


def build_stream_controls(
    hass: HomeAssistant, coordinators: dict[str, Any]
) -> list[SelectEntity]:
    """Return the four selects for the first Stream device on the app channel."""
    streams = [
        coordinator
        for coordinator in coordinators.values()
        if getattr(coordinator, "device_type", None) == DEVICE_TYPE_STREAM
        and getattr(coordinator, "enhanced_mode", False)
    ]
    if not streams:
        return []
    controls = StreamControls(
        hass, streams[0], [coordinator.device_sn for coordinator in streams]
    )
    return [
        StreamModeSelect(controls),
        StreamGridChargeSelect(controls),
        StreamWindowSelect(controls, end=False),
        StreamWindowSelect(controls, end=True),
    ]
