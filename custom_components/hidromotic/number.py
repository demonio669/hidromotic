"""Number platform for Hidromotic output durations.

Este módulo crea entidades tipo 'number' ÚNICAMENTE para:
1. Ajustar el tiempo de llenado/filtrado de las Piletas en minutos.
2. Ajustar la duración de las zonas (0 a 9999 minutos).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HidromoticConfigEntry
from .const import DOMAIN
from .coordinator import HidromoticCoordinator
from .entity_helpers import output_is_available, update_output_entity_visibility

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HidromoticConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hidromotic duration numbers from a config entry."""
    coordinator = entry.runtime_data
    added_pools: set[int] = set()
    added_zones: set[int] = set()

    @callback
    def async_add_number_entities() -> None:
        """Add duration controls for pools and irrigation zones."""
        pools = coordinator.get_pools()
        zones = coordinator.get_zones()
        new_entities: list[NumberEntity] = []

        # 1. Controles de tiempo para Piletas
        for pool_id, pool_data in pools.items():
            unique_id = f"{entry.entry_id}_pool_{pool_id}_duration_set"
            available = output_is_available(pool_data)
            update_output_entity_visibility(hass, "number", unique_id, available)
            if available and pool_id not in added_pools:
                added_pools.add(pool_id)
                new_entities.append(
                    HidromoticPoolDurationNumber(coordinator, entry, pool_id, pool_data)
                )

        # 2. Controles de duración de las salidas de zona, no de los programas.
        for zone_id, zone_data in zones.items():
            unique_id = f"{entry.entry_id}_zone_{zone_id}_duration_set"
            available = output_is_available(zone_data)
            update_output_entity_visibility(hass, "number", unique_id, available)
            if available and zone_id not in added_zones:
                added_zones.add(zone_id)
                new_entities.append(
                    HidromoticZoneDurationNumber(
                        coordinator, entry, zone_id, zone_data
                    )
                )

        if new_entities:
            async_add_entities(new_entities)

    async_add_number_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_number_entities))


class HidromoticPoolDurationNumber(CoordinatorEntity[HidromoticCoordinator], NumberEntity):
    """Control numérico para ajustar la duración de la pileta/piscina."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value = 1
    _attr_native_max_value = 9999
    _attr_native_step = 1
    _attr_icon = "mdi:timer-cog"

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        pool_id: int,
        pool_data: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._pool_id = pool_id
        self._entry = entry

        self._attr_unique_id = f"{entry.entry_id}_pool_{pool_id}_duration_set"
        base_label = pool_data.get("label") or f"Piscina {pool_id + 1}"
        self._attr_name = f"{base_label} Tiempo de Llenado"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Hidromotic",
            model="CHI Smart Mini"
            if coordinator.client.data.get("is_mini")
            else "CHI Smart",
        )

    @property
    def available(self) -> bool:
        pools = self.coordinator.get_pools()
        pool = pools.get(self._pool_id)
        if not output_is_available(pool):
            return False
        return super().available

    @property
    def native_value(self) -> float | None:
        pool = self.coordinator.get_pools().get(self._pool_id)
        if pool:
            return float(pool.get("duracion", 0))
        return None

    async def async_set_native_value(self, value: float) -> None:
        minutes = int(value)
        await self.coordinator.client.set_output_duration("pools", self._pool_id, minutes)


class HidromoticZoneDurationNumber(CoordinatorEntity[HidromoticCoordinator], NumberEntity):
    """Control numérico para ajustar la duración de una salida de zona."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value = 0
    _attr_native_max_value = 9999
    _attr_native_step = 1
    _attr_icon = "mdi:sprinkler-variant"

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        zone_id: int,
        zone_data: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._entry = entry

        zone_label = zone_data.get("label") or str(zone_id + 1)
        entity_name = (
            zone_label
            if zone_label.casefold().startswith("zona ")
            else f"Zona {zone_label}"
        )
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone_id}_duration_set"
        self._attr_name = f"{entity_name} Duración"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Hidromotic",
            model="CHI Smart Mini"
            if coordinator.client.data.get("is_mini")
            else "CHI Smart",
        )

    @property
    def available(self) -> bool:
        zones = self.coordinator.get_zones()
        zone = zones.get(self._zone_id)
        if not output_is_available(zone):
            return False
        return super().available

    @property
    def native_value(self) -> float | None:
        zone = self.coordinator.get_zones().get(self._zone_id)
        if zone is None:
            return None
        return float(zone.get("duracion", 0))

    async def async_set_native_value(self, value: float) -> None:
        minutes = int(value)
        await self.coordinator.client.set_output_duration("zones", self._zone_id, minutes)
