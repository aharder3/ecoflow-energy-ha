"""Text platform for EcoFlow Energy: the weekdays of a Stream plan."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .stream_controls import build_stream_texts


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Stream plan day fields of a config entry."""
    coordinators = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(build_stream_texts(hass, coordinators))
