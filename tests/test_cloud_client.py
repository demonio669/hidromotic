"""Tests for the Hidromotic account-cloud transport."""

import asyncio
from copy import deepcopy
from http.cookies import SimpleCookie
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from homeassistant.exceptions import HomeAssistantError

from custom_components.hidromotic.cloud_client import HidromoticCloudClient


class FakeResponse:
    def __init__(self) -> None:
        self.status = 303
        self.headers = {"Location": "/"}
        self.cookies = SimpleCookie()

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class BlockingWebSocket:
    def __init__(self) -> None:
        self.closed = False
        self._closed_event = asyncio.Event()
        self.send_str = AsyncMock()

    def __aiter__(self) -> "BlockingWebSocket":
        return self

    async def __anext__(self) -> None:
        await self._closed_event.wait()
        raise StopAsyncIteration

    async def close(self) -> None:
        self.closed = True
        self._closed_event.set()


class HidromoticCloudClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = HidromoticCloudClient("account", "password")
        self.state = {
            "device": "ABC123",
            "online": True,
            "v": 845,
            "cc": 66,
            "pic": {
                "pic_id": 15,
                "pic_rev": 5,
                "fecha": "2026-11-05 19:09:51",
                "entradas": [
                    {"i": 0, "tipo": 1, "invert": 1, "actual": 0, "estado": 1},
                ],
                "bomba": {"estado": 0, "marcha_min": 123},
                "salidas": [
                    {"tipo": 0, "estado": 0},
                    {"tipo": 0x41, "bomba": 1, "duracion": 64,
                     "estado": 0, "desc": "Zona de prueba"},
                    {"tipo": 0x22, "bomba": 1, "duracion": 30, "estado": 7},
                    {"tipo": 0x21, "bomba": 1, "duracion": 8, "estado": 0,
                     "tanque": {"modo": 1, "nivel": 0, "tipo": 1}},
                    {"tipo": 0x11, "estado": 0},
                    {"tipo": 0x51, "duracion": 25, "estado": 0},
                ],
                "horarios": [
                    {"i": 0, "estado": 0, "habilitado": 1, "accesorios": 1,
                     "zona_activa": 0, "duracion": 279, "zonas_min": [69, 70],
                     "hora": "20:00", "paridad": 0, "dias": 127},
                ],
                "riego": {"modo": 1, "horario_activo": 0, "lluvia": 0},
                "bateria": 97,
                "uart": {"resets": 2},
                "esp_resets": 3,
            },
            "esp": {
                "id": "CHI/ABC123",
                "fw_version": "806",
                "mac": "AA:BB:CC:DD:EE:FF",
                "uptime": 43,
                "ram": {"free": 36972, "min_free": 11704},
                "wifi": {"sta": {"rssi": -59, "ssid": "test-network"}},
            },
        }

    async def snapshot(self, seq: int = 14, **envelope: object) -> None:
        await self.client._process_text(json.dumps({
            "product": "chi", "device": "ABC123", "kind": "state",
            "data": {"seq": seq, "state": deepcopy(self.state)}, **envelope,
        }))

    async def patch(self, seq: int, ops: list[dict]) -> None:
        await self.client._process_text(json.dumps({
            "product": "chi", "device": "ABC123", "kind": "patch",
            "data": {"seq": seq, "ops": ops},
        }))

    async def test_connect_logs_in_and_requests_cloud_protocol_data(self) -> None:
        response = FakeResponse()
        websocket = BlockingWebSocket()
        session = MagicMock()
        session.post.return_value = response
        session.ws_connect = AsyncMock(return_value=websocket)
        client = HidromoticCloudClient("account", "password", session=session)

        with patch.object(client, "_send_command", new_callable=AsyncMock) as send:
            self.assertTrue(await client.connect())

        session.post.assert_called_once_with(
            "https://hidromotic.com/login",
            data={
                "login": "account",
                "password": "password",
            },
            allow_redirects=False,
        )
        session.ws_connect.assert_awaited_once_with(
            "wss://hidromotic.com/ws",
            heartbeat=30,
            origin="https://hidromotic.com",
            headers={},
        )
        self.assertEqual(
            [call.args[0] for call in send.await_args_list],
            [],
        )
        await client.disconnect()
        self.assertTrue(websocket.closed)

    async def test_login_rejects_response_without_success_redirect(self) -> None:
        for status, location in (
            (200, "/"), (401, "/"), (403, "/"), (500, "/"),
            (303, "/login"), (303, None),
        ):
            with self.subTest(status=status, location=location):
                response = FakeResponse()
                response.status = status
                response.headers = {"Location": location} if location else {}
                session = MagicMock()
                session.post.return_value = response
                session.ws_connect = AsyncMock()
                client = HidromoticCloudClient("account", "password", session=session)
                self.assertFalse(await client.connect())
                session.ws_connect.assert_not_awaited()

    async def test_commands_are_routed_to_the_selected_device(self) -> None:
        websocket = BlockingWebSocket()
        self.client._ws = websocket
        await self.snapshot()

        with patch(
            "custom_components.hidromotic.client.asyncio.sleep",
            new=AsyncMock(),
        ):
            await self.client.set_zone_state(0, True)
            await self.client.set_auto_riego(False)
            await self.client.reboot_device()

        self.assertEqual(
            [json.loads(call.args[0]) for call in websocket.send_str.await_args_list],
            [{"product": "chi", "device": "ABC123", "cmd": command}
             for command in ["#@S1M1;", "#@RA0;#@+;", {"accion": "reiniciar_wifi"}]],
        )

    async def test_login_forwards_response_cookies_with_a_shared_session(self) -> None:
        response = FakeResponse()
        response.cookies["session"] = "test-session"
        response.cookies["session"]["path"] = "/"
        response.cookies["session"]["httponly"] = True
        session = MagicMock()
        session.post.return_value = response
        session.ws_connect = AsyncMock(return_value=BlockingWebSocket())
        client = HidromoticCloudClient("account", "password", session=session)

        self.assertTrue(await client.connect())
        self.assertEqual(
            session.ws_connect.call_args.kwargs["headers"],
            {"Cookie": "session=test-session"},
        )
        await client.disconnect()
        session.close.assert_not_called()

    async def test_snapshot_maps_configuration_and_diagnostics(self) -> None:
        await self.snapshot()

        self.assertTrue(self.client.data_ready.is_set())
        self.assertTrue(self.client.device_id_ready.is_set())
        self.assertTrue(self.client.mac_ready.is_set())
        data = self.client.data
        self.assertEqual(data["device_id"], "CHI/ABC123")
        self.assertFalse(data["is_mini"])
        self.assertEqual(data["pic_version"], 845)
        self.assertEqual(data["pic_id"], "0x0F")
        self.assertEqual(data["zones"][0]["slot_id"], 1)
        self.assertEqual(data["zones"][0]["label"], "Zona de prueba")
        self.assertEqual(data["zones"][0]["duracion"], 64)
        self.assertEqual(data["tanks"][1]["estado"], 7)
        self.assertEqual(data["tanks"][0]["tipo_flotante"], 1)
        self.assertEqual(data["tanks"][0]["modo"], 1)
        self.assertEqual(data["tanks"][0]["nivel"], 0)
        self.assertEqual(data["mangueras"][0]["slot_id"], 4)
        self.assertEqual(data["pools"][0]["slot_id"], 5)
        self.assertIs(data["outputs"][1], data["outputs_by_tipo"][0x41])
        self.assertFalse(data["inputs"][0]["estado"])
        self.assertTrue(data["inputs"][0]["raw_estado"])
        self.assertEqual(data["pump"]["marcha"], 123)
        self.assertEqual(data["riegos"][0]["zonas"]["duracion_2"], 70)
        self.assertEqual(data["riegos"][0]["use_sensor_lluvia"], 1)
        self.assertTrue(data["auto_riego"])
        self.assertEqual(data["bateria"], 97)
        self.assertEqual(data["uart_reset_count"], 2)
        self.assertEqual(data["esp_reset_count"], 3)
        self.assertEqual(data["fw_version_esp"], "806")
        self.assertEqual(data["wifi_signal"], 82)
        self.assertEqual(data["ram_free"], 36972)

    async def test_patches_update_entities_and_remove_configuration(self) -> None:
        await self.snapshot()
        callback = MagicMock()
        self.client.register_callback(callback)
        await self.patch(15, [
            {"p": ["pic", "salidas", 1, "estado"], "v": 1},
            {"p": ["pic", "salidas", 1, "desc"], "d": True},
            {"p": ["pic", "salidas", 3, "tanque", "nivel"], "v": 1},
            {"p": ["pic", "riego", "lluvia"], "v": 1},
            {"p": ["pic", "fecha"], "v": "2026-11-05 19:10:10"},
            {"p": ["esp", "wifi", "sta", "rssi"], "v": -70},
        ])
        self.assertEqual(self.client.data["zones"][0]["estado"], 1)
        self.assertEqual(self.client.data["zones"][0]["label"], "Zona 1")
        self.assertEqual(self.client.data["tanks"][0]["nivel"], 1)
        self.assertTrue(self.client.data["lluvia_bloqueado"])
        self.assertEqual(self.client.data["pic_fecha"], "2026-11-05 19:10:10")
        self.assertEqual(self.client.data["wifi_signal"], 60)
        callback.assert_called_once()

        await self.patch(16, [
            {"p": ["pic", "salidas", 1], "v": {"tipo": 0, "estado": 0}},
            {"p": ["esp", "wifi", "sta", "ssid"], "d": True},
        ])
        self.assertEqual(self.client.data["zones"], {})
        self.assertNotIn("wifi_ssid", self.client.data)

    async def test_sequence_gap_requests_sync_and_disables_controls(self) -> None:
        self.client._ws = BlockingWebSocket()
        self.client._set_connected(True)
        await self.snapshot()
        callback = MagicMock()
        self.client.register_callback(callback)
        await self.patch(16, [{"p": ["pic", "salidas", 1, "estado"], "v": 1}])
        self.assertFalse(self.client.data_ready.is_set())
        callback.assert_called_once()
        self.assertEqual(
            json.loads(self.client._ws.send_str.call_args.args[0]),
            {"product": "chi", "device": "ABC123", "sync": True},
        )
        with self.assertRaises(HomeAssistantError):
            await self.client.set_zone_state(0, True)
        await self.snapshot(seq=17)
        self.assertTrue(self.client.data_ready.is_set())

    async def test_duplicate_patches_are_ignored_and_early_patches_are_queued(self) -> None:
        await self.patch(15, [{"p": ["pic", "salidas", 1, "estado"], "v": 1}])
        await self.snapshot()
        self.assertEqual(self.client.data["zones"][0]["estado"], 1)
        await self.patch(15, [{"p": ["pic", "salidas", 1, "estado"], "v": 0}])
        self.assertEqual(self.client.data["zones"][0]["estado"], 1)

    async def test_other_devices_and_products_do_not_replace_selected_chi(self) -> None:
        await self.snapshot()
        self.state["pic"]["salidas"] = []
        await self.snapshot(device="OTHER1")
        await self.snapshot(product="acueducto_adl")
        self.assertEqual(self.client.data["zones"][0]["slot_id"], 1)
        self.assertEqual(self.client.data["device_id"], "CHI/ABC123")

    async def test_offline_and_controller_faults_clear_availability(self) -> None:
        for field in ("online", "sin_respuesta", "pic_falla", "error_formato"):
            with self.subTest(field=field):
                self.state[field] = False if field == "online" else True
                await self.snapshot()
                self.assertFalse(self.client.data_ready.is_set())
                self.state.pop(field)
                await self.snapshot()
                self.assertTrue(self.client.data_ready.is_set())

    async def test_mini_and_identity_without_esp_data(self) -> None:
        self.state["mini"] = True
        self.state.pop("esp")
        await self.snapshot()
        self.assertTrue(self.client.data_ready.is_set())
        self.assertTrue(self.client.device_id_ready.is_set())
        self.assertEqual(self.client.data["device_id"], "CHI/ABC123")
        self.assertEqual(self.client.data["pic_name"], "CHI Smart Mini")

    async def test_refresh_requests_cloud_snapshot(self) -> None:
        await self.snapshot()
        self.client._ws = BlockingWebSocket()
        await self.client.refresh()
        self.assertEqual(
            json.loads(self.client._ws.send_str.call_args.args[0]),
            {"product": "chi", "device": "ABC123", "sync": True},
        )

    async def test_configuration_commands_preserve_unmodified_fields(self) -> None:
        await self.snapshot()
        self.client._ws = BlockingWebSocket()
        with patch("custom_components.hidromotic.client.asyncio.sleep", new=AsyncMock()):
            await self.client.set_tank_mode(0, False)
            await self.client.set_output_duration("pools", 0, 20)
            await self.client.set_riego_zona_duration(0, 0, 15)
        commands = [
            json.loads(call.args[0])["cmd"]
            for call in self.client._ws.send_str.await_args_list
        ]
        tank_config = commands[0]["config"]["salidas"]
        pool_config = commands[1]["config"]["salidas"]
        self.assertFalse(tank_config[3]["tanque_auto"])
        self.assertFalse(pool_config[3]["tanque_auto"])
        self.assertEqual(pool_config[5]["duracion"], 20)
        self.assertEqual(pool_config[1]["duracion"], 64)
        self.assertEqual(pool_config[1]["desc"], "Zona de prueba")
        self.assertTrue(pool_config[1]["bomba"])
        self.assertEqual(commands[2], {"config": {"riego": {
            "auto": True,
            "horarios": [{"i": 0, "habilitado": True, "hora": "20:00", "paridad": 0,
                          "dias": 127, "lluvia": True, "zonas_min": [15, 70]}],
        }}})

    async def test_existing_entry_selects_only_its_registered_device(self) -> None:
        self.client = HidromoticCloudClient(
            "account", "password", device_id="chi_abc123"
        )
        await self.snapshot(device="OTHER1")
        self.assertFalse(self.client.data_ready.is_set())
        await self.snapshot()
        self.assertTrue(self.client.data_ready.is_set())

    async def test_invalid_patch_requests_resync_without_partial_updates(self) -> None:
        await self.snapshot()
        self.client._ws = BlockingWebSocket()
        with self.assertLogs("custom_components.hidromotic.cloud_client", level="WARNING"):
            await self.patch(15, [
                {"p": ["pic", "salidas", 1, "estado"], "v": 1},
                {"p": ["pic", "salidas", -1], "v": {}},
            ])
        self.assertEqual(self.client.data["zones"][0]["estado"], 0)
        self.assertFalse(self.client.data_ready.is_set())
        self.assertTrue(json.loads(self.client._ws.send_str.call_args.args[0])["sync"])

    async def test_invalid_state_structure_is_reported_and_resynchronized(self) -> None:
        self.client._ws = BlockingWebSocket()
        for field in ("salidas", "horarios", "entradas", "bomba", "riego"):
            with self.subTest(field=field):
                original = self.state["pic"][field]
                self.state["pic"][field] = "invalid"
                with (
                    self.assertLogs("custom_components.hidromotic.cloud_client", level="WARNING"),
                    patch("custom_components.hidromotic.client.asyncio.sleep", new=AsyncMock()),
                ):
                    await self.snapshot()
                self.assertFalse(self.client.data_ready.is_set())
                self.state["pic"][field] = original

    async def test_duplicate_queued_patches_do_not_prevent_snapshot_publication(self) -> None:
        for _ in range(2):
            await self.patch(15, [{"p": ["pic", "salidas", 1, "estado"], "v": 1}])
        await self.patch(16, [{"p": ["pic", "riego", "lluvia"], "v": 1}])
        await self.snapshot()
        self.assertTrue(self.client.data_ready.is_set())
        self.assertEqual(self.client.data["zones"][0]["estado"], 1)
        self.assertTrue(self.client.data["lluvia_bloqueado"])

    async def test_gateway_configuration_errors_are_logged(self) -> None:
        self.state["config_estado"] = {"estado": "error", "detalle": "test rejection"}
        with self.assertLogs("custom_components.hidromotic.cloud_client", level="ERROR") as logs:
            await self.snapshot()
        self.assertIn("test rejection", "\n".join(logs.output))

    async def test_structured_schedule_change_keeps_optimistic_auto_setting(self) -> None:
        await self.snapshot()
        self.client._ws = BlockingWebSocket()
        with patch("custom_components.hidromotic.client.asyncio.sleep", new=AsyncMock()):
            await self.client.set_auto_riego(False)
            await self.client.set_riego_zona_duration(0, 0, 15)
        command = json.loads(self.client._ws.send_str.call_args.args[0])["cmd"]
        self.assertFalse(command["config"]["riego"]["auto"])

    async def test_patch_can_replace_root_create_paths_and_delete_array_slots(self) -> None:
        await self.snapshot()
        await self.patch(15, [
            {"p": ["new", "list", 0, "value"], "v": 1},
            {"p": ["pic", "salidas", 1], "d": True},
        ])
        self.assertEqual(self.client._state["new"]["list"][0]["value"], 1)
        self.assertEqual(self.client.data["zones"], {})
        self.assertEqual(self.client.data["pools"][0]["slot_id"], 5)
        self.state["mini"] = True
        await self.patch(16, [{"p": [], "v": self.state}])
        self.assertTrue(self.client.data["is_mini"])
        self.assertEqual(self.client.data["zones"][0]["slot_id"], 1)

    async def test_ciclon_and_task_fields_are_translated(self) -> None:
        self.state["pic"]["salidas"].append({
            "tipo": 0x61, "estado": 1, "ciclon": {
                "modo_ante_tareas": 1, "d_ante_tareas_s": 20,
                "modo_fin_de_tareas": 0, "d_fin_de_tareas_s": 5,
                "modo_tiempo": 1, "bomba_marcha_duracion_min": 60,
            },
        })
        self.state["pic"]["tareas"] = [
            {"tipo": 0x41, "modulo": "Z1", "modo": 0, "restante": 15},
        ]
        await self.snapshot()
        self.assertEqual(self.client.data["ciclon"][0]["d_ante_tareas"], 20)
        self.assertEqual(self.client.data["ciclon"][0]["bomba_marcha_duracion"], 60)
        self.assertEqual(self.client.data["tareas"][0]["duracion"], 15)

    async def test_reconnect_discards_previous_sequence_but_keeps_device_selection(self) -> None:
        await self.snapshot(seq=100)
        session = MagicMock()
        session.post.return_value = FakeResponse()
        session.ws_connect = AsyncMock(return_value=BlockingWebSocket())
        self.client._session = session
        self.client._owns_session = False
        try:
            self.assertTrue(await self.client.connect())
            self.assertFalse(self.client.data_ready.is_set())
            await self.snapshot(seq=1, device="OTHER1")
            self.assertFalse(self.client.data_ready.is_set())
            await self.snapshot(seq=1)
            self.assertTrue(self.client.data_ready.is_set())
        finally:
            await self.client.disconnect()

    async def test_cloud_session_with_real_http_and_websocket_transports(self) -> None:
        updated = asyncio.Event()
        received_commands = []

        async def login(request: web.Request) -> web.Response:
            self.assertEqual(
                dict(await request.post()), {"login": "account", "password": "password"}
            )
            response = web.HTTPSeeOther(location="/")
            response.set_cookie("session", "test-session", httponly=True, path="/")
            raise response

        async def websocket(request: web.Request) -> web.WebSocketResponse:
            self.assertEqual(request.cookies.get("session"), "test-session")
            self.assertEqual(request.headers.get("Origin"), "https://hidromotic.com")
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({
                "product": "chi", "device": "ABC123", "kind": "state",
                "data": {"seq": 14, "state": self.state},
            })
            async for message in ws:
                received_commands.append(json.loads(message.data))
                await ws.send_json({
                    "product": "chi", "device": "ABC123", "kind": "patch",
                    "data": {"seq": 15, "ops": [
                        {"p": ["pic", "salidas", 1, "estado"], "v": 1},
                    ]},
                })
            return ws

        app = web.Application()
        app.router.add_post("/login", login)
        app.router.add_get("/ws", websocket)
        async with (
            TestServer(app) as server,
            aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session,
        ):
            client = HidromoticCloudClient("account", "password", session=session)
            client.LOGIN_URL = str(server.make_url("/login"))
            client.WEBSOCKET_URL = str(server.make_url("/ws"))
            client.register_callback(
                lambda data: updated.set()
                if data.get("zones", {}).get(0, {}).get("estado") == 1 else None
            )
            try:
                self.assertTrue(await client.connect())
                await asyncio.wait_for(client.data_ready.wait(), timeout=2)
                await client.set_zone_state(0, True)
                await asyncio.wait_for(updated.wait(), timeout=2)
                self.assertEqual(received_commands, [
                    {"product": "chi", "device": "ABC123", "cmd": "#@S1M1;"},
                ])
            finally:
                await client.disconnect()
