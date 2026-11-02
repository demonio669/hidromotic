"""Helpers for entities that reflect dynamically enabled CHI outputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryHider

from .const import DOMAIN, STATE_DISABLED


def output_is_available(output: Mapping[str, Any] | None) -> bool:
    """Return whether a configured output is enabled by the CHI."""
    return output is not None and output.get("estado") != STATE_DISABLED


def update_output_entity_visibility(
    hass: HomeAssistant,
    platform: str,
    unique_id: str,
    available: bool,
) -> None:
    """Hide disabled outputs and restore their visibility when enabled."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
    if entity_id is None:
        return

    entry = registry.async_get(entity_id)
    if entry is None:
        return

    if available:
        if entry.hidden_by == RegistryEntryHider.INTEGRATION:
            registry.async_update_entity(entity_id, hidden_by=None)
    elif entry.hidden_by is None:
        registry.async_update_entity(
            entity_id, hidden_by=RegistryEntryHider.INTEGRATION
        )
