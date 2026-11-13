"""Registers the experimental Stream services in one call."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .mode_service import async_register_mode_service
from .schedule_service import async_register_schedule_service


def async_register_services(hass: HomeAssistant) -> None:
    """Register ``send_stream_schedule`` and ``set_stream_mode``."""
    async_register_schedule_service(hass)
    async_register_mode_service(hass)
