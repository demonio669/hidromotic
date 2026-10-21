"""Switch platform for Hidromotic zones and outputs.

Este módulo gestiona la creación y actualización de todas las entidades tipo 'switch'
(interruptores) de la controladora Hidromotic, utilizando una clase base genérica
para evitar la duplicación de código (Principio DRY).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HidromoticConfigEntry
from .const import DOMAIN, STATE_DISABLED, STATE_ON
from .coordinator import HidromoticCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HidromoticConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hidromotic switches from a config entry."""
    coordinator = entry.runtime_data

    added_zones: set[int] = set()
    added_tanks: set[int] = set()
    added_pools: set[int] = set()
    added_mangueras: set[int] = set()
    added_ciclon: set[int] = set()
    added_riegos: set[int] = set()

    @callback
    def async_add_switches() -> None:
        """Add switches for newly discovered entities."""
        new_entities: list[SwitchEntity] = []

        zones = coordinator.get_zones()
        tanks = coordinator.get_tanks()
        pools = coordinator.get_pools()
        mangueras = coordinator.get_mangueras()
        ciclon = coordinator.get_ciclon()
        riegos = coordinator.get_riegos()

        if (len(zones) == len(added_zones) and
            len(tanks) == len(added_tanks) and
            len(pools) == len(added_pools) and
            len(mangueras) == len(added_mangueras) and
            len(ciclon) == len(added_ciclon) and
            len(riegos) == len(added_riegos)):
            return

        for zone_id, zone_data in zones.items():
            if zone_id not in added_zones:
                added_zones.add(zone_id)
                new_entities.append(
                    HidromoticZoneSwitch(coordinator, entry, zone_id, zone_data)
                )

        for tank_id, tank_data in tanks.items():
            if tank_id not in added_tanks:
                added_tanks.add(tank_id)
                new_entities.append(
                    HidromoticTankSwitch(coordinator, entry, tank_id, tank_data)
                )

        for pool_id, pool_data in pools.items():
            if pool_id not in added_pools:
                added_pools.add(pool_id)
                new_entities.append(
                    HidromoticPoolSwitch(coordinator, entry, pool_id, pool_data)
                )

        for manguera_id, manguera_data in mangueras.items():
            if manguera_id not in added_mangueras:
                added_mangueras.add(manguera_id)
                new_entities.append(
                    HidromoticMangueraSwitch(coordinator, entry, manguera_id, manguera_data)
                )

        for ciclon_id, ciclon_data in ciclon.items():
            if ciclon_id not in added_ciclon:
                added_ciclon.add(ciclon_id)
                new_entities.append(
                    HidromoticCiclonSwitch(coordinator, entry, ciclon_id, ciclon_data)
                )

        for riego_id, riego_data in riegos.items():
            if riego_id not in added_riegos:
                added_riegos.add(riego_id)
                new_entities.append(
                    HidromoticRiegoSwitch(coordinator, entry, riego_id, riego_data)
                )

        if new_entities:
            async_add_entities(new_entities)

    async_add_switches()
    entry.async_on_unload(coordinator.async_add_listener(async_add_switches))
    async_add_entities([HidromoticAutoRiegoSwitch(coordinator, entry)])


