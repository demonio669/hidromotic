"""The Hidromotic integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .client import HidromoticClient, hex_to_int, int_to_hex, normalize_mac_address
from .cloud_client import HidromoticCloudClient
from .const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_TYPE_CLOUD,
    DOMAIN,
)
from .coordinator import HidromoticCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.SELECT,
]

type HidromoticConfigEntry = ConfigEntry[HidromoticCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HidromoticConfigEntry) -> bool:
    """Set up Hidromotic from a config entry."""
    # Reutiliza la sesión HTTP global administrada por Home Assistant
    session = async_get_clientsession(hass)
    integration = await async_get_integration(hass, DOMAIN)
    if entry.data.get(CONF_CONNECTION_TYPE) == CONNECTION_TYPE_CLOUD:
        client = HidromoticCloudClient(
            entry.data["username"],
            entry.data["password"],
            session=session,
        )
        connection_name = "Hidromotic cloud"
    else:
        host = entry.data[CONF_HOST]
        client = HidromoticClient(host, session=session)
        connection_name = f"Hidromotic device at {host}"

    coordinator = HidromoticCoordinator(hass, client, entry, integration.version)

    if not await coordinator.async_setup():
        await coordinator.async_shutdown()
        raise ConfigEntryNotReady(f"Failed to connect to {connection_name}")

    mac = normalize_mac_address(client.data.get("mac"))
    if mac is None:
        await coordinator.async_shutdown()
        raise ConfigEntryNotReady("Hidromotic did not provide a valid MAC address")
    if entry.unique_id != mac:
        duplicate = next(
            (
                configured_entry
                for configured_entry in hass.config_entries.async_entries(DOMAIN)
                if configured_entry.entry_id != entry.entry_id
                and configured_entry.unique_id == mac
            ),
            None,
        )
        if duplicate is not None:
            await coordinator.async_shutdown()
            raise ConfigEntryNotReady(
                f"MAC address {mac} is already configured by another entry"
            )
        hass.config_entries.async_update_entry(entry, unique_id=mac)

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: HidromoticConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown()

    return unload_ok
