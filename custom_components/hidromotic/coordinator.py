"""DataUpdateCoordinator for Hidromotic."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .client import HidromoticClient
from .const import DOMAIN, INITIAL_DATA_WAIT_SECONDS

_LOGGER = logging.getLogger(__name__)


class HidromoticCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for Hidromotic device."""

    def __init__(
        self, hass: HomeAssistant, client: HidromoticClient, config_entry: ConfigEntry
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
            config_entry=config_entry,
        )
        self.client = client
        self._remove_callback: Callable[[], None] | None = None

    async def async_setup(self) -> bool:
        """Configura callbacks e inicia la conexión."""
        self._remove_callback = self.client.register_callback(self._on_data_update)

        if not await self.client.connect():
            return False

        try:
            await asyncio.wait_for(self.client.data_ready.wait(), timeout=INITIAL_DATA_WAIT_SECONDS)
        except TimeoutError:
            _LOGGER.error("Timeout esperando configuración en coordinator")
            return False

        self.async_set_updated_data(self.client.data)
        return True

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        if self._remove_callback:
            try:
                self._remove_callback()
            except ValueError:
                pass
            self._remove_callback = None

        await self.client.disconnect()

    @callback
    def _on_data_update(self, data: dict[str, Any]) -> None:
        """Handle data update from WebSocket."""
        self.async_set_updated_data(data)

    async def async_set_zone_state(self, zone_id: int, on: bool) -> None:
        await self.client.set_zone_state(zone_id, on)

    async def async_set_tank_state(self, tank_id: int, on: bool) -> None:
        await self.client.set_tank_state(tank_id, on)

    async def async_set_pool_state(self, pool_id: int, on: bool) -> None:
        await self.client.set_pool_state(pool_id, on)

    async def async_set_manguera_state(self, manguera_id: int, on: bool) -> None:
        await self.client.set_manguera_state(manguera_id, on)

    # RECOMENDACIÓN 2: Delegación para control de salida Ciclón
    async def async_set_ciclon_state(self, ciclon_id: int, on: bool) -> None:
        await self.client.set_ciclon_state(ciclon_id, on)

    async def async_set_riego_state(self, riego_id: int, on: bool) -> None:
        await self.client.set_riego_state(riego_id, on)

    async def async_refresh_data(self) -> None:
        await self.client.refresh()

    def get_zones(self) -> dict[int, dict[str, Any]]:
        return self.client.get_zones()

    def get_tanks(self) -> dict[int, dict[str, Any]]:
        return self.client.get_tanks()

    def get_pools(self) -> dict[int, dict[str, Any]]:
        return self.client.get_pools()

    def get_mangueras(self) -> dict[int, dict[str, Any]]:
        return self.client.get_mangueras()

    def get_ciclon(self) -> dict[int, dict[str, Any]]:
        return self.client.get_ciclon()

    def get_riegos(self) -> dict[int, dict[str, Any]]:
        return self.client.get_riegos()

    def get_pump(self) -> dict[str, Any]:
        return self.client.get_pump()
