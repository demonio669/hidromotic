"""WebSocket client for Hidromotic CHI Smart irrigation controllers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import logging
from typing import Any

import aiohttp

from .const import (
    OUTPUT_TYPE_CICLON,
    OUTPUT_TYPE_MANGUERA,
    OUTPUT_TYPE_PISCINA,
    OUTPUT_TYPE_TANQUE,
    OUTPUT_TYPE_ZONA,
    STATE_DISABLED,
    TANK_EMPTY,
    TANK_FULL,
    TANK_LEVEL_FAIL,
    TANK_MEDIUM,
    TANK_SENSOR_FAIL,
)

_LOGGER = logging.getLogger(__name__)

# Mapeo oficial de funciones para las 4 Entradas Físicas Digitales (E0 - E3)
INPUT_TYPE_MAP = {
    0: "Ninguna",
    1: "Detector de agua",
    2: "Sensor de Lluvia",
    3: "Tanque 1 vacío",
    4: "Tanque 1 lleno",
    5: "Tanque 2 vacío",
    6: "Tanque 2 lleno",
    7: "Tanque 3 vacío",
    8: "Tanque 3 lleno",
    9: "Tanque 4 vacío",
    10: "Tanque 4 lleno",
    11: "Pausa-SÍ",
    12: "Pausa-NO",
}


def hex_to_int(h: str) -> int:
    """Convierte un carácter hexadecimal a entero."""
    if h == "A":
        return 10
    if h == "B":
        return 11
    if h == "C":
        return 12
    return int(h)


def int_to_hex(i: int) -> str:
    """Convierte un entero a carácter hexadecimal."""
    if i == 10:
        return "A"
    if i == 11:
        return "B"
    if i == 12:
        return "C"
    return str(i)


class HidromoticClient:
    """Cliente WebSocket asíncrono para la comunicación con la controladora Hidromotic."""

    RECONNECT_INTERVAL = 30

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Inicializa los atributos del cliente."""
        self.host = host
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session = session
        self._owns_session = session is None
        self._callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._connected = False
        self._should_reconnect = True
        self._reconnect_task: asyncio.Task[None] | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._data: dict[str, Any] = {"c_msg": 0}

        self.data_ready = asyncio.Event()
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Retorna True si el WebSocket está actualmente conectado."""
        return self._connected

    @property
    def data(self) -> dict[str, Any]:
        """Retorna el diccionario estructurado con los datos del dispositivo."""
        return self._data

    def register_callback(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Registra un callback para notificar cambios de estado a Home Assistant."""
        self._callbacks.append(callback)
        return lambda: self._callbacks.remove(callback)

    async def connect(self) -> bool:
        """Establece la conexión WebSocket con la controladora."""
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
            await self._send_command("#@C;")
        except Exception as err:
            _LOGGER.error("Failed to connect to Hidromotic: %s", err)
            self._connected = False
            return False
        else:
            return True

    async def disconnect(self) -> None:
        """Cierra la conexión WebSocket y cancela las tareas activas."""
        self._should_reconnect = False
        self._connected = False
        self.data_ready.clear()

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
        """Envía un comando en formato JSON-RPC al WebSocket."""
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
                await asyncio.wait_for(self._ws.send_str(payload), timeout=5.0)
            except TimeoutError:
                _LOGGER.error("Timeout sending command '%s' to Hidromotic", command)
            except Exception as err:
                _LOGGER.error("Error sending command to Hidromotic: %s", err)

    async def _listen(self) -> None:
        """Bucle principal para procesar los mensajes recibidos."""
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                self._data["c_msg"] = self._data.get("c_msg", 0) + 1
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
            self.data_ready.clear()
            if self._should_reconnect:
                self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """Bucle para gestionar los reintentos automáticos de reconexión."""
        self.data_ready.clear()
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
        """Procesa respuestas recibidas en formato JSON extrayendo información del sistema."""
        try:
            parsed = json.loads(data)
            _LOGGER.debug("Received JSON: %s", parsed)

            if isinstance(parsed, dict):
                result = parsed.get("result", parsed)
                if isinstance(result, dict):
                    if "id" in result:
                        self._data["device_id"] = result.get("id")
                    if "fw_version" in result:
                        self._data["fw_version_esp"] = result.get("fw_version")
                    if "ota" in result:
                        self._data["ota"] = result.get("ota")
                    if "uptime" in result:
                        self._data["uptime"] = result.get("uptime", 0)
                    if "mac" in result:
                        self._data["mac"] = result.get("mac", "unknown")

                    wifi_data = result.get("wifi", {}).get("sta", {})
                    if "ssid" in wifi_data:
                        self._data["wifi_ssid"] = wifi_data.get("ssid")
                    if "ip" in wifi_data:
                        self._data["wifi_ip"] = wifi_data.get("ip")
                    if "rssi" in wifi_data:
                        rssi = wifi_data.get("rssi", -100)
                        if rssi == 0 or rssi <= -100:
                            signal = 0
                        elif rssi >= -50:
                            signal = 100
                        else:
                            signal = 2 * (rssi + 100)
                        self._data["wifi_signal"] = signal
                    if "routertime" in wifi_data:
                        self._data["wifi_routertime"] = wifi_data.get("routertime", 0)
        except json.JSONDecodeError:
            _LOGGER.debug("Non-JSON text received: %s", data)

    async def _process_binary(self, data: bytes) -> None:
        """Procesa tramas de datos binarios garantizando exclusión mutua."""
        if len(data) < 2:
            return

        cmd = chr(data[0])
        _LOGGER.debug("Processing binary command: %s, length: %d", cmd, len(data))

        async with self._lock:
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
        """Parsea la trama binaria inicial con la configuración completa del sistema."""
        is_mini = data[1] == 77
        max_outputs = 6 if is_mini else 12

        self._data["is_mini"] = is_mini
        self._data["pic_name"] = "CHI Smart Mini" if is_mini else "CHI Smart"
        self._data["pic_version"] = data[2] | (data[3] << 8)
        self._data["pic_id"] = f"0x{data[6]:02X}"
        self._data["pic_rev"] = data[7] if len(data) > 7 else 0

        # Sincronización BCD de Fecha PIC
        if len(data) >= 16:
            bcd_to_hex = lambda v: (((v & 0xF0) >> 4) * 10) + (v & 0x0F)
            try:
                year = 2000 + bcd_to_hex(data[10])
                month = bcd_to_hex(data[9])
                day = bcd_to_hex(data[12])
                hour = bcd_to_hex(data[14])
                minute = bcd_to_hex(data[13])
                second = bcd_to_hex(data[15])
                self._data["pic_fecha"] = f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
            except Exception:
                self._data["pic_fecha"] = "unknown"

        self._data["zones"] = {}
        self._data["tanks"] = {}
        self._data["pools"] = {}
        self._data["mangueras"] = {}
        self._data["ciclon"] = {}
        self._data["pump"] = {}
        self._data["riegos"] = {}
        self._data["inputs"] = {}
        self._data["outputs"] = {}
        self._data["outputs_by_tipo"] = {}

        if "auto_riego" not in self._data:
            self._data["auto_riego"] = True

        b_pos, s_pos, e_pos, r_pos = None, None, None, None

        for idx in range(16, len(data)):
            if data[idx] == 0x42 and b_pos is None:
                b_pos = idx
            elif data[idx] == 0x45 and e_pos is None:
                e_pos = idx
            elif data[idx] == 0x53 and s_pos is None:
                s_pos = idx
                break

        if b_pos is not None and b_pos + 6 < len(data):
            marcha = (
                data[b_pos + 3]
                | (data[b_pos + 4] << 8)
                | (data[b_pos + 5] << 16)
                | (data[b_pos + 6] << 24)
            )
            self._data["pump"] = {
                "estado": data[b_pos + 1],
                "pausa_externa": data[b_pos + 2],
                "marcha": marcha,
            }

        if e_pos is not None:
            idx = e_pos + 1
            for j in range(4):
                if idx + 3 < len(data):
                    tipo = data[idx]
                    invert = data[idx + 1]
                    actual = data[idx + 2]
                    estado = data[idx + 3]

                    self._data["inputs"][j] = {
                        "id": j,
                        "tipo": tipo,
                        "tipo_name": INPUT_TYPE_MAP.get(tipo, f"Tipo {tipo}"),
                        "invert": invert == 1,
                        "actual": actual,
                        "estado": estado == 1,
                    }
                    idx += 4

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
                i += 1
                continue

            if i + 5 >= len(data):
                break

            bomba = data[i + 1]
            duracion = data[i + 2] | (data[i + 3] << 8)
            estado = data[i + 4]
            label_len = data[i + 5]

            if bomba > 1 or estado > STATE_DISABLED:
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

            modo, etc, nivel = 0, 0, 0
            automatico_tareas_enabled = 0
            automatico_fin_tareas_enabled = 0
            automatico_tiempo_bomba_enabled = 0
            automatico_tareas = 0
            automatico_fin_tareas = 0
            automatico_tiempo_bomba = 0

            if is_tank and estado != STATE_DISABLED:
                if i + 6 + label_len + 2 < len(data):
                    modo = data[i + 6 + label_len]
                    etc = data[i + 6 + label_len + 1]
                    nivel = data[i + 6 + label_len + 2]

            if is_ciclon and estado != STATE_DISABLED:
                if i + 6 + label_len + 7 < len(data):
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
                "tipo_raw": tipo,
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
            self._data["outputs_by_tipo"][tipo] = output_data

            if is_zone:
                self._data["zones"][tipo_id] = {
                    "id": tipo_id,
                    "slot_id": output_data["slot_id"],
                    "estado": estado,
                    "label": label or f"Zona {tipo_id + 1}",
                    "duracion": duracion,
                }
            elif is_tank:
                self._data["tanks"][tipo_id] = {
                    "id": tipo_id,
                    "slot_id": output_data["slot_id"],
                    "estado": estado,
                    "label": label or f"Tanque {tipo_id + 1}",
                    "nivel": nivel,
                    "modo": modo,
                    "etc": etc,
                }
            elif is_pileta:
                self._data["pools"][tipo_id] = {
                    "id": tipo_id,
                    "slot_id": output_data["slot_id"],
                    "estado": estado,
                    "label": label or f"Piscina {tipo_id + 1}",
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
            elif data[idx] == 0x62 and "bateria" not in self._data:
                if idx + 2 < len(data):
                    self._data["bateria"] = data[idx + 1] | (data[idx + 2] << 8)

        if r_pos is not None and r_pos + 1 < len(data):
            self._data["auto_riego"] = data[r_pos + 1] == 1

        riego_header_size = 28 if is_mini else 40
        max_riego_zonas = 6 if is_mini else 12

        while i < len(data):
            tipo_riego = data[i]

            if tipo_riego != 0x48:
                i += 1
                continue

            if i + (26 if is_mini else 38) < len(data):
                riego_id = data[i + 1]
                riego_estado = data[i + 2]
                riego_enabled = data[i + 10]
                riego_label = f"Riego {chr(65 + riego_id)}"
                riego_use_sensor_lluvia = data[i + 9]

                zonas_duracion = {}
                for z_idx in range(max_riego_zonas):
                    pos = i + 15 + (z_idx * 2)
                    if pos + 1 < len(data):
                        zonas_duracion[f"duracion_{z_idx + 1}"] = data[pos] | (data[pos + 1] << 8)

                label_offset = i + (26 if is_mini else 38) + 1
                if label_offset < len(data) and data[label_offset] > 0:
                    custom_label_len = data[label_offset]
                    if label_offset + 1 + custom_label_len <= len(data):
                        try:
                            custom_label = data[label_offset + 1 : label_offset + 1 + custom_label_len].decode("utf-8", errors="ignore")
                            if custom_label.strip():
                                riego_label = custom_label
                        except UnicodeDecodeError:
                            pass

                self._data["riegos"][riego_id] = {
                    "id": riego_id,
                    "slot_id": riego_id,
                    "estado": riego_estado,
                    "enabled": riego_enabled,
                    "label": riego_label,
                    "use_sensor_lluvia": riego_use_sensor_lluvia,
                    "zonas": zonas_duracion,
                }

            i += riego_header_size

        self.data_ready.set()

    async def _parse_running_data(self, data: bytes) -> None:
        """Parsea actualizaciones parciales en tiempo real enviadas por la placa."""
        i = 6
        while i < len(data):
            section = chr(data[i])

            if section == "B":
                if i + 6 < len(data):
                    self._data["pump"]["estado"] = data[i + 1]
                    self._data["pump"]["pausa_externa"] = data[i + 2]
                    self._data["pump"]["marcha"] = (
                        data[i + 3]
                        | (data[i + 4] << 8)
                        | (data[i + 5] << 16)
                        | (data[i + 6] << 24)
                    )
                elif i + 2 < len(data):
                    self._data["pump"]["estado"] = data[i + 1]
                    self._data["pump"]["pausa_externa"] = data[i + 2]
                i += 6

            elif section == "b":
                if i + 2 < len(data):
                    self._data["bateria"] = data[i + 1] | (data[i + 2] << 8)
                i += 2

            elif section == "E":
                if i + 2 < len(data):
                    input_id = data[i + 1]
                    estado = data[i + 2]
                    if input_id in self._data.get("inputs", {}):
                        self._data["inputs"][input_id]["estado"] = estado == 1
                i += 3

            elif section == "R":
                if i + 1 < len(data):
                    self._data["auto_riego"] = data[i + 1] == 1
                i += 2

            elif section == "S":
                step = 3
                if i + 2 < len(data):
                    tipo = data[i + 1]
                    estado = data[i + 2]

                    output = self._data.get("outputs_by_tipo", {}).get(tipo)
                    if output:
                        output["estado"] = estado
                        tipo_upper = tipo & 0xF0
                        tipo_id = (tipo & 0x0F) - 1

                        if tipo_upper == OUTPUT_TYPE_ZONA and tipo_id in self._data.get("zones", {}):
                            self._data["zones"][tipo_id]["estado"] = estado
                        elif tipo_upper == OUTPUT_TYPE_TANQUE and tipo_id in self._data.get("tanks", {}):
                            self._data["tanks"][tipo_id]["estado"] = estado
                            if i + 3 < len(data):
                                self._data["tanks"][tipo_id]["nivel"] = data[i + 3]
                                step = 4
                        elif tipo_upper == OUTPUT_TYPE_PISCINA and tipo_id in self._data.get("pools", {}):
                            self._data["pools"][tipo_id]["estado"] = estado
                        elif tipo_upper == OUTPUT_TYPE_MANGUERA and tipo_id in self._data.get("mangueras", {}):
                            self._data["mangueras"][tipo_id]["estado"] = estado
                        elif tipo_upper == OUTPUT_TYPE_CICLON and tipo_id in self._data.get("ciclon", {}):
                            self._data["ciclon"][tipo_id]["estado"] = estado
                i += step

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
        """Cambia el estado de una salida física especificando su tipo e id."""
        entity = self._data.get(entity_type, {}).get(entity_id)
        if not entity:
            _LOGGER.warning("%s %d not found", entity_type.capitalize(), entity_id)
            return

        slot_id = entity["slot_id"]
        state = 1 if on else 0
        command = f"#@S{int_to_hex(slot_id)}M{state};"

        await self._send_command(command)

    async def set_zone_state(self, zone_id: int, on: bool) -> None:
        await self._set_output_state("zones", zone_id, on)

    async def set_tank_state(self, tank_id: int, on: bool) -> None:
        await self._set_output_state("tanks", tank_id, on)

    async def set_pool_state(self, pool_id: int, on: bool) -> None:
        await self._set_output_state("pools", pool_id, on)

    async def set_manguera_state(self, manguera_id: int, on: bool) -> None:
        await self._set_output_state("mangueras", manguera_id, on)

    async def set_riego_state(self, riego_id: int, on: bool) -> None:
        riego = self._data.get("riegos", {}).get(riego_id)
        if not riego:
            return

        slot_id = riego["slot_id"]
        state = 1 if on else 0
        command = f"#@H{int_to_hex(slot_id)}M{state};"
        await self._send_command(command)

    async def set_auto_riego(self, on: bool) -> None:
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

    def get_ciclon(self) -> dict[int, dict[str, Any]]:
        return self._data.get("ciclon", {})

    def get_pump(self) -> dict[str, Any]:
        return self._data.get("pump", {})

    def is_auto_riego_on(self) -> bool:
        return self._data.get("auto_riego", False)

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
