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
from .const import DOMAIN, STATE_ON
from .coordinator import HidromoticCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HidromoticConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hidromotic switches from a config entry."""
    coordinator = entry.runtime_data

    # Conjuntos para rastrear qué entidades ya fueron añadidas a Home Assistant.
    # Esto es crucial para evitar errores de "Entity already exists" cuando
    # el WebSocket recibe actualizaciones dinámicas.
    added_zones: set[int] = set()
    added_tanks: set[int] = set()
    added_pools: set[int] = set()
    added_mangueras: set[int] = set()
    added_riegos: set[int] = set()

    @callback
    def async_add_switches() -> None:
        """Add switches for newly discovered entities."""
        new_entities: list[SwitchEntity] = []

        # 1. OPTIMIZACIÓN: Obtenemos todas las colecciones desde el coordinador
        # una única vez al principio para evitar llamadas redundantes a memoria.
        zones = coordinator.get_zones()
        tanks = coordinator.get_tanks()
        pools = coordinator.get_pools()
        mangueras = coordinator.get_mangueras()
        riegos = coordinator.get_riegos()

        # 2. OPTIMIZACIÓN (Salida temprana): Verificamos si la cantidad de elementos en
        # las colecciones coincide con lo que ya agregamos. Si son iguales, detenemos
        # la ejecución aquí para no desperdiciar ciclos de CPU iterando diccionarios.
        if (len(zones) == len(added_zones) and
            len(tanks) == len(added_tanks) and
            len(pools) == len(added_pools) and
            len(mangueras) == len(added_mangueras) and
            len(riegos) == len(added_riegos)):
            return

        # 3. Iteramos sobre cada colección. Si encontramos un ID que no está en
        # nuestro registro (added_*), lo añadimos al registro y creamos su entidad.
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

        for riego_id, riego_data in riegos.items():
            if riego_id not in added_riegos:
                added_riegos.add(riego_id)
                new_entities.append(
                    HidromoticRiegoSwitch(coordinator, entry, riego_id, riego_data)
                )

        # Si descubrimos entidades nuevas, le decimos a Home Assistant que las registre
        if new_entities:
            async_add_entities(new_entities)

    # Llamada inicial al arrancar la integración
    async_add_switches()

    # Registramos un listener. Cada vez que el coordinador reciba datos nuevos por
    # WebSocket, se ejecutará async_add_switches por si hay hardware nuevo conectado.
    entry.async_on_unload(coordinator.async_add_listener(async_add_switches))

    # El interruptor de "Auto Riego" es global y estático, lo agregamos siempre
    async_add_entities([HidromoticAutoRiegoSwitch(coordinator, entry)])


class HidromoticBaseSwitch(CoordinatorEntity[HidromoticCoordinator], SwitchEntity):
    """Base representation of a generic Hidromotic output switch.

    Centraliza la lógica común (estado, disponibilidad, identificadores)
    para todos los tipos de salidas (zonas, tanques, mangueras, etc.).
    """

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
        """Initialize the generic switch."""
        super().__init__(coordinator)
        self._entity_id = entity_id
        self._entity_type = entity_type
        self._entry = entry

        # Genera un ID único e irrepetible para la base de datos de HA
        self._attr_unique_id = f"{entry.entry_id}_{entity_type}_{entity_id}"

        # Usa la etiqueta personalizada guardada en la controladora, o un nombre por defecto
        self._attr_name = entity_data.get("label") or default_name

        # Vincula esta entidad al dispositivo físico principal
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Hidromotic",
            model="CHI Smart Mini"
            if coordinator.client.data.get("is_mini")
            else "CHI Smart",
        )

    def _get_collection(self) -> dict[int, dict[str, Any]]:
        """Get the specific data collection dynamically based on the entity type.

        Usa un mapeo para saber a qué función del coordinador llamar
        dependiendo del tipo de entidad que sea esta instancia.
        """
        method_map = {
            "zone": self.coordinator.get_zones,
            "tank": self.coordinator.get_tanks,
            "pool": self.coordinator.get_pools,
            "manguera": self.coordinator.get_mangueras,
            "riego": self.coordinator.get_riegos,
        }
        return method_map[self._entity_type]()

    @property
    def available(self) -> bool:
        """Return True if the entity exists in the latest coordinator data."""
        return self._entity_id in self._get_collection() and super().available

    @property
    def is_on(self) -> bool:
        """Return True if the hardware reports this output as active (estado = 1)."""
        item = self._get_collection().get(self._entity_id)
        if item:
            return item.get("estado", 0) == STATE_ON
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes shared across all outputs."""
        item = self._get_collection().get(self._entity_id)
        if item:
            return {"slot_id": item.get("slot_id")}
        return {}


