"""Home Assistant service that switches the Stream operating mode (experimental).

Sends ``106 { <mode>: 1 }`` (cmd 254/17) over the app-channel MQTT client the
coordinator already holds. See ``ecoflow/stream_mode.py`` for what is known.
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
from .ecoflow.stream_mode import MODES, build_mode_frame
from .schedule_service import _find_coordinator, _next_sequence

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_STREAM_MODE = "set_stream_mode"

SET_STREAM_MODE_SCHEMA = vol.Schema(
    {
        vol.Required("serial"): cv.string,
        vol.Required("mode"): vol.In(tuple(MODES)),
    }
)


async def _async_set_stream_mode(hass: HomeAssistant, call: ServiceCall) -> None:
    serial = call.data["serial"]
    coordinator = _find_coordinator(hass, serial)
    client = getattr(coordinator, "mqtt_client", None)
    if client is None or not client.is_connected():
        raise HomeAssistantError(f"Device {serial[:4]} not found or MQTT not connected")

    try:
        frame = build_mode_frame(
            call.data["mode"],
            device_serial=serial,
            sequence=_next_sequence(),
            timestamp=int(time.time()),
        )
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err

    ok = await hass.async_add_executor_job(
        partial(client.send_proto_set, frame, wait=True)
    )
    if not ok:
        raise HomeAssistantError("The broker did not acknowledge the mode frame")
    _LOGGER.info("Stream mode set to %s (%s)", call.data["mode"], serial[:4])


def async_register_mode_service(hass: HomeAssistant) -> None:
    """Register ``ecoflow_energy.set_stream_mode`` once."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_STREAM_MODE):
        return

    async def _handler(call: ServiceCall) -> None:
        await _async_set_stream_mode(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_STREAM_MODE,
        _handler,
        schema=SET_STREAM_MODE_SCHEMA,
    )
