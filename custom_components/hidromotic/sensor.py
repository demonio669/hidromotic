"""Sensor platform for Hidromotic tanks, pump, and system diagnostics."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTime
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

    entities: list[SensorEntity] = [
        HidromoticPumpSensor(coordinator, entry),
        HidromoticPumpMarchaSensor(coordinator, entry),
        HidromoticWifiSSIDSensor(coordinator, entry),
        HidromoticIPAddressSensor(coordinator, entry),
        HidromoticWifiSignalSensor(coordinator, entry),
        HidromoticWifiConnectedTimeSensor(coordinator, entry),
        HidromoticMacAddressSensor(coordinator, entry),
        HidromoticTypeSensor(coordinator, entry),
        HidromoticPicVersionSensor(coordinator, entry),
        HidromoticChipIDSensor(coordinator, entry),
        HidromoticPicDateSensor(coordinator, entry),
        HidromoticDeviceIdSensor(coordinator, entry),
        HidromoticEspVersionSensor(coordinator, entry),
        HidromoticOtaSensor(coordinator, entry),
        HidromoticBatterySensor(coordinator, entry),
        HidromoticUptimeSensor(coordinator, entry),
        HidromoticMessageCounterSensor(coordinator, entry),
        # RECOMENDACIÓN 6: Sensores para rastrear reinicios del chip
        HidromoticUartResetCountSensor(coordinator, entry),
        HidromoticEspResetCountSensor(coordinator, entry),
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


class HidromoticWifiSSIDSensor(HidromoticDiagnosticBaseSensor):
    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "wifi_ssid", "Red Wifi")

    @property
    def native_value(self) -> str:
        return self.coordinator.client.data.get("wifi_ssid", "unknown")


class HidromoticIPAddressSensor(HidromoticDiagnosticBaseSensor):
    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "ip_address", "IP")

    @property
    def native_value(self) -> str:
        return self.coordinator.client.data.get("wifi_ip", "unknown")


class HidromoticWifiSignalSensor(HidromoticDiagnosticBaseSensor):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.POWER_FACTOR
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "wifi_signal", "Nivel de señal")

    @property
    def native_value(self) -> int:
        return self.coordinator.client.data.get("wifi_signal", 0)


class HidromoticWifiConnectedTimeSensor(HidromoticDiagnosticBaseSensor):
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
    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "mac_address", "Mac addr")

    @property
    def native_value(self) -> str:
        return self.coordinator.client.data.get("mac", "unknown")


class HidromoticTypeSensor(HidromoticDiagnosticBaseSensor):
    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "device_type", "Tipo")

    @property
    def native_value(self) -> str:
        return self.coordinator.client.data.get("pic_name", "CHI Smart")


class HidromoticPicVersionSensor(HidromoticDiagnosticBaseSensor):
    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "pic_version", "Version PIC")

    @property
    def native_value(self) -> int | str:
        return self.coordinator.client.data.get("pic_version", "unknown")


class HidromoticChipIDSensor(HidromoticDiagnosticBaseSensor):
    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "chip_id", "Chip ID")

    @property
    def native_value(self) -> str:
        pic_id = self.coordinator.client.data.get("pic_id", "")
        rev = self.coordinator.client.data.get("pic_rev", "")
        return f"{pic_id}, {rev}" if pic_id else "unknown"


class HidromoticPicDateSensor(HidromoticDiagnosticBaseSensor):
    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "pic_fecha", "PIC Fecha")

    @property
    def native_value(self) -> str:
        return self.coordinator.client.data.get("pic_fecha", "unknown")


class HidromoticDeviceIdSensor(HidromoticDiagnosticBaseSensor):
    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "device_id", "ID del dispositivo")

    @property
    def native_value(self) -> str:
        return self.coordinator.client.data.get("device_id", "unknown")


class HidromoticEspVersionSensor(HidromoticDiagnosticBaseSensor):
    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "esp_version", "Vesion ESP")

    @property
    def native_value(self) -> str:
        return self.coordinator.client.data.get("fw_version_esp", "unknown")


class HidromoticOtaSensor(HidromoticDiagnosticBaseSensor):
    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "ota_status", "OTA")

    @property
    def native_value(self) -> str:
        return str(self.coordinator.client.data.get("ota", "unknown")).upper()


class HidromoticBatterySensor(HidromoticDiagnosticBaseSensor):
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
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "message_counter", "Contador de mensajes")

    @property
    def native_value(self) -> int:
        return self.coordinator.client.data.get("c_msg", 0)


# RECOMENDACIÓN 6: Implementación de sensores para UART Reset Count y ESP Reset Count
class HidromoticUartResetCountSensor(HidromoticDiagnosticBaseSensor):
    _attr_icon = "mdi:restart"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "uart_reset_count", "Reintentos UART")

    @property
    def native_value(self) -> int:
        return self.coordinator.client.data.get("uart_reset_count", 0)


class HidromoticEspResetCountSensor(HidromoticDiagnosticBaseSensor):
    _attr_icon = "mdi:chip"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: HidromoticCoordinator, entry: HidromoticConfigEntry) -> None:
        super().__init__(coordinator, entry, "esp_reset_count", "Reinicios ESP")

    @property
    def native_value(self) -> int:
        return self.coordinator.client.data.get("esp_reset_count", 0)


class HidromoticTankLevelSensor(CoordinatorEntity[HidromoticCoordinator], SensorEntity):
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
    def native_value(self) -> str:
        return self.coordinator.client.get_tank_level(self._tank_id)