# -------------------------------------------------------------------
# Clases Específicas: Heredan de BaseSwitch y definen cómo encender/apagar
# -------------------------------------------------------------------

class HidromoticZoneSwitch(HidromoticBaseSwitch):
    """Representation of a Hidromotic flooding zone switch."""

    def __init__(self, coordinator, entry, zone_id, zone_data):
        super().__init__(coordinator, entry, zone_id, "zone", f"Zone {zone_id + 1}", zone_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Add zone-specific attributes (duration)."""
        attrs = super().extra_state_attributes
        item = self._get_collection().get(self._entity_id)
        if item:
            attrs["duration_minutes"] = item.get("duracion", 0)
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Tell the hardware to turn on this zone."""
        await self.coordinator.async_set_zone_state(self._entity_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Tell the hardware to turn off this zone."""
        await self.coordinator.async_set_zone_state(self._entity_id, False)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator, checking for disconnects."""
        if self._entity_id not in self._get_collection():
            _LOGGER.debug("Zone %d no longer available", self._entity_id)
        self.async_write_ha_state()


class HidromoticTankSwitch(HidromoticBaseSwitch):
    """Representation of a Hidromotic tank filling switch."""

    def __init__(self, coordinator, entry, tank_id, tank_data):
        super().__init__(coordinator, entry, tank_id, "tank", f"Tank {tank_id + 1}", tank_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Add tank-specific attributes (water level)."""
        attrs = super().extra_state_attributes
        item = self._get_collection().get(self._entity_id)
        if item:
            # Reutilizamos el método seguro del cliente para interpretar el nivel
            attrs["level"] = self.coordinator.client.get_tank_level(self._entity_id)
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Tell the hardware to start filling this tank."""
        await self.coordinator.async_set_tank_state(self._entity_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Tell the hardware to stop filling this tank."""
        await self.coordinator.async_set_tank_state(self._entity_id, False)


class HidromoticPoolSwitch(HidromoticBaseSwitch):
    """Representation of a Hidromotic Pool switch."""

    def __init__(self, coordinator, entry, pool_id, pool_data):
        super().__init__(coordinator, entry, pool_id, "pool", f"Pool {pool_id + 1}", pool_data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_pool_state(self._entity_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_pool_state(self._entity_id, False)


class HidromoticMangueraSwitch(HidromoticBaseSwitch):
    """Representation of a Hidromotic Hose (Manguera) switch."""

    def __init__(self, coordinator, entry, manguera_id, manguera_data):
        super().__init__(coordinator, entry, manguera_id, "manguera", f"Manguera {manguera_id + 1}", manguera_data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_manguera_state(self._entity_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_manguera_state(self._entity_id, False)


class HidromoticRiegoSwitch(HidromoticBaseSwitch):
    """Representation of a Hidromotic Irrigation program (Riego) switch."""

    def __init__(self, coordinator, entry, riego_id, riego_data):
        super().__init__(coordinator, entry, riego_id, "riego", f"Riego {riego_id + 1}", riego_data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_riego_state(self._entity_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_riego_state(self._entity_id, False)


# -------------------------------------------------------------------
# Switches Globales (No pertenecen a la colección de salidas dinámicas)
# -------------------------------------------------------------------

class HidromoticAutoRiegoSwitch(CoordinatorEntity[HidromoticCoordinator], SwitchEntity):
    """Representation of the global Auto Irrigation toggle.

    Esta entidad no usa HidromoticBaseSwitch porque no es una salida
    con slot_id, sino un ajuste general de la controladora.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._entry = entry

        self._attr_unique_id = f"{entry.entry_id}_auto_riego"
        self._attr_translation_key = "auto_riego"
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
        """Return true if global auto irrigation is enabled."""
        return self.coordinator.client.is_auto_riego_on()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable auto irrigation globally."""
        await self.coordinator.client.set_auto_riego(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable auto irrigation globally."""
        await self.coordinator.client.set_auto_riego(False)
