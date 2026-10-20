"""WebSocket client for Hidromotic CHI Smart irrigation controllers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import logging
from typing import Any

import aiohttp

from .const import (
    OUTPUT_TYPE_TANQUE,
    OUTPUT_TYPE_ZONA,
    OUTPUT_TYPE_MANGUERA,
    OUTPUT_TYPE_PISCINA,
    OUTPUT_TYPE_CICLON,
    STATE_DISABLED,
    TANK_EMPTY,
    TANK_FULL,
    TANK_LEVEL_FAIL,
    TANK_MEDIUM,
    TANK_SENSOR_FAIL,
)

_LOGGER = logging.getLogger(__name__)


def hex_to_int(h: str) -> int:
    """Convert hex character to int (handles A, B, C for 10, 11, 12)."""
    if h == "A":
        return 10
    if h == "B":
        return 11
    if h == "C":
        return 12
    return int(h)


def int_to_hex(i: int) -> str:
    """Convert int to hex character (handles 10, 11, 12 as A, B, C)."""
    if i == 10:
        return "A"
    if i == 11:
        return "B"
    if i == 12:
        return "C"
    return str(i)


class HidromoticClient:
    """WebSocket client for Hidromotic device."""

    RECONNECT_INTERVAL = 30  # seconds

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the client."""
        self.host = host
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session = session
        self._owns_session = session is None
        self._callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._connected = False
        self._should_reconnect = True
        self._reconnect_task: asyncio.Task[None] | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._data: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Return if connected to device."""
        return self._connected

    @property
    def data(self) -> dict[str, Any]:
        """Return current device data."""
        return self._data

    def register_callback(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Register a callback for data updates."""
        self._callbacks.append(callback)
        return lambda: self._callbacks.remove(callback)

    async def connect(self) -> bool:
        """Connect to the device."""
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()
                self._owns_session = True

            url = f"ws://{self.host}/rpc"
            _LOGGER.debug("Connecting to %s", url)
            self._ws = await self._session.ws_connect(url, heartbeat=30)
            self._connected = True
            _LOGGER.info("Connected to Hidromotic at %s", self.host)

            self._listener_task = asyncio.create_task(self._listen())
            await self._send_command("e")
            await asyncio.sleep(1)
            await self._send_command("#@C;")
        except Exception as err:
            _LOGGER.error("Failed to connect to Hidromotic: %s", err)
            self._connected = False
            return False
        else:
            return True

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        self._should_reconnect = False
        self._connected = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
        if self._session and self._owns_session:
            await self._session.close()
            self._session = None

    async def _send_command(self, command: str) -> None:
        """Send a command to the device using JSON-RPC format."""
        if not self._ws or self._ws.closed:
            _LOGGER.warning("Cannot send command, not connected")
            return
        
        async with self._lock:
            if command.startswith("#"):
                payload = f'{{"method":"hdmt","params":{{"c":"{command}"}}}}'
            else:
                payload = f'{{"id":1111,"method":"hdmt","params":{{"c":"{command}"}}}}'
            
            _LOGGER.debug("Sending command: %s", payload)
            
            try:
                # CORRECCIÓN DEADLOCK: Timeout de 5 segundos para liberar el lock si la red falla
                await asyncio.wait_for(self._ws.send_str(payload), timeout=5.0)
            except TimeoutError:
                _LOGGER.error("Timeout sending command to Hidromotic. Disconnecting to force recovery.")
                await self._ws.close()
            except Exception as err:
                _LOGGER.error("Error sending command to Hidromotic: %s", err)

    async def _listen(self) -> None:
        """Listen for messages from the device."""
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    await self._process_binary(msg.data)
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    await self._process_text(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("WebSocket error: %s", msg.data)
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    _LOGGER.info("WebSocket closed")
                    break
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.error("Error in WebSocket listener: %s", err)
        finally:
            self._connected = False
            if self._should_reconnect:
                self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """Attempt to reconnect to the device."""
        while self._should_reconnect and not self._connected:
            _LOGGER.info(
                "Attempting to reconnect to Hidromotic in %d seconds",
                self.RECONNECT_INTERVAL,
            )
            await asyncio.sleep(self.RECONNECT_INTERVAL)
            if not self._should_reconnect:
                break
            try:
                if await self.connect():
                    _LOGGER.info("Reconnected to Hidromotic")
                    break
            except Exception as err:
                _LOGGER.debug("Reconnection attempt failed: %s", err)

    async def _process_text(self, data: str) -> None:
        """Process text message (JSON)."""
        try:
            parsed = json.loads(data)
            _LOGGER.debug("Received JSON: %s", parsed)
        except json.JSONDecodeError:
            _LOGGER.debug("Non-JSON text received: %s", data)

    async def _process_binary(self, data: bytes) -> None:
        """Process binary message from device."""
        if len(data) < 2:
            return

        cmd = chr(data[0])
        _LOGGER.debug("Processing binary command: %s, length: %d, data:%s", cmd, len(data), data)

        if cmd == "C":
            await self._parse_full_config(data)
        elif cmd == "D":
            await self._parse_running_data(data)

        for callback in self._callbacks:
            try:
                callback(self._data)
            except Exception as err:
                _LOGGER.error("Error in callback: %s", err)

    async def _parse_full_config(self, data: bytes) -> None:
        """Parse full configuration data (command 'C')."""
        is_mini = data[1] == 77  # 'M' = 77
        max_outputs = 6 if is_mini else 12

        self._data["is_mini"] = is_mini
        self._data["pic_version"] = data[2] | (data[3] << 8)
        self._data["pic_id"] = f"0x{data[6]:02X}"

        self._data["zones"] = {}
        self._data["tanks"] = {}
        self._data["pools"] = {}
        self._data["mangueras"] = {}
        self._data["ciclon"] = {}
        self._data["pump"] = {}
        self._data["riegos"] = {}
        self._data["outputs"] = {}

        etc = ""
        nivel = ""
        modo = ""

        if "auto_riego" not in self._data:
            self._data["auto_riego"] = True

        b_pos = None
        s_pos = None
        r_pos = None
        for idx in range(16, len(data)):
            if data[idx] == 0x42 and b_pos is None:
                b_pos = idx
            elif data[idx] == 0x53 and s_pos is None:
                s_pos = idx
                break

        if b_pos is not None and b_pos + 2 < len(data):
            self._data["pump"] = {
                "estado": data[b_pos + 1],
                "pausa_externa": data[b_pos + 2],
            }

        if s_pos is None:
            _LOGGER.warning("No 'S' section marker found in config data")
            return

        i = s_pos + 1
        slot_id = 0

        while i < len(data) - 6 and slot_id < max_outputs:
            tipo = data[i]

            if tipo == 0x00:
                i += 6
                slot_id += 1
                continue

            is_zone = 0x41 <= tipo <= 0x4C
            is_tank = 0x21 <= tipo <= 0x2C
            is_pileta = 0x51 <= tipo <= 0x5C
            is_manguera = 0x11 <= tipo <= 0x1C
            is_ciclon = 0x61 <= tipo <= 0x6C

            if not (is_zone or is_tank or is_pileta or is_manguera or is_ciclon):
                # CORRECCIÓN LIVELOCK: Avanzar el índice antes del continue
                i += 1
                continue

            if i + 5 >= len(data):
                break

            bomba = data[i + 1]
            duracion = data[i + 2] | (data[i + 3] << 8)
            estado = data[i + 4]
            label_len = data[i + 5]

            if bomba > 1 or estado > STATE_DISABLED:
                # CORRECCIÓN LIVELOCK: Avanzar el índice antes del continue
                i += 1
                continue

            label = ""
            if 0 < label_len <= 32 and i + 6 + label_len <= len(data):
                try:
                    label = data[i + 6 : i + 6 + label_len].decode("utf-8", errors="ignore")
                except UnicodeDecodeError:
                    label = ""
                    label_len = 0
            else:
                label_len = 0

            if is_tank and not (estado == STATE_DISABLED):
                modo = data[i + 6 + label_len]
                etc = data[i + 6 + label_len + 1]
                nivel = data[i + 6 + label_len + 2]

            if is_ciclon and not (estado == STATE_DISABLED):
                automatico_tareas_enabled = data[i + 6 + label_len]
                automatico_fin_tareas_enabled = data[i + 6 + label_len + 1]
                automatico_tiempo_bomba_enabled = data[i + 6 + label_len + 2]
                automatico_tareas = data[i + 6 + label_len + 3] | (data[i + 6 + label_len + 4] << 8)
                automatico_fin_tareas = data[i + 6 + label_len + 5]
                automatico_tiempo_bomba = data[i + 6 + label_len + 6] | (data[i + 6 + label_len + 7] << 8)

            tipo_id = (tipo & 0x0F) - 1

            output_data = {
                "id": tipo_id,
                "slot_id": slot_id,
                "tipo": f"{tipo:02X}",
                "bomba": bomba,
                "duracion": duracion,
                "estado": estado,
                "label": label,
            }

            header_size = 9 if is_tank else 6
            if is_ciclon:
                header_size = 16

            if estado == STATE_DISABLED:
                header_size = 6

            i += header_size + label_len
            slot_id += 1

            if estado == STATE_DISABLED:
                continue

            self._data["outputs"][slot_id] = output_data

            if is_zone:
                self._data["zones"][tipo_id] = {
                    "id": tipo_id,
                    "slot_id": output_data["slot_id"],
                    "estado": estado,
                    "label": label or f"Zone {tipo_id + 1}",
                    "duracion": duracion,
                }
            elif is_tank:
                self._data["tanks"][tipo_id] = {
                    "id": tipo_id,
                    "slot_id": output_data["slot_id"],
                    "estado": estado,
                    "label": label or f"Tank {tipo_id + 1}",
                    "nivel": nivel,
                    "modo": modo,
                    "etc": etc,
                }
            elif is_pileta:
                self._data["pools"][tipo_id] = {
                    "id": tipo_id,
                    "slot_id": output_data["slot_id"],
                    "estado": estado,
                    "label": label or f"Pool {tipo_id + 1}",
                    "duracion": duracion,
                }
            elif is_manguera:
                self._data["mangueras"][tipo_id] = {
                    "id": tipo_id,
                    "slot_id": output_data["slot_id"],
                    "estado": estado,
                    "label": label or f"Manguera {tipo_id + 1}",
                    "duracion": duracion,
                }
            elif is_ciclon:
                self._data["ciclon"][tipo_id] = {
                    "id": tipo_id,
                    "slot_id": output_data["slot_id"],
                    "estado": estado,
                    "label": label or f"Ciclon {tipo_id + 1}",
                    "duracion": duracion,
                    "automatico_tareas_enabled": automatico_tareas_enabled,
                    "automatico_fin_tareas_enabled": automatico_fin_tareas_enabled,
                    "automatico_tiempo_bomba_enabled": automatico_tiempo_bomba_enabled,
                    "automatico_tareas": automatico_tareas,
                    "automatico_fin_tareas": automatico_fin_tareas,
                    "automatico_tiempo_bomba": automatico_tiempo_bomba,
                }

        for idx in range(i, len(data)):
            if data[idx] == 0x52 and r_pos is None:
                r_pos = idx
                break

        if r_pos is not None and r_pos + 1 < len(data):
            self._data["auto_riego"] = data[r_pos + 1] == 1

        header_size = 40

        while i < len(data):
            tipo_riego = data[i]

            if tipo_riego != 0x48:
                i += header_size
                continue

            riego_id = data[i + 1]
            riego_estado = data[i + 2]
            riego_enabled = data[i + 10]
            riego_label = "Riego " + chr(65 + riego_id)
            riego_use_sensor_lluvia = data[i + 9]

            if tipo_riego == 0x48:
                self._data["riegos"][riego_id] = {
                    "id": riego_id,
                    "slot_id": riego_id,
                    "estado": riego_estado,
                    "enabled": riego_enabled,
                    "label": riego_label,
                    "use_sensor_lluvia": riego_use_sensor_lluvia,
                    "duracion_1": data[i + 15] | (data[i + 16] << 8),
                    "duracion_2": data[i + 17] | (data[i + 18] << 8),
                    "duracion_3": data[i + 19] | (data[i + 20] << 8),
                    "duracion_4": data[i + 21] | (data[i + 22] << 8),
                    "duracion_5": data[i + 23] | (data[i + 24] << 8),
                    "duracion_6": data[i + 25] | (data[i + 26] << 8),
                    "duracion_7": data[i + 27] | (data[i + 28] << 8),
                    "duracion_8": data[i + 29] | (data[i + 30] << 8),
                    "duracion_9": data[i + 31] | (data[i + 32] << 8),
                    "duracion_10": data[i + 33] | (data[i + 34] << 8),
                    "duracion_11": data[i + 35] | (data[i + 36] << 8),
                    "duracion_12": data[i + 37] | (data[i + 38] << 8),
                }

            i += header_size

    async def _parse_running_data(self, data: bytes) -> None:
        """Parse running data update (command 'D')."""
        i = 6
        while i < len(data):
            section = chr(data[i])

            if section == "B":
                self._data["pump"]["estado"] = data[i + 1]
                self._data["pump"]["pausa_externa"] = data[i + 2]
                i += 6

            elif section == "R":
                if i + 1 < len(data):
                    self._data["auto_riego"] = data[i + 1] == 1
                i += 2

            elif section == "S":
                if i + 2 < len(data):
                    tipo = data[i + 1]
                    estado = data[i + 2]
                    for output in self._data.get("outputs", {}).values():
                        if int(output["tipo"], 16) == tipo:
                            output["estado"] = estado
                            tipo_upper = tipo & 0xF0
                            tipo_id = (tipo & 0x0F) - 1
                            if tipo_upper == OUTPUT_TYPE_ZONA and tipo_id in self._data.get("zones", {}):
                                self._data["zones"][tipo_id]["estado"] = estado
                            elif tipo_upper == OUTPUT_TYPE_TANQUE and tipo_id in self._data.get("tanks", {}):
                                self._data["tanks"][tipo_id]["estado"] = estado
                                if i + 3 < len(data):
                                    self._data["tanks"][tipo_id]["nivel"] = data[i + 3]
                            elif tipo_upper == OUTPUT_TYPE_PISCINA and tipo_id in self._data.get("pools", {}):
                                self._data["pools"][tipo_id]["estado"] = estado
                            elif tipo_upper == OUTPUT_TYPE_MANGUERA and tipo_id in self._data.get("mangueras", {}):
                                self._data["mangueras"][tipo_id]["estado"] = estado
                            elif tipo_upper == OUTPUT_TYPE_CICLON and tipo_id in self._data.get("ciclon", {}):
                                self._data["ciclon"][tipo_id]["estado"] = estado
                            break
                i += 3
            elif section == "H":
                if i + 2 < len(data):
                    riego_id = data[i + 1]
                    estado = data[i + 2]

                    if riego_id in self._data.get("riegos", {}):
                        self._data["riegos"][riego_id]["estado"] = estado

                i += 3
            else:
                i += 1

    async def _set_output_state(self, entity_type: str, entity_id: int, on: bool) -> None:
        """Generic method to turn an output on or off."""
        entity = self._data.get(entity_type, {}).get(entity_id)
        if not entity:
            _LOGGER.warning("%s %d not found", entity_type.capitalize(), entity_id)
            return

        slot_id = entity["slot_id"]
        state = 1 if on else 0
        command = f"#@S{int_to_hex(slot_id)}M{state};"
        
        await self._send_command(command)

    async def set_zone_state(self, zone_id: int, on: bool) -> None:
        """Turn a zone on or off."""
        await self._set_output_state("zones", zone_id, on)

    async def set_tank_state(self, tank_id: int, on: bool) -> None:
        """Turn a tank on or off."""
        await self._set_output_state("tanks", tank_id, on)

    async def set_pool_state(self, pool_id: int, on: bool) -> None:
        """Turn a pool on or off."""
        await self._set_output_state("pools", pool_id, on)

    async def set_manguera_state(self, manguera_id: int, on: bool) -> None:
        """Turn a manguera on or off."""
        await self._set_output_state("mangueras", manguera_id, on)

    async def set_riego_state(self, riego_id: int, on: bool) -> None:
        """Turn a riego on or off."""
        riego = self._data.get("riegos", {}).get(riego_id)
        if not riego:
            return

        slot_id = riego["slot_id"]
        state = 1 if on else 0
        command = f"#@H{int_to_hex(slot_id)}M{state};"
        await self._send_command(command)

    async def set_auto_riego(self, on: bool) -> None:
        """Enable or disable automatic irrigation."""
        state = 1 if on else 0
        command = f"#@RA{state};"
        await self._send_command(command)
        self._data["auto_riego"] = on
        for callback in self._callbacks:
            try:
                callback(self._data)
            except Exception as err:
                _LOGGER.error("Error in callback: %s", err)

    async def refresh(self) -> None:
        """Request fresh data from device."""
        await self._send_command("#@C;")

    def get_zones(self) -> dict[int, dict[str, Any]]:
        return self._data.get("zones", {})

    def get_tanks(self) -> dict[int, dict[str, Any]]:
        return self._data.get("tanks", {})

    def get_pools(self) -> dict[int, dict[str, Any]]:
        return self._data.get("pools", {})

    def get_mangueras(self) -> dict[int, dict[str, Any]]:
        return self._data.get("mangueras", {})

    def get_riegos(self) -> dict[int, dict[str, Any]]:
        return self._data.get("riegos", {})

    def get_pump(self) -> dict[str, Any]:
        return self._data.get("pump", {})

    def is_auto_riego_on(self) -> bool:
        return self._data.get("auto_riego", False)

    def is_zone_on(self, zone_id: int) -> bool:
        zone = self._data.get("zones", {}).get(zone_id)
        if zone:
            return zone.get("estado", 0) == 1
        return False

    def is_tank_full(self, tank_id: int) -> bool:
        tank = self._data.get("tanks", {}).get(tank_id)
        if tank:
            return tank.get("nivel", 0xFF) == TANK_FULL
        return False

    def is_tank_empty(self, tank_id: int) -> bool:
        tank = self._data.get("tanks", {}).get(tank_id)
        if tank:
            return tank.get("nivel", 0xFF) == TANK_EMPTY
        return False

    def get_tank_level(self, tank_id: int) -> str:
        tank = self._data.get("tanks", {}).get(tank_id)
        if not tank:
            return "unknown"
        nivel = tank.get("nivel", 0xFF)
        if nivel == TANK_FULL:
            return "full"
        if nivel == TANK_EMPTY:
            return "empty"
        if nivel == TANK_SENSOR_FAIL:
            return "sensor_fail"
        if nivel == TANK_LEVEL_FAIL:
            return "level_fail"
        if nivel == TANK_MEDIUM:
            return "medium"
        return "unknown"