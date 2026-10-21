"""Sensor platform for Hidromotic tanks, pump, and system diagnostics.

Este módulo gestiona la creación y actualización de todas las entidades de tipo 'sensor'
del sistema Hidromotic en Home Assistant.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HidromoticConfigEntry
from .const import DOMAIN, PUMP_NO_WATER, PUMP_OFF, PUMP_ON, PUMP_RECOVERY
from .coordinator import HidromoticCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HidromoticConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hidromotic sensors from a config entry."""
    coordinator = entry.runtime_data

    # Registro de todas las entidades de diagnóstico y sistema requeridas
    entities: list[SensorEntity] = [
        # Bomba
        HidromoticPumpSensor(coordinator, entry),
        HidromoticPumpMarchaSensor(coordinator, entry),
        # Red & Conectividad
        HidromoticWifiSSIDSensor(coordinator, entry),
        HidromoticIPAddressSensor(coordinator, entry),
        HidromoticWifiSignalSensor(coordinator, entry),
        HidromoticWifiConnectedTimeSensor(coordinator, entry),
        HidromoticMacAddressSensor(coordinator, entry),
        # Hardware & Firmware
        HidromoticTypeSensor(coordinator, entry),
        HidromoticPicVersionSensor(coordinator, entry),
        HidromoticChipIDSensor(coordinator, entry),
        HidromoticPicDateSensor(coordinator, entry),
        HidromoticDeviceIdSensor(coordinator, entry),
        HidromoticEspVersionSensor(coordinator, entry),
        HidromoticOtaSensor(coordinator, entry),
        # Estado & Diagnóstico
        HidromoticBatterySensor(coordinator, entry),
        HidromoticUptimeSensor(coordinator, entry),
        HidromoticMessageCounterSensor(coordinator, entry),
    ]

    added_tanks: set[int] = set()

    @callback
    def async_add_tank_sensors() -> None:
        """Add sensors for newly discovered tanks."""
        tanks = coordinator.get_tanks()
        new_entities: list[SensorEntity] = []

        for tank_id, tank_data in tanks.items():
            if tank_id not in added_tanks:
                added_tanks.add(tank_id)
                new_entities.append(
                    HidromoticTankLevelSensor(coordinator, entry, tank_id, tank_data)
                )

        if new_entities:
            async_add_entities(new_entities)

    async_add_entities(entities)
    async_add_tank_sensors()

    entry.async_on_unload(coordinator.async_add_listener(async_add_tank_sensors))


# ===================================================================
# Clase Base de Diagnóstico
# ===================================================================

class HidromoticDiagnosticBaseSensor(
    CoordinatorEntity[HidromoticCoordinator], SensorEntity
):
    """Clase base para todos los sensores de diagnóstico del sistema."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        sensor_type: str,
        name: str,
    ) -> None:
        """Inicializa el sensor de diagnóstico."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Hidromotic",
            model="CHI Smart Mini"
            if coordinator.client.data.get("is_mini")
            else "CHI Smart",
        )


# ===================================================================
# Sensores de Bomba
# ===================================================================

class HidromoticPumpSensor(CoordinatorEntity[HidromoticCoordinator], SensorEntity):
    """Sensor para el estado general de la bomba."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:pump"

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_pump_status"
        self._attr_name = "Estado de bomba"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Hidromotic",
            model="CHI Smart Mini"
            if coordinator.client.data.get("is_mini")
            else "CHI Smart",
        )

    @property
    def native_value(self) -> str:
        pump = self.coordinator.get_pump()
        estado = pump.get("estado", 0)
        status_map = {
            PUMP_OFF: "off",
            PUMP_ON: "on",
            PUMP_RECOVERY: "recovery",
            PUMP_NO_WATER: "no_water",
        }
        return status_map.get(estado, f"unknown_{estado}")


class HidromoticPumpMarchaSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'Bomba Marcha' (minutos)."""

    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "pump_marcha", "Bomba Marcha")

    @property
    def native_value(self) -> int:
        return self.coordinator.get_pump().get("marcha", 0)


# ===================================================================
# Sensores de Red & Conectividad
# ===================================================================

class HidromoticWifiSSIDSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'Red Wifi'."""

    _attr_icon = "mdi:wifi"

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "wifi_ssid", "Red Wifi")

    @property
    def native_value(self) -> str:
        return self.coordinator.client.data.get("wifi_ssid", "unknown")


class HidromoticIPAddressSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'IP'."""

    _attr_icon = "mdi:ip-network"

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "ip_address", "IP")

    @property
    def native_value(self) -> str:
        return self.coordinator.client.data.get("wifi_ip", "unknown")


class HidromoticWifiSignalSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'Nivel de señal' (%)."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.POWER_FACTOR
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "wifi_signal", "Nivel de señal")

    @property
    def native_value(self) -> int:
        return self.coordinator.client.data.get("wifi_signal", 0)


class HidromoticWifiConnectedTimeSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'Tiempo conectado' WiFi."""

    _attr_icon = "mdi:wifi-clock"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "wifi_connected_time", "Tiempo conectado")

    @property
    def native_value(self) -> int:
        return self.coordinator.client.data.get("wifi_routertime", 0)


class HidromoticMacAddressSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'Mac addr'."""

    _attr_icon = "mdi:network"

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "mac_address", "Mac addr")

    @property
    def native_value(self) -> str:
        return self.coordinator.client.data.get("mac", "unknown")


# ===================================================================
# Sensores de Hardware & Firmware
# ===================================================================

class HidromoticTypeSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'Tipo' (CHI Smart / CHI Smart Mini)."""

    _attr_icon = "mdi:microcontroller"

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "device_type", "Tipo")

    @property
    def native_value(self) -> str:
        return self.coordinator.client.data.get("pic_name", "CHI Smart")


class HidromoticPicVersionSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'Version PIC'."""

    _attr_icon = "mdi:chip"

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "pic_version", "Version PIC")

    @property
    def native_value(self) -> int | str:
        return self.coordinator.client.data.get("pic_version", "unknown")


class HidromoticChipIDSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'Chip ID'."""

    _attr_icon = "mdi:identifier"

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "chip_id", "Chip ID")

    @property
    def native_value(self) -> str:
        pic_id = self.coordinator.client.data.get("pic_id", "")
        rev = self.coordinator.client.data.get("pic_rev", "")
        return f"{pic_id}, {rev}" if pic_id else "unknown"


class HidromoticPicDateSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'PIC Fecha'."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "pic_fecha", "PIC Fecha")

    @property
    def native_value(self) -> str:
        return self.coordinator.client.data.get("pic_fecha", "unknown")


class HidromoticDeviceIdSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'ID del dispositivo'."""

    _attr_icon = "mdi:badge-account-horizontal"

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "device_id", "ID del dispositivo")

    @property
    def native_value(self) -> str:
        return self.coordinator.client.data.get("device_id", "unknown")


class HidromoticEspVersionSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'Vesion ESP'."""

    _attr_icon = "mdi:memory"

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "esp_version", "Vesion ESP")

    @property
    def native_value(self) -> str:
        return self.coordinator.client.data.get("fw_version_esp", "unknown")


class HidromoticOtaSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'OTA'."""

    _attr_icon = "mdi:cloud-upload"

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "ota_status", "OTA")

    @property
    def native_value(self) -> str:
        return str(self.coordinator.client.data.get("ota", "unknown")).upper()


# ===================================================================
# Sensores de Estado General
# ===================================================================

class HidromoticBatterySensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'Batería' (%)."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "battery", "Batería")

    @property
    def native_value(self) -> int | None:
        bateria = self.coordinator.client.data.get("bateria")
        if bateria is None or bateria == 0:
            return None
        return min(bateria, 100)


class HidromoticUptimeSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'Tiempo Energizado' (segundos)."""

    _attr_icon = "mdi:clock-start"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "uptime", "Tiempo Energizado")

    @property
    def native_value(self) -> int:
        return self.coordinator.client.data.get("uptime", 0)


class HidromoticMessageCounterSensor(HidromoticDiagnosticBaseSensor):
    """Sensor 'Contador de mensajes'."""

    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "message_counter", "Contador de mensajes")

    @property
    def native_value(self) -> int:
        return self.coordinator.client.data.get("c_msg", 0)


# ===================================================================
# Sensores de Tanque
# ===================================================================

class HidromoticTankLevelSensor(CoordinatorEntity[HidromoticCoordinator], SensorEntity):
    """Sensor para el nivel del tanque de agua."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:water-percent"

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        tank_id: int,
        tank_data: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._tank_id = tank_id
        self._entry = entry

        self._attr_unique_id = f"{entry.entry_id}_tank_{tank_id}_level"
        self._attr_translation_key = "tank_level"

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
        tanks = self.coordinator.get_tanks()
        return self._tank_id in tanks and super().available

    @property
    def native_value(self) -> str:
        return self.coordinator.client.get_tank_level(self._tank_id)

    @property
    def icon(self) -> str:
        value = self.native_value
        if value == "full":
            return "mdi:water"
        if value == "empty":
            return "mdi:water-off"
        if value == "medium":
            return "mdi:water-percent"
        if value in ("sensor_fail", "level_fail"):
            return "mdi:water-alert"
        return "mdi:water-percent"
