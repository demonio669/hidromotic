"""Select platform for Hidromotic tank configuration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HidromoticConfigEntry
from .const import DOMAIN
from .coordinator import HidromoticCoordinator
from .entity_helpers import output_is_available, update_output_entity_visibility

TANK_MODES = ("Manual", "Automático")

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HidromoticConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up tank mode selectors from a config entry."""
    coordinator = entry.runtime_data
    added_tanks: set[int] = set()

    @callback
    def async_add_tank_modes() -> None:
        """Add mode selectors for newly discovered tanks."""
        new_entities: list[SelectEntity] = []
        for tank_id, tank_data in coordinator.get_tanks().items():
            unique_id = f"{entry.entry_id}_tank_{tank_id}_mode"
            available = output_is_available(tank_data)
            update_output_entity_visibility(hass, "select", unique_id, available)
            if available and tank_id not in added_tanks:
                added_tanks.add(tank_id)
                new_entities.append(
                    HidromoticTankModeSelect(coordinator, entry, tank_id, tank_data)
                )

        if new_entities:
            async_add_entities(new_entities)

    async_add_tank_modes()
    entry.async_on_unload(coordinator.async_add_listener(async_add_tank_modes))


class HidromoticTankModeSelect(
    CoordinatorEntity[HidromoticCoordinator], SelectEntity
):
    """Select automatic or manual mode for a Hidromotic tank."""

    _attr_has_entity_name = True
    _attr_options = list(TANK_MODES)
    _attr_icon = "mdi:autorenew"

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        tank_id: int,
        tank_data: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._tank_id = tank_id
        self._attr_unique_id = f"{entry.entry_id}_tank_{tank_id}_mode"
        base_label = tank_data.get("label") or f"Tanque {tank_id + 1}"
        self._attr_name = f"{base_label} Modo"
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
        tank = self.coordinator.get_tanks().get(self._tank_id)
        return (
            tank is not None
            and output_is_available(tank)
            and tank.get("tipo_flotante", 0) != 0
            and super().available
        )

    @property
    def current_option(self) -> str | None:
        tank = self.coordinator.get_tanks().get(self._tank_id)
        if tank is None:
            return None
        return "Automático" if tank.get("modo", 0) else "Manual"

    async def async_select_option(self, option: str) -> None:
        if option not in TANK_MODES:
            raise ValueError(f"Unsupported tank mode: {option}")
        await self.coordinator.async_set_tank_mode(
            self._tank_id, option == "Automático"
        )
