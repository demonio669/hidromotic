"""Binary sensor platform for Hidromotic tanks and physical inputs.

Este módulo se encarga de crear y actualizar las entidades de tipo 'binary_sensor'
para representar:
1. Sensores de estado de tanques (Lleno / Vacío).
2. Entradas físicas digitales de la placa (Detector de agua, Sensor de lluvia, etc.).
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

    # Conjuntos para rastrear qué componentes ya han sido añadidos
    # y evitar registros duplicados durante actualizaciones por WebSocket.
    added_tanks: set[int] = set()
    added_inputs: set[int] = set()

    @callback
    def async_add_binary_sensors() -> None:
        """Add sensors for newly discovered tanks and physical inputs."""
        new_entities: list[BinarySensorEntity] = []

        # ------------------------------------------------------------------
        # 1. Detección y Registro de Sensores Binarios de Tanques
        # ------------------------------------------------------------------
        tanks = coordinator.get_tanks()
        for tank_id, tank_data in tanks.items():
            if tank_id not in added_tanks:
                added_tanks.add(tank_id)
                # Se agregan ambas entidades (Lleno y Vacío) por cada tanque
                new_entities.append(
                    HidromoticTankFullSensor(coordinator, entry, tank_id, tank_data)
                )
                new_entities.append(
                    HidromoticTankEmptySensor(coordinator, entry, tank_id, tank_data)
                )

        # ------------------------------------------------------------------
        # 2. Detección y Registro de Entradas Físicas Digitales (E0 - E3)
        # ------------------------------------------------------------------
        inputs = coordinator.client.data.get("inputs", {})
        for input_id, input_data in inputs.items():
            # Solo creamos la entidad si la entrada física está configurada (tipo != 0)
            if input_id not in added_inputs and input_data.get("tipo", 0) != 0:
                added_inputs.add(input_id)
                new_entities.append(
                    HidromoticPhysicalInputSensor(coordinator, entry, input_id, input_data)
                )

        # Si hay nuevas entidades descubiertas, las registramos en Home Assistant
        if new_entities:
            async_add_entities(new_entities)

    # Registro inicial al cargar la integración
    async_add_binary_sensors()

    # Escuchamos actualizaciones del coordinador para detectar cambios en caliente
    entry.async_on_unload(coordinator.async_add_listener(async_add_binary_sensors))


# ===================================================================
# Clases Base e Implementación para Tanques de Agua
# ===================================================================

class HidromoticTankBaseBinarySensor(
    CoordinatorEntity[HidromoticCoordinator], BinarySensorEntity
):
    """Base representation of a Hidromotic tank binary sensor.

    Agrupa la lógica común de disponibilidad, atributos e información
    del dispositivo para los sensores binarios de tanque.
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

        base_label = tank_data.get("label") or f"Tanque {tank_id + 1}"

        # Identificador único en la base de datos de Home Assistant
        self._attr_unique_id = f"{entry.entry_id}_tank_{tank_id}_{sensor_type}"
        self._attr_name = f"{base_label} {name_suffix}"

        # Vinculación de la entidad con el dispositivo central
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

        Verifica que el tanque exista en la trama y que su lectura no marque error.
        """
        tanks = self.coordinator.get_tanks()
        tank = tanks.get(self._tank_id)
        if tank:
            nivel = tank.get("nivel", 0xFF)
            return nivel != 0xFF and nivel not in (2, 3) and super().available
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        tanks = self.coordinator.get_tanks()
        tank = tanks.get(self._tank_id)
        if tank:
            return {
                "level_raw": tank.get("nivel", 0xFF),
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
            coordinator, entry, tank_id, tank_data, sensor_type="full", name_suffix="Lleno"
        )

    @property
    def is_on(self) -> bool:
        """Return True if the tank level matches TANK_FULL."""
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
            coordinator, entry, tank_id, tank_data, sensor_type="empty", name_suffix="Vacío"
        )

    @property
    def is_on(self) -> bool:
        """Return True if the tank matches the configured empty condition."""
        tanks = self.coordinator.get_tanks()
        tank = tanks.get(self._tank_id)
        if tank:
            return tank.get("nivel", 0xFF) == TANK_FULL
        return False


# ===================================================================
# Implementación para Entradas Físicas Digitales (E0 - E3)
# ===================================================================

class HidromoticPhysicalInputSensor(
    CoordinatorEntity[HidromoticCoordinator], BinarySensorEntity
):
    """Representación de una entrada digital física del hardware (E1 - E4)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        input_id: int,
        input_data: dict[str, Any],
    ) -> None:
        """Initialize the physical input binary sensor."""
        super().__init__(coordinator)
        self._input_id = input_id
        self._entry = entry

        tipo_name = input_data.get("tipo_name", f"Entrada {input_id + 1}")
        self._attr_unique_id = f"{entry.entry_id}_input_{input_id}"
        self._attr_name = f"Entrada {input_id + 1} ({tipo_name})"

        # Asignación de clase de dispositivo estándar válida en Home Assistant
        tipo = input_data.get("tipo", 0)
        if tipo in (1, 2):  # Detector de agua (1) y Sensor de lluvia (2)
            self._attr_device_class = BinarySensorDeviceClass.MOISTURE
        elif tipo in (11, 12):  # Pausa externa
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        else:
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

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
        """Return True if the input exists in coordinator data."""
        inputs = self.coordinator.client.data.get("inputs", {})
        return self._input_id in inputs and super().available

    @property
    def is_on(self) -> bool:
        """Return True if physical input is active."""
        inputs = self.coordinator.client.data.get("inputs", {})
        inp = inputs.get(self._input_id)
        if inp:
            return inp.get("estado", False)
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        inputs = self.coordinator.client.data.get("inputs", {})
        inp = inputs.get(self._input_id, {})
        return {
            "input_id": self._input_id + 1,
            "tipo_id": inp.get("tipo"),
            "tipo_function": inp.get("tipo_name"),
            "inverted": inp.get("invert", False),
            "raw_state": inp.get("actual"),
        }
