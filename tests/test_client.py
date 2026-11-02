"""Tests for Hidromotic WebSocket protocol parsing."""

import unittest
from unittest.mock import AsyncMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.hidromotic.client import HidromoticClient, normalize_mac_address


class HidromoticClientParsingTests(unittest.IsolatedAsyncioTestCase):
    async def test_mac_address_is_normalized_and_validated(self) -> None:
        self.assertEqual(
            normalize_mac_address("AA:BB:CC:DD:EE:FF"),
            "aabbccddeeff",
        )
        self.assertEqual(
            normalize_mac_address("AA-BB-CC-DD-EE-FF"),
            "aabbccddeeff",
        )
        self.assertIsNone(normalize_mac_address("unknown"))
        self.assertIsNone(normalize_mac_address(None))

    async def test_riego_zone_duration_uses_zero_based_hex_zone_index(self) -> None:
        client = HidromoticClient("localhost")
        client._send_command = AsyncMock()
        client.data["riegos"] = {0: {"slot_id": 0, "zonas": {}}}

        await client.set_riego_zona_duration(0, 0, 27)

        client._send_command.assert_awaited_once_with("#@H0Z0D27;#@+;")
        self.assertEqual(client.data["riegos"][0]["zonas"]["duracion_1"], 27)

    async def test_riego_zone_duration_encodes_large_indices_as_hex(self) -> None:
        client = HidromoticClient("localhost")
        client._send_command = AsyncMock()
        client.data["riegos"] = {10: {"slot_id": 10, "zonas": {}}}

        await client.set_riego_zona_duration(10, 10, 42)

        client._send_command.assert_awaited_once_with("#@HAZAD42;#@+;")
        self.assertEqual(client.data["riegos"][10]["zonas"]["duracion_11"], 42)

    async def test_zone_output_duration_does_not_change_irrigation_programs(self) -> None:
        client = HidromoticClient("localhost")
        client._send_command = AsyncMock()
        client.data["zones"] = {1: {"slot_id": 10, "duracion": 5}}
        client.data["riegos"] = {
            0: {"slot_id": 0, "zonas": {"duracion_2": 10}},
            1: {"slot_id": 1, "zonas": {"duracion_2": 20}},
        }

        await client.set_output_duration("zones", 1, 35)

        client._send_command.assert_awaited_once_with("#@SAD35;#@+;")
        self.assertEqual(client.data["zones"][1]["duracion"], 35)
        self.assertEqual(
            [riego["zonas"]["duracion_2"] for riego in client.data["riegos"].values()],
            [10, 20],
        )

    async def test_running_frame_offsets_and_auto_irrigation_state(self) -> None:
        client = HidromoticClient("localhost")
        client.data["pic_version"] = 1
        client.data["pump"] = {}
        client.data["auto_riego"] = False
        client.data["inputs"] = {0: {"invert": True}}
        client.data["riegos"] = {0: {}}

        frame = bytes(
            [
                ord("D"), 0, 0, 0, 0, 0,
                ord("B"), 1, 2, 3, 4, 5, 6,
                ord("b"), 55, 0,
                ord("E"), 0, 1,
                ord("R"), 2, 1,
                ord("H"), 0, 1, 2, 3, 10, 0, 0, 0,
                ord("L"), 0, 0x41, 1, 5, 0,
                ord("u"), 0x75, 0x34, 0x12,
            ]
        )

        await client._parse_running_data(frame)

        self.assertEqual(client.data["pump"]["marcha"], 0x06050403)
        self.assertEqual(client.data["bateria"], 55)
        self.assertFalse(client.data["inputs"][0]["estado"])
        self.assertEqual(client.data["active_horario"], 2)
        self.assertTrue(client.data["lluvia_bloqueado"])
        self.assertFalse(client.data["auto_riego"])
        self.assertEqual(client.data["riegos"][0]["duracion"], 10)
        self.assertEqual(client.data["tareas"][0]["duracion"], 5)
        self.assertEqual(client.data["uart_reset_count"], 0x1234)

    async def test_running_frame_is_ignored_before_full_config(self) -> None:
        client = HidromoticClient("localhost")

        await client._parse_running_data(bytes([ord("D"), 0, 0, 0, 0, 0, ord("B"), 1, 0]))

        self.assertNotIn("pump", client.data)

    async def test_full_config_reads_auto_irrigation_and_uart_counter(self) -> None:
        client = HidromoticClient("localhost")
        frame = bytearray(16)
        frame[0] = ord("C")
        frame[1] = ord("M")
        frame[6] = 0x42
        frame.append(ord("S"))
        frame.extend([0] * (6 * 6))
        frame.extend([ord("R"), 0, 3, 1])
        frame.extend([ord("u"), 0x75, 0x34, 0x12])

        await client._parse_full_config(bytes(frame))

        self.assertFalse(client.data["auto_riego"])
        self.assertEqual(client.data["active_horario"], 3)
        self.assertTrue(client.data["lluvia_bloqueado"])
        self.assertEqual(client.data["uart_reset_count"], 0x1234)

    async def test_full_config_consumes_sections_before_matching_marker_bytes(self) -> None:
        client = HidromoticClient("localhost")
        frame = bytearray(16)
        frame[0] = ord("C")
        frame[1] = ord("M")
        frame[6] = 0x42
        pump = bytearray(17)
        pump[0] = ord("B")
        pump[1] = 1
        pump[3] = ord("S")
        frame.extend(pump)
        frame.extend([ord("S"), *([0] * (6 * 6))])
        frame.extend([ord("R"), 1, 2, 0])

        await client._parse_full_config(bytes(frame))

        self.assertTrue(client.data_ready.is_set())
        self.assertEqual(client.data["pump"]["marcha"], ord("S"))
        self.assertTrue(client.data["auto_riego"])
        self.assertEqual(client.data["active_horario"], 2)
        self.assertFalse(client.data["lluvia_bloqueado"])
        self.assertEqual(client.data["outputs"], {})

    async def test_full_config_parses_program_label_as_data(self) -> None:
        client = HidromoticClient("localhost")
        frame = bytearray(16)
        frame[0] = ord("C")
        frame[1] = ord("M")
        frame[6] = 0x42
        frame.extend([ord("S"), *([0] * (6 * 6))])
        frame.extend([ord("R"), 1, 0, 0])

        riego = bytearray(28)
        riego[0] = ord("H")
        riego[1] = 0
        riego[2] = 1
        riego[10] = 1
        riego[15] = 25
        riego[27] = 3
        frame.extend(riego)
        frame.extend(b"RHS")

        await client._parse_full_config(bytes(frame))

        self.assertEqual(client.data["riegos"][0]["label"], "RHS")
        self.assertEqual(client.data["riegos"][0]["zonas"]["duracion_1"], 25)
        self.assertTrue(client.data["auto_riego"])

    async def test_full_config_preserves_zero_based_output_slots(self) -> None:
        client = HidromoticClient("localhost")
        frame = bytearray(16)
        frame[0] = ord("C")
        frame[1] = ord("M")
        frame[6] = 0x42
        frame.extend([ord("S"), *([0] * 6)])
        frame.extend([0x41, 1, 60, 0, 0, 0])
        frame.extend([0] * (4 * 6))
        frame.extend([ord("R"), 0, 0, 0])

        await client._parse_full_config(bytes(frame))

        self.assertEqual(client.data["zones"][0]["slot_id"], 1)
        self.assertEqual(list(client.data["outputs"]), [1])
        self.assertEqual(client.data["outputs"][1]["slot_id"], 1)

    async def test_truncated_full_config_does_not_mark_data_ready(self) -> None:
        client = HidromoticClient("localhost")

        await client._parse_full_config(bytes([ord("C"), ord("M")]))

        self.assertFalse(client.data_ready.is_set())

        frame = bytearray(16)
        frame[0] = ord("C")
        frame[1] = ord("M")
        frame.extend([ord("S"), 0x41, 1, 2])
        await client._parse_full_config(bytes(frame))

        self.assertFalse(client.data_ready.is_set())
        self.assertEqual(client.data["zones"], {})

    async def test_truncated_running_section_does_not_update_state(self) -> None:
        client = HidromoticClient("localhost")
        client.data["pic_version"] = 1
        client.data["inputs"] = {
            0: {"id": 0, "invert": False, "estado": False, "raw_estado": False}
        }

        await client._parse_running_data(bytes([ord("D"), 0, 0, 0, 0, 0, ord("E"), 0]))

        self.assertFalse(client.data["inputs"][0]["estado"])
        self.assertFalse(client.data["inputs"][0]["raw_estado"])

    async def test_json_updates_notify_registered_callbacks(self) -> None:
        client = HidromoticClient("localhost")
        updates: list[dict] = []
        client.register_callback(updates.append)

        await client._process_text(
            '{"result":{"id":"device-1","uptime":20,'
            '"mac":"AA:BB:CC:DD:EE:FF",'
            '"wifi":{"sta":{"ssid":"garden","ip":"192.0.2.1",'
            '"rssi":-60,"routertime":12}}}}'
        )

        self.assertEqual(len(updates), 1)
        self.assertEqual(client.data["device_id"], "device-1")
        self.assertEqual(client.data["mac"], "AA:BB:CC:DD:EE:FF")
        self.assertTrue(client.mac_ready.is_set())
        self.assertEqual(client.data["wifi_ssid"], "garden")
        self.assertEqual(client.data["wifi_ip"], "192.0.2.1")
        self.assertEqual(client.data["wifi_signal"], 80)
        self.assertEqual(client.data["wifi_routertime"], 12)

    async def test_command_failure_is_reported_when_disconnected(self) -> None:
        client = HidromoticClient("localhost")

        with self.assertRaises(HomeAssistantError):
            await client._send_command("#@C;")

    async def test_tank_level_values_match_reported_device_states(self) -> None:
        client = HidromoticClient("localhost")
        client.data["tanks"] = {
            0: {"nivel": 0},
            1: {"nivel": 1},
            2: {"nivel": 2},
            3: {"nivel": 3},
            4: {"nivel": 4},
        }

        self.assertEqual(client.get_tank_level(0), "empty")
        self.assertEqual(client.get_tank_level(1), "full")
        self.assertEqual(client.get_tank_level(2), "sensor_fail")
        self.assertEqual(client.get_tank_level(3), "level_fail")
        self.assertEqual(client.get_tank_level(4), "medium")
