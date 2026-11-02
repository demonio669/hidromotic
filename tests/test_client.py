"""Tests for Hidromotic WebSocket protocol parsing."""

import unittest

from homeassistant.exceptions import HomeAssistantError

from custom_components.hidromotic.client import HidromoticClient


class HidromoticClientParsingTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_json_updates_notify_registered_callbacks(self) -> None:
        client = HidromoticClient("localhost")
        updates: list[dict] = []
        client.register_callback(updates.append)

        await client._process_text(
            '{"result":{"id":"device-1","uptime":20,'
            '"wifi":{"sta":{"ssid":"garden","ip":"192.0.2.1",'
            '"rssi":-60,"routertime":12}}}}'
        )

        self.assertEqual(len(updates), 1)
        self.assertEqual(client.data["device_id"], "device-1")
        self.assertEqual(client.data["wifi_ssid"], "garden")
        self.assertEqual(client.data["wifi_ip"], "192.0.2.1")
        self.assertEqual(client.data["wifi_signal"], 80)
        self.assertEqual(client.data["wifi_routertime"], 12)

    async def test_command_failure_is_reported_when_disconnected(self) -> None:
        client = HidromoticClient("localhost")

        with self.assertRaises(HomeAssistantError):
            await client._send_command("#@C;")

    async def test_tank_level_matches_original_web_interface_values(self) -> None:
        client = HidromoticClient("localhost")
        client.data["tanks"] = {
            0: {"nivel": 0},
            1: {"nivel": 1},
            2: {"nivel": 2},
            3: {"nivel": 3},
            4: {"nivel": 4},
        }

        self.assertEqual(client.get_tank_level(0), "full")
        self.assertEqual(client.get_tank_level(1), "empty")
        self.assertEqual(client.get_tank_level(2), "sensor_fail")
        self.assertEqual(client.get_tank_level(3), "level_fail")
        self.assertEqual(client.get_tank_level(4), "medium")
