"""Tests for Hidromotic entity platforms and entity behavior."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.hidromotic import (
    binary_sensor,
    button,
    number,
    select,
    sensor,
    switch,
)


class HidromoticEntityPlatformTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.entry = MagicMock()
        self.entry.entry_id = "entry-1"
        self.entry.title = "CHI"
        self.entry.async_on_unload = MagicMock()
        self.coordinator = MagicMock()
        self.entry.runtime_data = self.coordinator
        self.coordinator.client.data = {"is_mini": True}
        self.coordinator.client.get_tank_level.return_value = "full"
        self.coordinator.client.is_lluvia_bloqueado.return_value = True
        self.coordinator.client.is_auto_riego_on.return_value = True
        self.coordinator.client.reboot_device = AsyncMock()
        self.coordinator.client.set_output_duration = AsyncMock()
        self.coordinator.async_set_tank_mode = AsyncMock()
        self.coordinator.client.set_auto_riego = AsyncMock()
        for method in (
            "async_set_zone_state",
            "async_set_tank_state",
            "async_set_pool_state",
            "async_set_manguera_state",
            "async_set_ciclon_state",
            "async_set_riego_state",
        ):
            setattr(self.coordinator, method, AsyncMock())

    async def test_switch_entities_report_state_and_forward_commands(self) -> None:
        collections = {
            "zones": {0: {"slot_id": 1, "estado": 1, "duracion": 12}},
            "tanks": {0: {"slot_id": 2, "estado": 0, "duracion": 20, "nivel": 1}},
            "pools": {0: {"slot_id": 3, "estado": 0, "duracion": 30}},
            "mangueras": {0: {"slot_id": 4, "estado": 0}},
            "ciclon": {
                0: {
                    "slot_id": 5,
                    "estado": 0,
                    "modo_ante_tareas": 1,
                    "modo_fin_de_tareas": 2,
                    "modo_tiempo": 1,
                    "proximo_ciclon": 90,
                }
            },
            "riegos": {0: {"slot_id": 6, "estado": 0}},
        }
        for name, value in collections.items():
            getattr(self.coordinator, f"get_{name}").return_value = value

        zone = switch.HidromoticZoneSwitch(self.coordinator, self.entry, 0, collections["zones"][0])
        tank = switch.HidromoticTankSwitch(self.coordinator, self.entry, 0, collections["tanks"][0])
        pool = switch.HidromoticPoolSwitch(self.coordinator, self.entry, 0, collections["pools"][0])
        hose = switch.HidromoticMangueraSwitch(
            self.coordinator, self.entry, 0, collections["mangueras"][0]
        )
        cyclone = switch.HidromoticCiclonSwitch(
            self.coordinator, self.entry, 0, collections["ciclon"][0]
        )
        irrigation = switch.HidromoticRiegoSwitch(
            self.coordinator, self.entry, 0, collections["riegos"][0]
        )
        automatic = switch.HidromoticAutoRiegoSwitch(self.coordinator, self.entry)

        self.assertTrue(zone.is_on)
        self.assertTrue(zone.available)
        self.assertEqual(zone.extra_state_attributes["duration_minutes"], 12)
        self.assertEqual(tank.extra_state_attributes["level"], "full")
        self.assertEqual(tank.extra_state_attributes["mode"], "manual")
        self.assertEqual(pool.extra_state_attributes["duration_minutes"], 30)
        self.assertEqual(hose.extra_state_attributes, {"slot_id": 4})
        self.assertEqual(cyclone.extra_state_attributes["proximo_ciclon_seg"], 90)
        self.assertFalse(irrigation.is_on)
        self.assertTrue(automatic.is_on)

        for entity in (zone, tank, pool, hose, cyclone, irrigation):
            await entity.async_turn_on()
            await entity.async_turn_off()
        await automatic.async_turn_on()
        await automatic.async_turn_off()

        for method in (
            "async_set_zone_state",
            "async_set_tank_state",
            "async_set_pool_state",
            "async_set_manguera_state",
            "async_set_ciclon_state",
            "async_set_riego_state",
        ):
            handler = getattr(self.coordinator, method)
            self.assertEqual(handler.await_count, 2)
        self.coordinator.client.set_auto_riego.assert_has_awaits(
            [unittest.mock.call(True), unittest.mock.call(False)]
        )

    async def test_number_entities_report_values_and_send_changes(self) -> None:
        self.coordinator.get_pools.return_value = {
            0: {"slot_id": 1, "estado": 0, "duracion": 40}
        }
        self.coordinator.get_zones.return_value = {
            0: {"slot_id": 2, "estado": 0, "duracion": 50}
        }
        pool = number.HidromoticPoolDurationNumber(
            self.coordinator, self.entry, 0, self.coordinator.get_pools.return_value[0]
        )
        zone = number.HidromoticZoneDurationNumber(
            self.coordinator, self.entry, 0, self.coordinator.get_zones.return_value[0]
        )

        self.assertTrue(pool.available)
        self.assertTrue(zone.available)
        self.assertEqual(pool.native_value, 40.0)
        self.assertEqual(zone.native_value, 50.0)
        await pool.async_set_native_value(41.8)
        await zone.async_set_native_value(51.8)

        self.coordinator.client.set_output_duration.assert_has_awaits(
            [
                unittest.mock.call("pools", 0, 41),
                unittest.mock.call("zones", 0, 51),
            ]
        )

    async def test_tank_duration_number_reads_writes_and_tracks_availability(self) -> None:
        tank = {"slot_id": 3, "estado": 0, "duracion": 45}
        self.coordinator.get_tanks.return_value = {0: tank}
        entity = number.HidromoticTankDurationNumber(
            self.coordinator, self.entry, 0, tank
        )

        self.assertTrue(entity.available)
        self.assertEqual(entity.native_value, 45.0)
        await entity.async_set_native_value(50)
        self.coordinator.client.set_output_duration.assert_awaited_once_with(
            "tanks", 0, 50
        )

        tank["estado"] = 7
        self.assertFalse(entity.available)
        self.coordinator.get_tanks.return_value = {}
        self.assertIsNone(entity.native_value)
        self.assertFalse(entity.available)

    async def test_tank_mode_select_reports_and_updates_mode(self) -> None:
        tank = {
            "estado": 0,
            "modo": 1,
            "tipo_flotante": 1,
            "label": "Cisterna",
        }
        self.coordinator.get_tanks.return_value = {0: tank}
        entity = select.HidromoticTankModeSelect(
            self.coordinator, self.entry, 0, tank
        )

        self.assertEqual(entity.options, ["Manual", "Automático"])
        self.assertEqual(entity.current_option, "Automático")
        self.assertTrue(entity.available)
        await entity.async_select_option("Manual")
        self.coordinator.async_set_tank_mode.assert_awaited_once_with(0, False)

        tank["modo"] = 0
        self.assertEqual(entity.current_option, "Manual")
        tank["tipo_flotante"] = 0
        self.assertFalse(entity.available)
        with self.assertRaises(ValueError):
            await entity.async_select_option("Invalid")

        self.coordinator.get_tanks.return_value = {}
        self.assertIsNone(entity.current_option)

    async def test_tank_sensors_report_values_and_availability(self) -> None:
        self.coordinator.get_tanks.return_value = {
            0: {"estado": 0, "nivel": 0, "label": "Cisterna"}
        }
        data = self.coordinator.get_tanks.return_value[0]
        level = sensor.HidromoticTankLevelSensor(self.coordinator, self.entry, 0, data)
        empty = sensor.HidromoticTankEmptyStateSensor(self.coordinator, self.entry, 0, data)
        full = sensor.HidromoticTankFullStateSensor(self.coordinator, self.entry, 0, data)
        tank_binary = binary_sensor.HidromoticTankBaseBinarySensor(
            self.coordinator, self.entry, 0, data, "empty", "Vacío"
        )

        self.assertTrue(level.available)
        self.assertEqual(level.native_value, "full")
        self.assertTrue(empty.available)
        self.assertEqual(empty.native_value, "false")
        self.assertEqual(full.native_value, "true")
        self.assertTrue(tank_binary.available)

        data["nivel"] = 1
        self.coordinator.client.get_tank_level.return_value = "empty"
        self.assertEqual(level.native_value, "empty")
        self.assertEqual(empty.native_value, "true")
        self.assertEqual(full.native_value, "false")

        data["estado"] = 7
        self.assertFalse(level.available)
        self.assertFalse(empty.available)
        self.assertFalse(tank_binary.available)
        data["estado"] = 0
        for unavailable_level in (2, 3, 0xFF):
            data["nivel"] = unavailable_level
            self.assertFalse(tank_binary.available)

        data["nivel"] = 0
        self.coordinator.client.data["inputs"] = {}
        self.assertFalse(
            binary_sensor.HidromoticPhysicalInputSensor(
                self.coordinator, self.entry, 99, {"tipo": 12}
            ).is_on
        )

    async def test_diagnostic_sensors_expose_values_and_defaults(self) -> None:
        self.coordinator.client.data = {
            "is_mini": True,
            "wifi_ssid": "garden",
            "wifi_ip": "192.0.2.2",
            "wifi_signal": 75,
            "wifi_routertime": 33,
            "wifi_sntp": "SI",
            "wifi_dhcp": "Dynamic",
            "wifi_gateway": "192.0.2.1",
            "mqtt_connected_time": 11756,
            "mg_version": "2.19.1",
            "active_slot": 0,
            "ram_free": 35476,
            "ram_min_free": 11704,
            "wifi_ap_ssid": "CHI3_C985AB",
            "wifi_ap_ip": "192.0.4.1",
            "mac": "AA:BB:CC:DD:EE:FF",
            "pic_name": "CHI Smart Mini",
            "pic_version": 12,
            "pic_id": "0x42",
            "pic_rev": 3,
            "pic_fecha": "2026-01-02",
            "device_id": "device-1",
            "fw_version_esp": "1.2.3",
            "ota": "ready",
            "bateria": 120,
            "uptime": 300,
            "c_msg": 17,
            "uart_reset_count": 4,
            "esp_reset_count": 5,
        }
        self.coordinator.get_pump.return_value = {"estado": 1, "marcha": 10}
        entities = [
            sensor.HidromoticPumpSensor(self.coordinator, self.entry),
            sensor.HidromoticPumpMarchaSensor(self.coordinator, self.entry),
            sensor.HidromoticWifiSSIDSensor(self.coordinator, self.entry),
            sensor.HidromoticIPAddressSensor(self.coordinator, self.entry),
            sensor.HidromoticWifiSignalSensor(self.coordinator, self.entry),
            sensor.HidromoticWifiConnectedTimeSensor(self.coordinator, self.entry),
            sensor.HidromoticWifiSntpSensor(self.coordinator, self.entry),
            sensor.HidromoticWifiDhcpSensor(self.coordinator, self.entry),
            sensor.HidromoticWifiGatewaySensor(self.coordinator, self.entry),
            sensor.HidromoticMqttConnectedTimeSensor(self.coordinator, self.entry),
            sensor.HidromoticMacAddressSensor(self.coordinator, self.entry),
            sensor.HidromoticTypeSensor(self.coordinator, self.entry),
            sensor.HidromoticPicVersionSensor(self.coordinator, self.entry),
            sensor.HidromoticChipIDSensor(self.coordinator, self.entry),
            sensor.HidromoticPicDateSensor(self.coordinator, self.entry),
            sensor.HidromoticDeviceIdSensor(self.coordinator, self.entry),
            sensor.HidromoticEspVersionSensor(self.coordinator, self.entry),
            sensor.HidromoticOtaSensor(self.coordinator, self.entry),
            sensor.HidromoticOsVersionSensor(self.coordinator, self.entry),
            sensor.HidromoticActiveSlotSensor(self.coordinator, self.entry),
            sensor.HidromoticFreeMemorySensor(self.coordinator, self.entry),
            sensor.HidromoticMinFreeMemorySensor(self.coordinator, self.entry),
            sensor.HidromoticAccessPointSsidSensor(self.coordinator, self.entry),
            sensor.HidromoticAccessPointIpSensor(self.coordinator, self.entry),
            sensor.HidromoticBatterySensor(self.coordinator, self.entry),
            sensor.HidromoticUptimeSensor(self.coordinator, self.entry),
            sensor.HidromoticMessageCounterSensor(self.coordinator, self.entry),
            sensor.HidromoticUartResetCountSensor(self.coordinator, self.entry),
            sensor.HidromoticEspResetCountSensor(self.coordinator, self.entry),
        ]
        self.assertEqual(
            [entity.native_value for entity in entities],
            [
                "on",
                10,
                "garden",
                "192.0.2.2",
                75,
                33,
                "SI",
                "Dynamic",
                "192.0.2.1",
                11756,
                "AA:BB:CC:DD:EE:FF",
                "CHI Smart Mini",
                12,
                "0x42, 3",
                "2026-01-02",
                "device-1",
                "1.2.3",
                "READY",
                "2.19.1",
                0,
                35476,
                11704,
                "CHI3_C985AB",
                "192.0.4.1",
                100,
                300,
                17,
                4,
                5,
            ],
        )

        self.coordinator.get_pump.return_value = {"estado": 99}
        self.assertEqual(entities[0].native_value, "unknown_99")
        self.coordinator.client.data["bateria"] = 0
        self.assertIsNone(entities[24].native_value)
        self.assertEqual(entities[9].native_unit_of_measurement, "s")
        self.assertEqual(entities[21].native_unit_of_measurement, "B")

    async def test_binary_sensors_report_state(self) -> None:
        self.coordinator.get_pump.return_value = {"pausa_externa": 1}
        self.coordinator.client.data["inputs"] = {0: {"estado": True}}
        pause = binary_sensor.HidromoticExternalPauseBinarySensor(
            self.coordinator, self.entry
        )
        rain = binary_sensor.HidromoticRainBlockedBinarySensor(
            self.coordinator, self.entry
        )
        physical = binary_sensor.HidromoticPhysicalInputSensor(
            self.coordinator,
            self.entry,
            0,
            {"tipo": 1, "tipo_name": "Lluvia"},
        )

        self.assertTrue(pause.is_on)
        self.assertTrue(rain.is_on)
        self.assertTrue(physical.is_on)
        self.coordinator.client.data["inputs"][0]["estado"] = False
        self.assertFalse(physical.is_on)

    async def test_button_forwards_restart_action(self) -> None:
        entity = button.HidromoticRebootButton(self.coordinator, self.entry)

        await entity.async_press()

        self.coordinator.client.reboot_device.assert_awaited_once()

    async def test_binary_sensor_setup_adds_physical_inputs(self) -> None:
        self.coordinator.get_tanks.return_value = {0: {"nivel": 1}}
        self.coordinator.client.data["inputs"] = {
            0: {"tipo": 0},
            1: {"tipo": 1, "tipo_name": "Sensor de lluvia"},
        }
        add_entities = MagicMock()
        await binary_sensor.async_setup_entry(MagicMock(), self.entry, add_entities)

        self.assertEqual(len(add_entities.call_args_list[0].args[0]), 2)
        self.assertEqual(len(add_entities.call_args_list[1].args[0]), 1)
        listener = self.coordinator.async_add_listener.call_args.args[0]
        listener()
        self.assertEqual(len(add_entities.call_args_list), 2)

    async def test_switch_setup_tracks_dynamic_outputs_and_visibility(self) -> None:
        collections = {
            "zones": {0: {"estado": 7}},
            "tanks": {0: {"estado": 7}},
            "pools": {0: {"estado": 7}},
            "mangueras": {0: {"estado": 7}},
            "ciclon": {0: {"estado": 7}},
            "riegos": {0: {"estado": 7}},
        }
        for name, value in collections.items():
            getattr(self.coordinator, f"get_{name}").return_value = value
        add_entities = MagicMock()

        with patch(
            "custom_components.hidromotic.switch.update_output_entity_visibility"
        ) as update_visibility:
            await switch.async_setup_entry(MagicMock(), self.entry, add_entities)
            listener = self.coordinator.async_add_listener.call_args.args[0]
            self.assertEqual(len(add_entities.call_args_list), 1)

            for output in collections.values():
                output[0]["estado"] = 1
            listener()
            self.assertEqual(len(add_entities.call_args_list), 2)
            self.assertEqual(len(add_entities.call_args_list[1].args[0]), 6)

            listener()
            self.assertEqual(len(add_entities.call_args_list), 2)

            for output in collections.values():
                output[0]["estado"] = 7
            listener()

        self.assertEqual(update_visibility.call_count, 24)

    async def test_number_and_select_setup_add_tank_controls_when_enabled(self) -> None:
        self.coordinator.get_pools.return_value = {}
        self.coordinator.get_zones.return_value = {}
        tanks = {0: {"estado": 7, "modo": 0, "tipo_flotante": 1}}
        self.coordinator.get_tanks.return_value = tanks
        add_numbers = MagicMock()
        add_selects = MagicMock()

        with (
            patch(
                "custom_components.hidromotic.number.update_output_entity_visibility"
            ),
            patch(
                "custom_components.hidromotic.select.update_output_entity_visibility"
            ),
        ):
            await number.async_setup_entry(MagicMock(), self.entry, add_numbers)
            await select.async_setup_entry(MagicMock(), self.entry, add_selects)
            number_listener = self.coordinator.async_add_listener.call_args_list[-2].args[0]
            select_listener = self.coordinator.async_add_listener.call_args_list[-1].args[0]
            self.assertEqual(add_numbers.call_count, 0)
            self.assertEqual(add_selects.call_count, 0)

            tanks[0]["estado"] = 0
            number_listener()
            select_listener()

        self.assertEqual(add_numbers.call_count, 1)
        self.assertIsInstance(
            add_numbers.call_args.args[0][0], number.HidromoticTankDurationNumber
        )
        self.assertEqual(add_selects.call_count, 1)
        self.assertIsInstance(
            add_selects.call_args.args[0][0], select.HidromoticTankModeSelect
        )

    async def test_button_setup_adds_restart_entity(self) -> None:
        add_entities = MagicMock()

        await button.async_setup_entry(MagicMock(), self.entry, add_entities)

        self.assertIsInstance(add_entities.call_args.args[0][0], button.HidromoticRebootButton)