class HidromoticBaseSwitch(CoordinatorEntity[HidromoticCoordinator], SwitchEntity):
    """Base representation of a generic Hidromotic output switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        entity_id: int,
        entity_type: str,
        default_name: str,
        entity_data: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._entity_id = entity_id
        self._entity_type = entity_type
        self._entry = entry

        self._attr_unique_id = f"{entry.entry_id}_{entity_type}_{entity_id}"
        self._attr_name = entity_data.get("label") or default_name

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Hidromotic",
            model="CHI Smart Mini"
            if coordinator.client.data.get("is_mini")
            else "CHI Smart",
        )

    def _get_collection(self) -> dict[int, dict[str, Any]]:
        method_map = {
            "zone": self.coordinator.get_zones,
            "tank": self.coordinator.get_tanks,
            "pool": self.coordinator.get_pools,
            "manguera": self.coordinator.get_mangueras,
            "ciclon": self.coordinator.get_ciclon,
            "riego": self.coordinator.get_riegos,
        }
        return method_map[self._entity_type]()

    @property
    def available(self) -> bool:
        collection = self._get_collection()
        if self._entity_id not in collection:
            return False

        item = collection.get(self._entity_id)
        if item and item.get("estado") == STATE_DISABLED:
            return False

        return super().available

    @property
    def is_on(self) -> bool:
        item = self._get_collection().get(self._entity_id)
        if item:
            return item.get("estado", 0) == STATE_ON
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self._get_collection().get(self._entity_id)
        if item:
            return {"slot_id": item.get("slot_id")}
        return {}


# -------------------------------------------------------------------
# Clases Específicas
# -------------------------------------------------------------------

class HidromoticZoneSwitch(HidromoticBaseSwitch):
    """Representation of a Hidromotic flooding zone switch."""

    def __init__(self, coordinator, entry, zone_id, zone_data):
        super().__init__(coordinator, entry, zone_id, "zone", f"Zone {zone_id + 1}", zone_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        item = self._get_collection().get(self._entity_id)
        if item:
            attrs["duration_minutes"] = item.get("duracion", 0)
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_zone_state(self._entity_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_zone_state(self._entity_id, False)


class HidromoticTankSwitch(HidromoticBaseSwitch):
    """Representation of a Hidromotic tank filling switch."""

    def __init__(self, coordinator, entry, tank_id, tank_data):
        super().__init__(coordinator, entry, tank_id, "tank", f"Tank {tank_id + 1}", tank_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Agrega atributos específicos del tanque (nivel, modo, duración y ETC)."""
        attrs = super().extra_state_attributes
        item = self._get_collection().get(self._entity_id)
        if item:
            # Estado del nivel (Lleno, Vacío, Medio, etc.)
            attrs["level"] = self.coordinator.client.get_tank_level(self._entity_id)
            # Duración del temporizador de llenado en minutos
            attrs["duration_minutes"] = item.get("duracion", 0)

            # Interpretación del modo: 1 = Automático, 0 = Manual
            modo_raw = item.get("modo", 0)
            attrs["mode_raw"] = modo_raw
            attrs["mode"] = "automatic" if modo_raw != 0 else "manual"

            # Tiempo estimado / restante (etc)
            attrs["etc"] = item.get("etc", 0)
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_tank_state(self._entity_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_tank_state(self._entity_id, False)


class HidromoticPoolSwitch(HidromoticBaseSwitch):
    """Representation of a Hidromotic Pool switch."""

    def __init__(self, coordinator, entry, pool_id, pool_data):
        super().__init__(coordinator, entry, pool_id, "pool", f"Pool {pool_id + 1}", pool_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        item = self._get_collection().get(self._entity_id)
        if item:
            attrs["duration_minutes"] = item.get("duracion", 0)
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_pool_state(self._entity_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_pool_state(self._entity_id, False)


class HidromoticMangueraSwitch(HidromoticBaseSwitch):
    """Representation of a Hidromotic Hose switch."""

    def __init__(self, coordinator, entry, manguera_id, manguera_data):
        super().__init__(coordinator, entry, manguera_id, "manguera", f"Manguera {manguera_id + 1}", manguera_data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_manguera_state(self._entity_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_manguera_state(self._entity_id, False)


class HidromoticCiclonSwitch(HidromoticBaseSwitch):
    """Representation of a Hidromotic Cyclon output switch."""

    def __init__(self, coordinator, entry, ciclon_id, ciclon_data):
        super().__init__(coordinator, entry, ciclon_id, "ciclon", f"Ciclon {ciclon_id + 1}", ciclon_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        item = self._get_collection().get(self._entity_id)
        if item:
            attrs.update({
                "modo_ante_tareas": item.get("modo_ante_tareas"),
                "modo_fin_de_tareas": item.get("modo_fin_de_tareas"),
                "modo_tiempo": item.get("modo_tiempo"),
                "proximo_ciclon_seg": item.get("proximo_ciclon", 0),
            })
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_ciclon_state(self._entity_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_ciclon_state(self._entity_id, False)


class HidromoticRiegoSwitch(HidromoticBaseSwitch):
    """Representation of a Hidromotic Irrigation program switch."""

    def __init__(self, coordinator, entry, riego_id, riego_data):
        super().__init__(coordinator, entry, riego_id, "riego", f"Riego {riego_id + 1}", riego_data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_riego_state(self._entity_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_riego_state(self._entity_id, False)


class HidromoticAutoRiegoSwitch(CoordinatorEntity[HidromoticCoordinator], SwitchEntity):
    """Representation of the global Auto Irrigation toggle."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_auto_riego"
        self._attr_name = "Auto irrigation"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Hidromotic",
            model="CHI Smart Mini"
            if coordinator.client.data.get("is_mini")
            else "CHI Smart",
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.client.is_auto_riego_on()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_auto_riego(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_auto_riego(False)
