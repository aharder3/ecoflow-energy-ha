"""Home Assistant service for the Stream scheduled charge (experimental).

Sends one schedule frame (cmd 254/17, field 595) to a Stream device over the
app-channel MQTT client the coordinator already holds. The frame layout is the
one decoded from the vendor app; see ``ecoflow/stream_schedule.py``.

Not yet hooked into ``async_setup`` - see documentation/stream-schedule-service.md.
"""

from __future__ import annotations

import logging
import time
from functools import partial

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DOMAIN
from .ecoflow.stream_schedule_request import (
    OPERATIONS,
    SOURCES,
    build_schedule_request_frame,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_SEND_STREAM_SCHEDULE = "send_stream_schedule"

# The app counts its own frames upward from small numbers. Starting well above
# that keeps ours apart in the shared sequence space; the device has not been
# seen to care either way.
_SEQUENCE_START = 100
_sequence = _SEQUENCE_START

SEND_STREAM_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("serial"): cv.string,
        vol.Optional("serials"): vol.All(cv.ensure_list, [cv.string]),
        vol.Required("plan_id"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required("start"): cv.string,
        vol.Required("end"): cv.string,
        vol.Required("source"): vol.In(SOURCES),
        vol.Optional("soc", default=95): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
        vol.Optional("power", default=1050): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
        vol.Optional("operation", default="change"): vol.In(tuple(OPERATIONS)),
        # The app sends flag 4 = 1 for a plan that is switched on and leaves it
        # out for one that is switched off (observed on plans 2 and 3).
        vol.Optional("enabled", default=True): cv.boolean,
    }
)


def _next_sequence() -> int:
    global _sequence
    _sequence += 1
    return _sequence


def _find_coordinator(hass: HomeAssistant, serial: str):
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if isinstance(entry_data, dict) and serial in entry_data:
            return entry_data[serial]
    return None


async def _async_send_stream_schedule(hass: HomeAssistant, call: ServiceCall) -> None:
    data = call.data
    serial = data["serial"]
    coordinator = _find_coordinator(hass, serial)
    client = getattr(coordinator, "mqtt_client", None)
    if client is None or not client.is_connected():
        raise HomeAssistantError(f"Device {serial[:4]} not found or MQTT not connected")

    try:
        frame = build_schedule_request_frame(
            header_serial=serial,
            serials=data.get("serials") or [serial],
            plan_id=data["plan_id"],
            start=data["start"],
            end=data["end"],
            source=data["source"],
            soc_pct=data["soc"],
            power_w=data["power"],
            sequence=_next_sequence(),
            timestamp=int(time.time()),
            operation=data["operation"],
            flag4=1 if data["enabled"] else None,
        )
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err

    ok = await hass.async_add_executor_job(
        partial(client.send_proto_set, frame, wait=True)
    )
    if not ok:
        raise HomeAssistantError("The broker did not acknowledge the schedule frame")
    _LOGGER.info(
        "Stream schedule sent: plan %s %s-%s (%s, %s)",
        data["plan_id"],
        data["start"],
        data["end"],
        data["source"],
        "on" if data["enabled"] else "off",
    )


def async_register_schedule_service(hass: HomeAssistant) -> None:
    """Register ``ecoflow_energy.send_stream_schedule`` once."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_STREAM_SCHEDULE):
        return

    async def _handler(call: ServiceCall) -> None:
        await _async_send_stream_schedule(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_STREAM_SCHEDULE,
        _handler,
        schema=SEND_STREAM_SCHEDULE_SCHEMA,
    )
