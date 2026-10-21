"""Number platform for Hidromotic output and irrigation durations.

Este módulo crea entidades tipo 'number' ÚNICAMENTE para:
1. Ajustar el tiempo de llenado/filtrado de las Piletas en minutos.
2. Ajustar la duración de las zonas de Riego HABILITADAS (minutos > 0).
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
from .const import DOMAIN, STATE_DISABLED
from .coordinator import HidromoticCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HidromoticConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hidromotic duration numbers from a config entry."""
    coordinator = entry.runtime_data
    added_pools: set[int] = set()
    added_riego_zonas: set[str] = set()

    @callback
    def async_add_number_entities() -> None:
        """Add duration controls ONLY for enabled pools and active irrigation zones."""
        pools = coordinator.get_pools()
        riegos = coordinator.get_riegos()
        new_entities: list[NumberEntity] = []

        # 1. Controles de tiempo para Piletas
        for pool_id, pool_data in pools.items():
            if pool_id not in added_pools:
                added_pools.add(pool_id)
                new_entities.append(
                    HidromoticPoolDurationNumber(coordinator, entry, pool_id, pool_data)
                )

        # 2. Controles de tiempo EXCLUSIVAMENTE para Zonas de Riego habilitadas (> 0 min)
        max_zonas = 6 if coordinator.client.data.get("is_mini") else 12
        for riego_id, riego_data in riegos.items():
            zonas = riego_data.get("zonas", {})
            for z_idx in range(max_zonas):
                entity_key = f"{riego_id}_z_{z_idx}"
                duracion = zonas.get(f"duracion_{z_idx + 1}", 0)

                # FILTRO DIRECTO: Si la duración es 0, no se crea ni se registra la entidad
                if duracion > 0 and entity_key not in added_riego_zonas:
                    added_riego_zonas.add(entity_key)
                    new_entities.append(
                        HidromoticRiegoZonaDurationNumber(
                            coordinator, entry, riego_id, z_idx, riego_data
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
        if self._pool_id not in pools:
            return False
        pool = pools.get(self._pool_id)
        if pool and pool.get("estado") == STATE_DISABLED:
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


class HidromoticRiegoZonaDurationNumber(CoordinatorEntity[HidromoticCoordinator], NumberEntity):
    """Control numérico para ajustar la duración de una zona en un programa de Riego."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value = 1
    _attr_native_max_value = 999
    _attr_native_step = 1
    _attr_icon = "mdi:sprinkler-variant"

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        riego_id: int,
        zona_idx: int,
        riego_data: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._riego_id = riego_id
        self._zona_idx = zona_idx
        self._entry = entry

        riego_label = riego_data.get("label") or f"Riego {chr(65 + riego_id)}"
        self._attr_unique_id = f"{entry.entry_id}_riego_{riego_id}_z_{zona_idx + 1}_duration"
        self._attr_name = f"{riego_label} Zona {zona_idx + 1} Duración"

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
        riegos = self.coordinator.get_riegos()
        return self._riego_id in riegos and super().available

    @property
    def native_value(self) -> float | None:
        riego = self.coordinator.get_riegos().get(self._riego_id)
        if riego and "zonas" in riego:
            return float(riego["zonas"].get(f"duracion_{self._zona_idx + 1}", 0))
        return 0

    async def async_set_native_value(self, value: float) -> None:
        minutes = int(value)
        await self.coordinator.client.set_riego_zona_duration(
            self._riego_id, self._zona_idx, minutes
        )
