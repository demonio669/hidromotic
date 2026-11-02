"""Tests for hiding and dynamically adding disabled CHI outputs."""

import unittest
from unittest.mock import MagicMock, patch

from homeassistant.helpers.entity_registry import RegistryEntryHider

from custom_components.hidromotic import number, sensor, switch
from custom_components.hidromotic.entity_helpers import (
    output_is_available,
    update_output_entity_visibility,
)


class HidromoticEntityVisibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.hass = MagicMock()
        self.entry = MagicMock()
        self.entry.entry_id = "entry-1"
        self.entry.title = "CHI"
        self.entry.async_on_unload = MagicMock()
        self.coordinator = MagicMock()
        self.entry.runtime_data = self.coordinator
        self.coordinator.async_add_listener = MagicMock(return_value=MagicMock())
        self.coordinator.client.data = {"is_mini": True}
        self.registry = MagicMock()
        self.registry.async_get_entity_id.return_value = None
        self.registry.async_get.return_value = None
        self.registry_patch = patch(
            "custom_components.hidromotic.entity_helpers.er.async_get",
            return_value=self.registry,
        )
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)

    def test_output_availability_uses_disabled_state(self) -> None:
        self.assertFalse(output_is_available(None))
        self.assertFalse(output_is_available({"estado": 7}))
        self.assertTrue(output_is_available({"estado": 0}))

    def test_registry_visibility_preserves_user_hidden_setting(self) -> None:
        self.registry.async_get_entity_id.return_value = "switch.chi_zone_1"
        registry_entry = MagicMock(hidden_by=None)
        self.registry.async_get.return_value = registry_entry

        update_output_entity_visibility(self.hass, "switch", "entry-1_zone_0", False)
        self.registry.async_update_entity.assert_called_once_with(
            "switch.chi_zone_1", hidden_by=RegistryEntryHider.INTEGRATION
        )

        registry_entry.hidden_by = RegistryEntryHider.INTEGRATION
        update_output_entity_visibility(self.hass, "switch", "entry-1_zone_0", True)
        self.registry.async_update_entity.assert_called_with(
            "switch.chi_zone_1", hidden_by=None
        )

        registry_entry.hidden_by = RegistryEntryHider.USER
        self.registry.async_update_entity.reset_mock()
        update_output_entity_visibility(self.hass, "switch", "entry-1_zone_0", True)
        self.registry.async_update_entity.assert_not_called()

    async def test_switches_skip_disabled_outputs_and_add_them_when_enabled(self) -> None:
        zones = {0: {"estado": 7}, 1: {"estado": 0}}
        self.coordinator.get_zones.return_value = zones
        self.coordinator.get_tanks.return_value = {}
        self.coordinator.get_pools.return_value = {}
        self.coordinator.get_mangueras.return_value = {}
        self.coordinator.get_ciclon.return_value = {}
        self.coordinator.get_riegos.return_value = {}
        add_entities = MagicMock()

        with patch(
            "custom_components.hidromotic.switch.HidromoticZoneSwitch"
        ) as zone_switch, patch(
            "custom_components.hidromotic.switch.HidromoticAutoRiegoSwitch"
        ):
            await switch.async_setup_entry(self.hass, self.entry, add_entities)

            self.assertEqual(
                [call.args[2] for call in zone_switch.call_args_list],
                [1],
            )
            zones[0]["estado"] = 0
            self.coordinator.async_add_listener.call_args.args[0]()

            self.assertEqual(
                [call.args[2] for call in zone_switch.call_args_list],
                [1, 0],
            )

    async def test_duration_controls_skip_disabled_outputs_until_enabled(self) -> None:
        zones = {0: {"estado": 7}}
        pools = {0: {"estado": 7}}
        self.coordinator.get_zones.return_value = zones
        self.coordinator.get_pools.return_value = pools
        add_entities = MagicMock()

        with patch(
            "custom_components.hidromotic.number.HidromoticZoneDurationNumber"
        ) as zone_number, patch(
            "custom_components.hidromotic.number.HidromoticPoolDurationNumber"
        ) as pool_number:
            await number.async_setup_entry(self.hass, self.entry, add_entities)

            zone_number.assert_not_called()
            pool_number.assert_not_called()
            zones[0]["estado"] = 0
            pools[0]["estado"] = 0
            self.coordinator.async_add_listener.call_args.args[0]()

            zone_number.assert_called_once()
            pool_number.assert_called_once()

    async def test_tank_sensors_skip_disabled_tanks_until_enabled(self) -> None:
        tanks = {0: {"estado": 7}, 1: {"estado": 0}}
        self.coordinator.get_tanks.return_value = tanks
        add_entities = MagicMock()

        with patch(
            "custom_components.hidromotic.sensor.HidromoticTankLevelSensor"
        ) as level_sensor, patch(
            "custom_components.hidromotic.sensor.HidromoticTankEmptyStateSensor"
        ) as empty_sensor, patch(
            "custom_components.hidromotic.sensor.HidromoticTankFullStateSensor"
        ) as full_sensor:
            await sensor.async_setup_entry(self.hass, self.entry, add_entities)

            self.assertEqual(level_sensor.call_count, 1)
            self.assertEqual(empty_sensor.call_count, 1)
            self.assertEqual(full_sensor.call_count, 1)
            tanks[0]["estado"] = 0
            self.coordinator.async_add_listener.call_args.args[0]()

            self.assertEqual(level_sensor.call_count, 2)
            self.assertEqual(empty_sensor.call_count, 2)
            self.assertEqual(full_sensor.call_count, 2)
