"""Button platform for Hidromotic device actions (Reboot)."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HidromoticConfigEntry
from .const import DOMAIN
from .coordinator import HidromoticCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HidromoticConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hidromotic button entities."""
    coordinator = entry.runtime_data
    async_add_entities([HidromoticRebootButton(coordinator, entry)])


class HidromoticRebootButton(ButtonEntity):
    """Entidad de botón para reiniciar la controladora Hidromotic."""

    _attr_has_entity_name = True
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:restart"

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
    ) -> None:
        """Inicializa el botón de reinicio."""
        self._coordinator = coordinator
        self._entry = entry

        self._attr_unique_id = f"{entry.entry_id}_reboot_button"
        self._attr_name = "Reiniciar Dispositivo"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Hidromotic",
            model="CHI Smart Mini"
            if coordinator.client.data.get("is_mini")
            else "CHI Smart",
        )

    async def async_press(self) -> None:
        """Ejecuta la acción de reinicio al presionar el botón."""
        await self._coordinator.client.reboot_device()
