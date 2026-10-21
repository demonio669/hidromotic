"""The Hidromotic integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import HidromoticClient, hex_to_int, int_to_hex
from .coordinator import HidromoticCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.BINARY_SENSOR, Platform.SENSOR]

type HidromoticConfigEntry = ConfigEntry[HidromoticCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HidromoticConfigEntry) -> bool:
    """Set up Hidromotic from a config entry."""
    host = entry.data[CONF_HOST]

    # Reutiliza la sesión HTTP global administrada por Home Assistant
    session = async_get_clientsession(hass)
    client = HidromoticClient(host, session=session)

    coordinator = HidromoticCoordinator(hass, client, entry)

    if not await coordinator.async_setup():
        raise ConfigEntryNotReady(f"Failed to connect to Hidromotic device at {host}")

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: HidromoticConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown()

    return unload_ok
