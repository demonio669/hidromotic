"""Switch platform for Hidromotic zones."""

from __future__ import annotations

import logging
from typing import Any

#from pyhidromotic import STATE_ON

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HidromoticConfigEntry
from .const import DOMAIN,STATE_ON
from .coordinator import HidromoticCoordinator


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HidromoticConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hidromotic switches from a config entry."""
    coordinator = entry.runtime_data

    # Track which zones and tanks we've added
    added_zones: set[int] = set()
    added_tanks: set[int] = set()
    added_pools: set[int] = set()
    added_mangueras: set[int] = set()

    @callback
    def async_add_switches() -> None:
        """Add switches for newly discovered zones and tanks."""
        new_entities: list[SwitchEntity] = []

        # Add zone switches
        zones = coordinator.get_zones()
        for zone_id, zone_data in zones.items():
            if zone_id not in added_zones:
                added_zones.add(zone_id)
                new_entities.append(
                    HidromoticZoneSwitch(coordinator, entry, zone_id, zone_data)
                )

        # Add tank switches
        tanks = coordinator.get_tanks()
        for tank_id, tank_data in tanks.items():
            if tank_id not in added_tanks:
                added_tanks.add(tank_id)
                new_entities.append(
                    HidromoticTankSwitch(coordinator, entry, tank_id, tank_data)
                )

        # Add pool switches
        pools = coordinator.get_pools()
        _LOGGER.debug("Pools: %s", pools)

        for pool_id, pool_data in pools.items():
            if pool_id not in added_pools:
                added_pools.add(pool_id)
                new_entities.append(
                    HidromoticPoolSwitch(coordinator, entry, pool_id, pool_data)
                )

        # Add manguera switches
        mangueras = coordinator.get_mangueras()
        _LOGGER.debug("Mangueras: %s", mangueras)

        for manguera_id, manguera_data in mangueras.items():
            if manguera_id not in added_mangueras:
                added_mangueras.add(manguera_id)
                new_entities.append(
                    HidromoticMangueraSwitch(coordinator, entry, manguera_id, manguera_data)
                )


        if new_entities:
            async_add_entities(new_entities)

    # Add initial zones and tanks
    async_add_switches()

    # Listen for updates to add new entities dynamically
    entry.async_on_unload(coordinator.async_add_listener(async_add_switches))

    # Add Auto Riego switch
    async_add_entities([HidromoticAutoRiegoSwitch(coordinator, entry)])


class HidromoticZoneSwitch(CoordinatorEntity[HidromoticCoordinator], SwitchEntity):
    """Representation of a Hidromotic zone switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        zone_id: int,
        zone_data: dict[str, Any],
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._entry = entry

        # Set unique ID based on device and zone
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone_id}"

        # Use custom label if available, otherwise default name
        self._attr_name = zone_data.get("label", f"Zone {zone_id + 1}")

        # Device info - all entities belong to one device
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
        """Return if entity is available."""
        zones = self.coordinator.get_zones()
        return self._zone_id in zones and super().available

    @property
    def is_on(self) -> bool:
        """Return true if the zone is active."""
        zones = self.coordinator.get_zones()
        zone = zones.get(self._zone_id)
        if zone:
            return zone.get("estado", 0) == STATE_ON
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        zones = self.coordinator.get_zones()
        zone = zones.get(self._zone_id)
        if zone:
            return {
                "duration_minutes": zone.get("duracion", 0),
                "slot_id": zone.get("slot_id"),
            }
        return {}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the zone (start irrigation)."""
        await self.coordinator.async_set_zone_state(self._zone_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the zone (stop irrigation)."""
        await self.coordinator.async_set_zone_state(self._zone_id, False)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Check if zone still exists
        zones = self.coordinator.get_zones()
        if self._zone_id not in zones:
            # Zone was disconnected - entity will show as unavailable
            _LOGGER.debug("Zone %d no longer available", self._zone_id)

        self.async_write_ha_state()


