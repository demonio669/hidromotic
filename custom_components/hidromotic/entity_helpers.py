"""Helpers for entities that reflect dynamically enabled CHI outputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_registry import RegistryEntryHider

from .const import CONNECTION_TYPE_CLOUD, DOMAIN, STATE_DISABLED
from .coordinator import HidromoticCoordinator


def hidromotic_device_info(
    coordinator: HidromoticCoordinator, entry: ConfigEntry
) -> DeviceInfo:
    """Return consistent registry details for the CHI device."""
    client = coordinator.client
    is_cloud = client.connection_type == CONNECTION_TYPE_CLOUD
    username = client.account_username
    if is_cloud and username:
        model_id = f"Cloud - usuario: {username}"
    elif is_cloud:
        model_id = "Cloud"
    else:
        model_id = "Local"
    device_id = client.data.get("device_id")

    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Hidromotic",
        model="CHI Smart Mini" if client.data.get("is_mini") else "CHI Smart",
        model_id=model_id,
        serial_number=device_id if isinstance(device_id, str) else None,
        sw_version=coordinator.integration_version,
    )


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
