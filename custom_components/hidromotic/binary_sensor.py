"""Binary sensor platform for Hidromotic tanks.

Este módulo gestiona la creación y actualización de los sensores binarios
(lleno y vacío) asociados a los tanques de agua del sistema Hidromotic.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HidromoticConfigEntry
from .const import DOMAIN, TANK_EMPTY, TANK_FULL
from .coordinator import HidromoticCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HidromoticConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hidromotic binary sensors from a config entry."""
    coordinator = entry.runtime_data

    # Conjunto para rastrear qué tanques ya han sido agregados a Home Assistant
    # y evitar registros duplicados durante las actualizaciones dinámicas.
    added_tanks: set[int] = set()

    @callback
    def async_add_tank_sensors() -> None:
        """Add sensors for newly discovered tanks."""
        tanks = coordinator.get_tanks()
        new_entities = []

        for tank_id, tank_data in tanks.items():
            if tank_id not in added_tanks:
                added_tanks.add(tank_id)
                # Creamos ambas entidades (Lleno y Vacío) para cada tanque descubierto
                new_entities.append(
                    HidromoticTankFullSensor(coordinator, entry, tank_id, tank_data)
                )
                new_entities.append(
                    HidromoticTankEmptySensor(coordinator, entry, tank_id, tank_data)
                )

        # Si se descubrieron tanques nuevos, se registran en Home Assistant
        if new_entities:
            async_add_entities(new_entities)

    # Registro de tanques iniciales al cargar la integración
    async_add_tank_sensors()

    # Listener que se ejecuta cada vez que el coordinador recibe datos nuevos vía WebSocket
    entry.async_on_unload(coordinator.async_add_listener(async_add_tank_sensors))


class HidromoticTankBaseBinarySensor(
    CoordinatorEntity[HidromoticCoordinator], BinarySensorEntity
):
    """Base representation of a Hidromotic tank binary sensor.

    Esta clase base abstracta agrupa la configuración común (disponibilidad,
    atributos extendidos e información de dispositivo) para evitar duplicar código.
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        tank_id: int,
        tank_data: dict[str, Any],
        sensor_type: str,
        name_suffix: str,
    ) -> None:
        """Initialize the base binary sensor."""
        super().__init__(coordinator)
        self._tank_id = tank_id
        self._entry = entry

        base_label = tank_data.get("label", f"Tank {tank_id + 1}")

        # Identificador único en la base de datos de Home Assistant
        self._attr_unique_id = f"{entry.entry_id}_tank_{tank_id}_{sensor_type}"
        self._attr_name = f"{base_label} {name_suffix}"

        # Vinculación de la entidad al dispositivo físico de Hidromotic
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
        """Return True if the entity is available.

        El sensor estará disponible si el tanque existe en los datos del coordinador
        y su nivel no presenta errores de lectura del sensor físico (2 o 3).
        """
        tanks = self.coordinator.get_tanks()
        tank = tanks.get(self._tank_id)
        if tank:
            nivel = tank.get("nivel", 0xFF)
            return nivel != 0xFF and nivel not in (2, 3) and super().available
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes.

        Expone el valor entero nativo del nivel ('level_raw') y la traducción
        legible obtenida directamente a través del cliente ('level').
        """
        tanks = self.coordinator.get_tanks()
        tank = tanks.get(self._tank_id)
        if tank:
            return {
                "level_raw": tank.get("nivel", 0xFF),
                # Reutilizamos la función auxiliar del cliente para mantener coherencia
                "level": self.coordinator.client.get_tank_level(self._tank_id),
            }
        return {}


class HidromoticTankFullSensor(HidromoticTankBaseBinarySensor):
    """Binary sensor for tank full status."""

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        tank_id: int,
        tank_data: dict[str, Any],
    ) -> None:
        """Initialize the full sensor."""
        super().__init__(
            coordinator, entry, tank_id, tank_data, sensor_type="full", name_suffix="Full"
        )

    @property
    def is_on(self) -> bool:
        """Return True if the tank is full (nivel == TANK_FULL)."""
        tanks = self.coordinator.get_tanks()
        tank = tanks.get(self._tank_id)
        if tank:
            return tank.get("nivel", 0xFF) == TANK_FULL
        return False


class HidromoticTankEmptySensor(HidromoticTankBaseBinarySensor):
    """Binary sensor for tank empty status."""

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        tank_id: int,
        tank_data: dict[str, Any],
    ) -> None:
        """Initialize the empty sensor."""
        super().__init__(
            coordinator, entry, tank_id, tank_data, sensor_type="empty", name_suffix="Empty"
        )

    @property
    def is_on(self) -> bool:
        """Return True if the tank matches the configured empty threshold state."""
        tanks = self.coordinator.get_tanks()
        tank = tanks.get(self._tank_id)
        if tank:
            return tank.get("nivel", 0xFF) == TANK_FULL
        return False