class HidromoticTankSwitch(CoordinatorEntity[HidromoticCoordinator], SwitchEntity):
    """Representation of a Hidromotic tank switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        tank_id: int,
        tank_data: dict[str, Any],
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._tank_id = tank_id
        self._entry = entry

        self._attr_unique_id = f"{entry.entry_id}_tank_{tank_id}"
        self._attr_name = tank_data.get("label") or f"Tank {tank_id + 1}"

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
        """Return if entity is available."""
        tanks = self.coordinator.get_tanks()
        return self._tank_id in tanks and super().available

    @property
    def is_on(self) -> bool:
        """Return true if the tank is filling."""
        tanks = self.coordinator.get_tanks()
        tank = tanks.get(self._tank_id)
        if tank:
            return tank.get("estado", 0) == STATE_ON
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        tanks = self.coordinator.get_tanks()
        tank = tanks.get(self._tank_id)
        if tank:
            return {
                "slot_id": tank.get("slot_id"),
                "level": tank.get("nivel"),
            }
        return {}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the tank (start filling)."""
        await self.coordinator.async_set_tank_state(self._tank_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the tank (stop filling)."""
        await self.coordinator.async_set_tank_state(self._tank_id, False)



class HidromoticPoolSwitch(CoordinatorEntity[HidromoticCoordinator], SwitchEntity):
    """Representation of a Hidromotic Pool switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        pool_id: int,
        pool_data: dict[str, Any],
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._pool_id = pool_id
        self._entry = entry

        self._attr_unique_id = f"{entry.entry_id}_pool_{pool_id}"
        self._attr_name = pool_data.get("label") or f"Pool {pool_id + 1}"

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
        """Return if entity is available."""
        pools = self.coordinator.get_pools()
        return self._pool_id in pools and super().available

    @property
    def is_on(self) -> bool:
        """Return true if the pool is filling."""
        pools = self.coordinator.get_pools()
        pool = pools.get(self._pool_id)
        if pool:
            return pool.get("estado", 0) == STATE_ON
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        pools = self.coordinator.get_pools()
        pool = pools.get(self._pool_id)
        if pool:
            return {
                "slot_id": pool.get("slot_id"),
                "level": pool.get("nivel"),
            }
        return {}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the pool (start filling)."""
        await self.coordinator.async_set_pool_state(self._pool_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the pool (stop filling)."""
        await self.coordinator.async_set_pool_state(self._pool_id, False)


class HidromoticMangueraSwitch(CoordinatorEntity[HidromoticCoordinator], SwitchEntity):
    """Representation of a Hidromotic Manguera switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HidromoticCoordinator,
        entry: HidromoticConfigEntry,
        manguera_id: int,
        manguera_data: dict[str, Any],
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._manguera_id = manguera_id
        self._entry = entry

        self._attr_unique_id = f"{entry.entry_id}_manguera_{manguera_id}"
        self._attr_name = manguera_data.get("label") or f"Manguera {manguera_id + 1}"

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
        """Return if entity is available."""
        mangueras = self.coordinator.get_mangueras()
        return self._manguera_id in mangueras and super().available

    @property
    def is_on(self) -> bool:
        """Return true if the manguera is filling."""
        mangueras = self.coordinator.get_mangueras()
        manguera = mangueras.get(self._manguera_id)
        if manguera:
            return manguera.get("estado", 0) == STATE_ON
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        mangueras = self.coordinator.get_mangueras()
        manguera = mangueras.get(self._manguera_id)
        if manguera:
            return {
                "slot_id": manguera.get("slot_id"),
                "level": manguera.get("nivel"),
            }
        return {}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the manguera (start filling)."""
        await self.coordinator.async_set_manguera_state(self._manguera_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the manguera (stop filling)."""
        await self.coordinator.async_set_manguera_state(self._manguera_id, False)





class HidromoticAutoRiegoSwitch(CoordinatorEntity[HidromoticCoordinator], SwitchEntity):
    """Representation of the Auto Riego switch."""

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
        self._attr_name = "Auto irrigation"  # Fallback name

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
        """Return true if auto riego is enabled."""
        return self.coordinator.client.is_auto_riego_on()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable auto riego."""
        await self.coordinator.client.set_auto_riego(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable auto riego."""
        await self.coordinator.client.set_auto_riego(False)
