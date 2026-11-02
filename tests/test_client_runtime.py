"""Tests for Hidromotic WebSocket lifecycle and command handling."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.exceptions import HomeAssistantError

from custom_components.hidromotic.client import (
    HidromoticClient,
    hex_to_int,
    int_to_hex,
    normalize_mac_address,
)


class WaitingWebSocket:
    def __init__(self) -> None:
        self.closed = False
        self.release = asyncio.Event()
        self.send_str = AsyncMock()

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self.release.wait()
        raise StopAsyncIteration

    async def close(self) -> None:
        self.closed = True
        self.release.set()


class MessageWebSocket:
    def __init__(self, messages: list[MagicMock]) -> None:
        self.messages = iter(messages)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.messages)
        except StopIteration:
            raise StopAsyncIteration from None


class ExplodingWebSocket:
    def __aiter__(self):
        raise RuntimeError("listener failed")


class HidromoticClientRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_protocol_helpers_and_callback_removal(self) -> None:
        self.assertEqual(hex_to_int("A"), 10)
        self.assertEqual(hex_to_int("B"), 11)
        self.assertEqual(hex_to_int("C"), 12)
        self.assertEqual(hex_to_int("9"), 9)
        self.assertEqual(int_to_hex(10), "A")
        self.assertEqual(int_to_hex(11), "B")
        self.assertEqual(int_to_hex(12), "C")
        self.assertEqual(int_to_hex(9), "9")
        self.assertIsNone(normalize_mac_address(123))

        client = HidromoticClient("chi.local")
        callback = MagicMock()
        remove_callback = client.register_callback(callback)
        client._notify_callbacks()
        callback.assert_called_once_with(client.data)
        remove_callback()
        client._notify_callbacks()
        callback.assert_called_once()

    async def test_connect_and_disconnect_notify_connection_transitions(self) -> None:
        websocket = WaitingWebSocket()
        session = MagicMock()
        session.ws_connect = AsyncMock(return_value=websocket)
        client = HidromoticClient("chi.local", session=session)
        updates: list[dict] = []
        client.register_callback(updates.append)

        self.assertTrue(await client.connect())
        self.assertTrue(client.connected)
        self.assertEqual(len(updates), 1)
        self.assertEqual(websocket.send_str.await_count, 3)

        await client.disconnect()
        self.assertFalse(client.connected)
        self.assertTrue(websocket.closed)
        self.assertEqual(len(updates), 2)

    async def test_connect_failure_and_owned_session_cleanup(self) -> None:
        failed_session = MagicMock()
        failed_session.ws_connect = AsyncMock(side_effect=OSError("offline"))
        failed = HidromoticClient("chi.local", session=failed_session)
        callback = MagicMock()
        failed.register_callback(callback)
        self.assertFalse(await failed.connect())
        self.assertFalse(failed.connected)
        callback.assert_not_called()

        websocket = WaitingWebSocket()
        owned_session = MagicMock()
        owned_session.ws_connect = AsyncMock(return_value=websocket)
        owned_session.close = AsyncMock()
        client = HidromoticClient("chi.local")
        with patch("custom_components.hidromotic.client.aiohttp.ClientSession", return_value=owned_session):
            self.assertTrue(await client.connect())
        self.assertTrue(client._owns_session)
        await client.disconnect()
        owned_session.close.assert_awaited_once()

    async def test_send_command_formats_and_reports_transport_errors(self) -> None:
        client = HidromoticClient("chi.local")
        websocket = WaitingWebSocket()
        client._ws = websocket

        await client._send_command("#@C;")
        await client._send_command("e")
        self.assertIn('"params":{"c":"#@C;"}}', websocket.send_str.await_args_list[0].args[0])
        self.assertIn('"id":1111', websocket.send_str.await_args_list[1].args[0])

        websocket.send_str.side_effect = TimeoutError
        with self.assertRaises(HomeAssistantError):
            await client._send_command("e")

        websocket.send_str.side_effect = OSError("closed")
        with self.assertRaises(HomeAssistantError):
            await client._send_command("e")

        websocket.closed = True
        with self.assertRaises(HomeAssistantError):
            await client._send_command("e")

    async def test_listener_processes_messages_and_reconnects(self) -> None:
        messages = [
            MagicMock(type=aiohttp.WSMsgType.TEXT, data='{"result":{"id":"chi"}}'),
            MagicMock(type=aiohttp.WSMsgType.BINARY, data=b""),
            MagicMock(type=aiohttp.WSMsgType.ERROR, data="lost"),
        ]
        websocket = MessageWebSocket(messages)
        client = HidromoticClient("chi.local")
        client._ws = websocket
        client._should_reconnect = False
        callback = MagicMock()
        client.register_callback(callback)

        await client._listen()

        self.assertEqual(client.data["device_id"], "chi")
        self.assertFalse(client.connected)
        callback.assert_called_once_with(client.data)

    async def test_listener_handles_closed_socket_and_iteration_errors(self) -> None:
        closed = MagicMock(type=aiohttp.WSMsgType.CLOSED, data=None)
        client = HidromoticClient("chi.local")
        client._ws = MessageWebSocket([closed])
        client._connected = True
        client.data_ready.set()
        client._should_reconnect = False
        callback = MagicMock()
        client.register_callback(callback)

        await client._listen()

        self.assertFalse(client.connected)
        self.assertFalse(client.data_ready.is_set())
        callback.assert_called_once_with(client.data)

        client._ws = ExplodingWebSocket()
        await client._listen()
        self.assertFalse(client.connected)

    async def test_reconnect_stops_after_an_attempt_raises(self) -> None:
        client = HidromoticClient("chi.local")
        client.connect = AsyncMock(side_effect=OSError("offline"))
        sleep_calls = 0

        async def stop_after_retry(_delay: int) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls == 2:
                client._should_reconnect = False

        with patch(
            "custom_components.hidromotic.client.asyncio.sleep",
            new=AsyncMock(side_effect=stop_after_retry),
        ):
            await client._reconnect()

        client.connect.assert_awaited_once()

    async def test_reconnect_retries_until_connection_succeeds(self) -> None:
        client = HidromoticClient("chi.local")
        results = iter((False, True))

        async def connect() -> bool:
            connected = next(results)
            client._connected = connected
            return connected

        client.connect = connect
        with patch("custom_components.hidromotic.client.asyncio.sleep", new=AsyncMock()):
            await client._reconnect()

        self.assertTrue(client.connected)

    async def test_callback_errors_are_isolated(self) -> None:
        client = HidromoticClient("chi.local")
        client.register_callback(MagicMock(side_effect=RuntimeError("callback failed")))
        client._notify_callbacks()

    async def test_text_and_binary_message_edge_cases(self) -> None:
        client = HidromoticClient("chi.local")
        callback = MagicMock()
        client.register_callback(callback)
        await client._process_text("not json")
        await client._process_text("[]")
        await client._process_text('{"result":{"wifi":{"sta":"invalid"}}}')
        self.assertEqual(callback.call_count, 3)

        await client._process_binary(b"")
        await client._process_binary(b"?\x00")
        await client._process_binary(bytes([ord("C"), 0]))
        self.assertEqual(callback.call_count, 5)

    async def test_text_parser_handles_device_and_wifi_metadata(self) -> None:
        client = HidromoticClient("chi.local")
        await client._process_text(
            '{"result":{"id":"chi","fw_version":"1.0","ota":"ready",'
            '"uptime":20,"mac":" AA:BB:CC:DD:EE:FF ",'
            '"wifi":{"sta":{"ssid":"garden","ip":"192.0.2.1",'
            '"rssi":-75,"routertime":10}}}}'
        )

        self.assertEqual(client.data["device_id"], "chi")
        self.assertEqual(client.data["fw_version_esp"], "1.0")
        self.assertEqual(client.data["wifi_signal"], 50)
        self.assertEqual(client.data["mac"], "AA:BB:CC:DD:EE:FF")
        self.assertTrue(client.mac_ready.is_set())

        for rssi, expected in ((0, 0), (-100, 0), (-40, 100)):
            await client._process_text(
                f'{{"wifi":{{"sta":{{"rssi":{rssi}}}}}}}'
            )
            self.assertEqual(client.data["wifi_signal"], expected)

    async def test_full_configuration_parses_every_known_section(self) -> None:
        client = HidromoticClient("chi.local")
        frame = bytearray(16)
        frame[0] = ord("C")
        frame[1] = ord("M")
        frame[2:4] = (5).to_bytes(2, "little")
        frame[6] = 0x42
        frame[7] = 3

        pump = bytearray(17)
        pump[0] = ord("B")
        pump[1] = 1
        pump[3:7] = (1234).to_bytes(4, "little")
        frame.extend(pump)

        inputs = bytearray([ord("E")])
        for input_id in range(4):
            inputs.extend([input_id + 1, input_id % 2, input_id, input_id % 2])
        frame.extend(inputs)

        frame.append(ord("S"))
        frame.extend([0x41, 1, 5, 0, 0, 2])
        frame.extend(b"Z1")
        frame.extend([0x21, 0, 6, 0, 0, 0, 1, 2, 3])
        frame.extend([0x51, 0, 7, 0, 0, 0])
        frame.extend([0x11, 0, 8, 0, 0, 0])
        frame.extend([0x61, 0, 9, 0, 0, 0, *range(10)])
        frame.extend([0, 0, 0, 0, 0, 0])
        frame.extend([ord("R"), 1, 2, 1])

        irrigation = bytearray(28)
        irrigation[0] = ord("H")
        irrigation[1] = 0
        irrigation[2] = 1
        irrigation[9] = 1
        irrigation[10] = 1
        irrigation[15:27] = bytes(range(12))
        irrigation[27] = 2
        frame.extend(irrigation)
        frame.extend(b"P1")
        frame.extend([ord("L"), 0, 0x41, 1, 12, 0])
        frame.extend([ord("L"), 1, 0x42, 0])
        frame.extend([ord("b"), 99, 0])
        frame.extend([ord("u"), 0x75, 4, 0])
        frame.extend([ord("c"), 3, 0])
        frame.append(ord("?"))

        self.assertTrue(await client._parse_full_config(bytes(frame)))
        self.assertTrue(client.data_ready.is_set())
        self.assertEqual(client.data["pump"]["marcha"], 1234)
        self.assertEqual(client.data["inputs"][3]["tipo"], 4)
        self.assertEqual(client.data["zones"][0]["label"], "Z1")
        self.assertEqual(client.data["tanks"][0]["nivel"], 2)
        self.assertEqual(client.data["tanks"][0]["tipo_flotante"], 3)
        self.assertEqual(client.data["tanks"][0]["duracion"], 6)
        self.assertEqual(client.data["pools"][0]["duracion"], 7)
        self.assertEqual(client.data["mangueras"][0]["duracion"], 8)
        self.assertEqual(client.data["ciclon"][0]["proximo_ciclon"], 0x0908)
        self.assertEqual(client.data["riegos"][0]["label"], "P1")
        self.assertEqual(client.data["tareas"][0]["duracion"], 12)
        self.assertEqual(client.data["tareas"][1]["duracion"], 0)
        self.assertEqual(client.data["bateria"], 99)
        self.assertEqual(client.data["uart_reset_count"], 4)
        self.assertEqual(client.data["esp_reset_count"], 3)

    async def test_full_configuration_rejects_truncated_sections(self) -> None:
        markers = (
            (ord("B"), 1),
            (ord("E"), 1),
            (ord("S"), 1),
            (ord("H"), 1),
            (ord("R"), 1),
            (ord("L"), 1),
            (ord("b"), 1),
            (ord("u"), 1),
            (ord("c"), 1),
        )
        for marker, _ in markers:
            client = HidromoticClient("chi.local")
            frame = bytearray(16)
            frame[0] = ord("C")
            frame[1] = ord("M")
            frame.extend([marker])
            self.assertFalse(await client._parse_full_config(bytes(frame)))
            self.assertFalse(client.data_ready.is_set())

        client = HidromoticClient("chi.local")
        frame = bytearray(16)
        frame[0] = ord("C")
        frame[1] = ord("M")
        frame.extend([ord("S"), 0x41, 0, 1, 0, 0, 3, ord("a")])
        self.assertFalse(await client._parse_full_config(bytes(frame)))

    async def test_full_configuration_handles_standard_device_and_unmapped_outputs(self) -> None:
        client = HidromoticClient("chi.local")
        frame = bytearray(16)
        frame[0] = ord("C")
        frame.extend([ord("S")])
        for output_type in (0x10, 0x41, 0x31, 0, 0, 0, 0, 0, 0, 0, 0, 0):
            frame.extend([output_type, 0, 1, 0, 7 if output_type == 0x41 else 0, 0])
        frame.extend([ord("H"), *([0] * 39)])
        frame.extend([ord("?")])

        self.assertTrue(await client._parse_full_config(bytes(frame)))
        self.assertFalse(client.data["is_mini"])
        self.assertEqual(client.data["zones"][0]["estado"], 7)
        self.assertEqual(client.data["riegos"][0]["label"], "Riego A")
        self.assertTrue(client.data_ready.is_set())

        client = HidromoticClient("chi.local")
        frame = bytearray(16)
        frame[0] = ord("C")
        frame[1] = ord("M")
        frame.extend([ord("S"), *([0] * 36), ord("H")])
        self.assertFalse(await client._parse_full_config(bytes(frame)))

    async def test_running_frame_updates_every_section(self) -> None:
        client = HidromoticClient("chi.local")
        client.data["pic_version"] = 1
        client.data["pump"] = {}
        client.data["inputs"] = {0: {"invert": True}}
        client.data["zones"] = {0: {}}
        client.data["tanks"] = {0: {"nivel": 0}}
        client.data["pools"] = {0: {"estado": 0}}
        client.data["mangueras"] = {0: {"estado": 0}}
        client.data["ciclon"] = {0: {"modo_tiempo": 1}}
        client.data["riegos"] = {0: {}}
        client.data["outputs_by_tipo"] = {
            0x41: {"estado": 0},
            0x21: {"estado": 0},
            0x51: {"estado": 0},
            0x11: {"estado": 0},
            0x61: {"estado": 0},
        }

        frame = bytearray([ord("D"), 0, 0, 0, 0, 0])
        frame.extend([ord("B"), 1, 2, 3, 4, 5, 6])
        frame.extend([ord("b"), 55, 0])
        frame.extend([ord("E"), 0, 1])
        frame.extend([ord("R"), 2, 1])
        frame.extend([ord("S"), 0x41, 1, 0, 0])
        frame.extend([ord("S"), 0x21, 1, 4, 0, 0, 0])
        frame.extend([ord("S"), 0x51, 1, 0, 0])
        frame.extend([ord("S"), 0x11, 1, 0, 0])
        frame.extend([ord("S"), 0x61, 1, 90, 0, 0])
        frame.extend([ord("H"), 0, 1, 2, 3, 10, 0, 0, 0])
        frame.extend([ord("L"), 0, 0x41, 1, 5, 0])
        frame.extend([ord("L"), 1, 0x42, 0])
        frame.extend([ord("u"), 0x75, 4, 0])
        frame.extend([ord("c"), 3, 0])
        frame.extend([ord("k"), 1])
        frame.append(ord("?"))

        await client._parse_running_data(bytes(frame))
        self.assertEqual(client.data["pump"]["marcha"], 0x06050403)
        self.assertEqual(client.data["inputs"][0]["estado"], False)
        self.assertEqual(client.data["zones"][0]["estado"], 1)
        self.assertEqual(client.data["tanks"][0]["nivel"], 4)
        self.assertEqual(client.data["ciclon"][0]["proximo_ciclon"], 90)
        self.assertEqual(client.data["riegos"][0]["duracion"], 10)
        self.assertEqual(client.data["button_state"], 1)

    async def test_running_frame_ignores_invalid_data_and_truncated_sections(self) -> None:
        client = HidromoticClient("chi.local")
        await client._parse_running_data(b"")
        await client._parse_running_data(b"X\x00\x00\x00\x00\x00")
        client.data["pic_version"] = 1
        await client._parse_running_data(b"D")

        for section, payload in (
            ("B", [1]),
            ("b", [1]),
            ("E", [0]),
            ("R", [1]),
            ("S", [0]),
            ("H", []),
            ("L", []),
            ("u", [1]),
            ("c", [1]),
            ("k", []),
        ):
            await client._parse_running_data(bytes([ord("D"), 0, 0, 0, 0, 0, ord(section), *payload]))

        client.data["pump"] = {}
        await client._parse_running_data(bytes([ord("D"), 0, 0, 0, 0, 0, ord("B"), 2, 3]))
        client.data["inputs"] = {}
        client.data["outputs_by_tipo"] = {}
        await client._parse_running_data(
            bytes([ord("D"), 0, 0, 0, 0, 0, ord("E"), 99, 1,
                   ord("S"), 0x41, 1, 0, 0, 0])
        )
        self.assertNotIn(99, client.data["inputs"])

    async def test_output_commands_durations_and_accessors(self) -> None:
        client = HidromoticClient("chi.local")
        client._send_command = AsyncMock()
        client.data.update(
            {
                "zones": {0: {"slot_id": 10, "duracion": 5}},
                "tanks": {0: {"slot_id": 1}},
                "pools": {0: {"slot_id": 2}},
                "mangueras": {0: {"slot_id": 3}},
                "ciclon": {0: {"slot_id": 4}},
                "riegos": {0: {"slot_id": 10, "zonas": {}}},
                "pump": {"estado": 1},
                "auto_riego": False,
                "lluvia_bloqueado": True,
            }
        )
        updates: list[dict] = []
        client.register_callback(updates.append)

        await client.set_zone_state(0, True)
        await client.set_tank_state(0, False)
        await client.set_pool_state(0, True)
        await client.set_manguera_state(0, False)
        await client.set_ciclon_state(0, True)
        await client.set_riego_state(0, True)
        await client.set_output_duration("zones", 0, 25)
        await client.set_riego_zona_duration(0, 0, 30)
        await client.set_auto_riego(True)
        await client.reboot_device()
        await client.refresh()

        self.assertEqual(client.data["zones"][0]["duracion"], 25)
        self.assertEqual(client.data["riegos"][0]["zonas"]["duracion_1"], 30)
        self.assertTrue(client.is_auto_riego_on())
        self.assertTrue(client.is_lluvia_bloqueado())
        self.assertEqual(client.get_zones()[0]["slot_id"], 10)
        self.assertEqual(client.get_tanks()[0]["slot_id"], 1)
        self.assertEqual(client.get_pools()[0]["slot_id"], 2)
        self.assertEqual(client.get_mangueras()[0]["slot_id"], 3)
        self.assertEqual(client.get_ciclon()[0]["slot_id"], 4)
        self.assertEqual(client.get_riegos()[0]["slot_id"], 10)
        self.assertEqual(client.get_pump()["estado"], 1)
        self.assertEqual(len(updates), 3)

        for level, expected in (
            (0, "empty"),
            (1, "full"),
            (2, "sensor_fail"),
            (3, "level_fail"),
            (4, "medium"),
            (99, "unknown"),
        ):
            client.data["tanks"][0]["nivel"] = level
            self.assertEqual(client.get_tank_level(0), expected)
        self.assertEqual(HidromoticClient("chi.local").get_tank_level(0), "unknown")

    async def test_default_accessors_and_callback_failures(self) -> None:
        client = HidromoticClient("chi.local")
        self.assertEqual(client.get_zones(), {})
        self.assertEqual(client.get_tanks(), {})
        self.assertEqual(client.get_pools(), {})
        self.assertEqual(client.get_mangueras(), {})
        self.assertEqual(client.get_riegos(), {})
        self.assertEqual(client.get_ciclon(), {})
        self.assertEqual(client.get_pump(), {})
        self.assertFalse(client.is_auto_riego_on())
        self.assertFalse(client.is_lluvia_bloqueado())

        client._send_command = AsyncMock()
        client.data["zones"] = {0: {"slot_id": 1}}
        client.data["riegos"] = {0: {"slot_id": 1}}
        client.register_callback(MagicMock(side_effect=RuntimeError("callback failed")))
        await client.set_output_duration("zones", 0, 10)
        await client.set_riego_zona_duration(0, 0, 10)
        await client.set_auto_riego(True)
        await client.reboot_device()
        await client.refresh()

    async def test_tank_mode_configuration_uses_tank_index_and_float_guard(self) -> None:
        client = HidromoticClient("chi.local")
        client._send_command = AsyncMock()
        client.data["tanks"] = {
            10: {"modo": 0, "tipo_flotante": 1},
            1: {"modo": 0, "tipo_flotante": 0},
        }
        callback = MagicMock()
        client.register_callback(callback)

        await client.set_tank_mode(10, True)

        client._send_command.assert_awaited_once_with("#@T10A1;#@+;")
        self.assertEqual(client.data["tanks"][10]["modo"], 1)
        callback.assert_called_once_with(client.data)

        with self.assertRaises(HomeAssistantError):
            await client.set_tank_mode(1, True)
        client._send_command.assert_awaited_once()

    async def test_missing_outputs_do_not_send_commands(self) -> None:
        client = HidromoticClient("chi.local")
        client._send_command = AsyncMock()
        await client._set_output_state("zones", 99, True)
        await client.set_riego_state(99, True)
        await client.set_output_duration("zones", 99, 30)
        await client.set_riego_zona_duration(99, 0, 30)
        client._send_command.assert_not_awaited()
