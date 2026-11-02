"""WebSocket client for Hidromotic CHI Smart irrigation controllers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import logging
from typing import Any

import aiohttp
from homeassistant.exceptions import HomeAssistantError

from .const import (
    COMMAND_INTERVAL_SECONDS,
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


def normalize_mac_address(mac: Any) -> str | None:
    """Return a normalized MAC address suitable for a config-entry unique ID."""
    if not isinstance(mac, str):
        return None

    normalized = mac.strip().replace(":", "").replace("-", "").lower()
    if len(normalized) != 12 or any(char not in "0123456789abcdef" for char in normalized):
        return None
    return normalized


def _redact_sensitive_data(value: Any) -> Any:
    """Return a copy with credential-like fields redacted for debug logging."""
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if isinstance(key, str)
                and any(
                    sensitive in key.lower()
                    for sensitive in ("pass", "secret", "token", "credential", "api_key")
                )
                else _redact_sensitive_data(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_data(item) for item in value]
    return value


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
        self._data: dict[str, Any] = {"c_msg": 0, "lluvia_bloqueado": False, "tareas": {}}

        self.data_ready = asyncio.Event()
        self.mac_ready = asyncio.Event()
        self._lock = asyncio.Lock()
        self._command_lock = asyncio.Lock()
        self._last_command_sent_at: float | None = None

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
        """Establece la conexión WebSocket con la controladora e inicia la escucha."""
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()
                self._owns_session = True

            url = f"ws://{self.host}/rpc"
            _LOGGER.debug("Connecting to %s", url)
            self._ws = await self._session.ws_connect(url, heartbeat=30)
            self._set_connected(True)

            self._listener_task = asyncio.create_task(self._listen())

            await self._send_command("e")
            await self._send_command("#@C;")
            await self._send_command("#@EY;")
        except Exception as err:
            _LOGGER.debug("Failed to connect to Hidromotic: %s", err)
            self._set_connected(False)
            return False
        else:
            return True

    async def disconnect(self) -> None:
        """Cierra la conexión WebSocket y cancela las tareas activas."""
        self._should_reconnect = False
        was_available = self._connected or self.data_ready.is_set()
        self._connected = False
        self.data_ready.clear()
        if was_available:
            self._notify_callbacks()

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
            self._ws = None
        if self._session and self._owns_session:
            await self._session.close()
            self._session = None

    def _set_connected(self, connected: bool) -> None:
        """Notify listeners when the WebSocket connection changes state."""
        if self._connected == connected:
            return
        self._connected = connected
        self._notify_callbacks()

    async def _send_command(self, command: str) -> None:
        """Envía un comando en formato JSON-RPC al WebSocket."""
        async with self._command_lock:
            loop = asyncio.get_running_loop()
            if self._last_command_sent_at is not None:
                delay = COMMAND_INTERVAL_SECONDS - (
                    loop.time() - self._last_command_sent_at
                )
                if delay > 0:
                    await asyncio.sleep(delay)

            async with self._lock:
                if not self._ws or self._ws.closed:
                    raise HomeAssistantError(
                        "No hay conexión con el dispositivo Hidromotic"
                    )

                if command.startswith("#"):
                    payload = f'{{"method":"hdmt","params":{{"c":"{command}"}}}}'
                else:
                    payload = f'{{"id":1111,"method":"hdmt","params":{{"c":"{command}"}}}}'

                _LOGGER.debug("Protocol TX (request): %s", payload)
                self._last_command_sent_at = loop.time()

                try:
                    await asyncio.wait_for(self._ws.send_str(payload), timeout=5.0)
                except TimeoutError as err:
                    _LOGGER.error("Timeout sending command '%s' to Hidromotic", command)
                    raise HomeAssistantError(
                        "Tiempo de espera agotado al enviar un comando a Hidromotic"
                    ) from err
                except Exception as err:
                    _LOGGER.error("Error sending command to Hidromotic: %s", err)
                    raise HomeAssistantError(
                        "No se pudo enviar el comando al dispositivo Hidromotic"
                    ) from err

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
                    _LOGGER.debug("WebSocket closed with error: %s", msg.data)
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    _LOGGER.debug("WebSocket closed")
                    break
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.debug("WebSocket listener stopped: %s", err)
        finally:
            was_available = self._connected or self.data_ready.is_set()
            self._connected = False
            self.data_ready.clear()
            if was_available:
                self._notify_callbacks()
            if self._should_reconnect:
                self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """Bucle para gestionar los reintentos automáticos de reconexión."""
        self.data_ready.clear()
        while self._should_reconnect and not self._connected:
            _LOGGER.debug(
                "Attempting to reconnect to Hidromotic in %d seconds",
                self.RECONNECT_INTERVAL,
            )
            await asyncio.sleep(self.RECONNECT_INTERVAL)
            if not self._should_reconnect:
                break
            try:
                if await self.connect():
                    _LOGGER.debug("Reconnected to Hidromotic")
                    break
            except Exception as err:
                _LOGGER.debug("Reconnection attempt failed: %s", err)

    def _notify_callbacks(self) -> None:
        """Notify Home Assistant listeners that client data may have changed."""
        for callback in tuple(self._callbacks):
            try:
                callback(self._data)
            except Exception as err:
                _LOGGER.error("Error in callback: %s", err)

    async def _process_text(self, data: str) -> None:
        """Procesa respuestas recibidas en formato JSON extrayendo información del sistema."""
        try:
            parsed = json.loads(data)
            _LOGGER.debug("Protocol RX (JSON response): %s", _redact_sensitive_data(parsed))

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
                    if isinstance(result.get("mg_version"), str):
                        self._data["mg_version"] = result["mg_version"]
                    active_slot = result.get("active_slot")
                    if isinstance(active_slot, int) and not isinstance(active_slot, bool):
                        self._data["active_slot"] = active_slot

                    ram = result.get("ram")
                    if isinstance(ram, dict):
                        for field in ("free", "min_free"):
                            value = ram.get(field)
                            if isinstance(value, int) and not isinstance(value, bool):
                                self._data[f"ram_{field}"] = ram[field]

                    if "mac" in result:
                        mac = result.get("mac")
                        if isinstance(mac, str) and mac.strip():
                            self._data["mac"] = mac.strip()
                            self.mac_ready.set()

                    wifi = result.get("wifi")
                    wifi_section = wifi if isinstance(wifi, dict) else {}
                    wifi_data = wifi_section.get("sta", {})
                    if not isinstance(wifi_data, dict):
                        wifi_data = {}
                    for source_key, data_key in (
                        ("ssid", "wifi_ssid"),
                        ("ip", "wifi_ip"),
                        ("dhcp", "wifi_dhcp"),
                        ("gw", "wifi_gateway"),
                        ("sntp", "wifi_sntp"),
                    ):
                        value = wifi_data.get(source_key)
                        if isinstance(value, str):
                            self._data[data_key] = value
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

                    wifi_ap = wifi_section.get("ap", {})
                    if isinstance(wifi_ap, dict):
                        ssid = wifi_ap.get("ssid")
                        if isinstance(ssid, str):
                            self._data["wifi_ap_ssid"] = ssid
                        ip = wifi_ap.get("ip")
                        if isinstance(ip, str):
                            self._data["wifi_ap_ip"] = ip

                    mqtt = wifi_section.get("mqtt", {})
                    if isinstance(mqtt, dict):
                        connected_time = mqtt.get("d")
                        if isinstance(connected_time, int) and not isinstance(
                            connected_time, bool
                        ):
                            self._data["mqtt_connected_time"] = connected_time
        except json.JSONDecodeError:
            _LOGGER.debug("Protocol RX (non-JSON text response, length=%d)", len(data))
        self._notify_callbacks()

    async def _process_binary(self, data: bytes) -> None:
        """Procesa tramas de datos binarios garantizando exclusión mutua."""
        if len(data) < 2:
            return

        cmd = chr(data[0])
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Protocol RX (binary response, command=%s, length=%d): %s",
                cmd,
                len(data),
                data.hex(" "),
            )

        async with self._lock:
            if cmd == "C":
                await self._parse_full_config(data)
            elif cmd == "D":
                await self._parse_running_data(data)

        self._notify_callbacks()

    async def _parse_full_config(self, data: bytes) -> bool:
        """Parsea secciones de configuración respetando el cursor y sus longitudes."""
        if len(data) < 16 or data[0] != ord("C"):
            _LOGGER.warning("Ignoring truncated or invalid full configuration frame")
            return False

        self.data_ready.clear()
        is_mini = data[1] == 77
        max_outputs = 6 if is_mini else 12
        riego_header_size = 28 if is_mini else 40
        max_riego_zonas = 6 if is_mini else 12

        self._data["is_mini"] = is_mini
        self._data["pic_name"] = "CHI Smart Mini" if is_mini else "CHI Smart"
        self._data["pic_version"] = data[2] | (data[3] << 8)
        self._data["pic_id"] = f"0x{data[6]:02X}"
        self._data["pic_rev"] = data[7]
        _LOGGER.debug(
            "Full config header: model=%s pic_version=%d config_version=%d "
            "frame_length=%d",
            self._data["pic_name"],
            self._data["pic_version"],
            int.from_bytes(data[4:6], "little"),
            len(data),
        )

        def bcd_to_int(value: int) -> int:
            return (((value & 0xF0) >> 4) * 10) + (value & 0x0F)

        year = 2000 + bcd_to_int(data[10])
        month = bcd_to_int(data[9])
        day = bcd_to_int(data[12])
        hour = bcd_to_int(data[14])
        minute = bcd_to_int(data[13])
        second = bcd_to_int(data[15])
        self._data["pic_fecha"] = (
            f"{year:04d}-{month:02d}-{day:02d} "
            f"{hour:02d}:{minute:02d}:{second:02d}"
        )

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
        self._data["tareas"] = {}
        self._data.setdefault("auto_riego", True)

        def truncated(section: str, offset: int) -> bool:
            _LOGGER.warning(
                "Truncated full configuration section %s at offset %d",
                section,
                offset,
            )
            return False

        i = 16
        outputs_seen = False
        while i < len(data):
            section = data[i]
            remaining = len(data) - i

            if section == ord("B"):
                if remaining < 17:
                    return truncated("B", i)
                self._data["pump"] = {
                    "estado": data[i + 1],
                    "pausa_externa": data[i + 2],
                    "marcha": int.from_bytes(data[i + 3 : i + 7], "little"),
                    "t0_offduracion": int.from_bytes(data[i + 7 : i + 9], "little"),
                    "t1_ondelay": int.from_bytes(data[i + 9 : i + 11], "little"),
                    "t2_desactivando": int.from_bytes(data[i + 11 : i + 13], "little"),
                    "t3_pozoseco": int.from_bytes(data[i + 13 : i + 15], "little"),
                    "t4_pozoseco_auto_recover": int.from_bytes(
                        data[i + 15 : i + 17], "little"
                    ),
                }
                i += 17

            elif section == ord("E"):
                if remaining < 17:
                    return truncated("E", i)
                section_offset = i
                inputs = {}
                for input_id in range(4):
                    offset = i + 1 + input_id * 4
                    tipo = data[offset]
                    invert = data[offset + 1] == 1
                    raw_estado = data[offset + 3] == 1
                    inputs[input_id] = {
                        "id": input_id,
                        "tipo": tipo,
                        "tipo_name": INPUT_TYPE_MAP.get(tipo, f"Tipo {tipo}"),
                        "invert": invert,
                        "actual": data[offset + 2],
                        "raw_estado": raw_estado,
                        "estado": raw_estado ^ invert,
                    }
                self._data["inputs"] = inputs
                i += 17
                _LOGGER.debug(
                    "Full config E section: offset=%d consumed=17 raw=%s inputs=%s "
                    "next_offset=%d next_byte=%s",
                    section_offset,
                    data[section_offset:i].hex(" "),
                    inputs,
                    i,
                    f"0x{data[i]:02X}" if i < len(data) else "end",
                )

            elif section == ord("S"):
                outputs_seen = True
                section_offset = i
                i += 1
                for slot_id in range(max_outputs):
                    if len(data) - i < 6:
                        return truncated("S", i)

                    slot_offset = i
                    tipo, bomba = data[i], data[i + 1]
                    duracion = data[i + 2] | (data[i + 3] << 8)
                    estado = data[i + 4]
                    label_len = data[i + 5]
                    i += 6

                    if label_len > 32 or len(data) - i < label_len:
                        return truncated("S label", i - 1)
                    label = data[i : i + label_len].decode("utf-8", errors="ignore")
                    i += label_len

                    if tipo == 0:
                        continue

                    is_zone = 0x41 <= tipo <= 0x4C
                    is_tank = 0x21 <= tipo <= 0x2C
                    is_pileta = 0x51 <= tipo <= 0x5C
                    is_manguera = 0x11 <= tipo <= 0x1C
                    is_ciclon = 0x61 <= tipo <= 0x6C
                    tipo_id = (tipo & 0x0F) - 1
                    if tipo_id < 0:
                        _LOGGER.warning("Invalid output type 0x%02X in slot %d", tipo, slot_id)
                        continue

                    extra_size = 0
                    if estado != STATE_DISABLED and is_tank:
                        extra_size = 3
                    elif estado != STATE_DISABLED and is_ciclon:
                        extra_size = 10
                    if len(data) - i < extra_size:
                        return truncated("S output details", i)
                    extras = data[i : i + extra_size]
                    i += extra_size
                    if is_tank:
                        _LOGGER.debug(
                            "Full config tank: slot=%d offset=%d type=0x%02X "
                            "state=%d duration=%d label=%r extras=%s mode=%d "
                            "level=%d float_type=%d",
                            slot_id,
                            slot_offset,
                            tipo,
                            estado,
                            duracion,
                            label,
                            extras.hex(" "),
                            extras[0] if extras else 0,
                            extras[1] if len(extras) > 1 else 0,
                            extras[2] if len(extras) > 2 else 0,
                        )

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
                    self._data["outputs"][slot_id] = output_data
                    self._data["outputs_by_tipo"][tipo] = output_data

                    if is_zone:
                        self._data["zones"][tipo_id] = {
                            "id": tipo_id,
                            "slot_id": slot_id,
                            "estado": estado,
                            "label": label or f"Zona {tipo_id + 1}",
                            "duracion": duracion,
                        }
                    elif is_tank:
                        self._data["tanks"][tipo_id] = {
                            "id": tipo_id,
                            "slot_id": slot_id,
                            "estado": estado,
                            "label": label or f"Tanque {tipo_id + 1}",
                            "duracion": duracion,
                            "nivel": extras[1] if extras else 0,
                            "modo": extras[0] if extras else 0,
                            "tipo_flotante": extras[2] if extras else 0,
                        }
                    elif is_pileta:
                        self._data["pools"][tipo_id] = {
                            "id": tipo_id,
                            "slot_id": slot_id,
                            "estado": estado,
                            "label": label or f"Piscina {tipo_id + 1}",
                            "duracion": duracion,
                        }
                    elif is_manguera:
                        self._data["mangueras"][tipo_id] = {
                            "id": tipo_id,
                            "slot_id": slot_id,
                            "estado": estado,
                            "label": label or f"Manguera {tipo_id + 1}",
                            "duracion": duracion,
                        }
                    elif is_ciclon:
                        self._data["ciclon"][tipo_id] = {
                            "id": tipo_id,
                            "slot_id": slot_id,
                            "estado": estado,
                            "label": label or f"Ciclon {tipo_id + 1}",
                            "duracion": duracion,
                            "modo_ante_tareas": extras[0] if extras else 0,
                            "modo_fin_de_tareas": extras[1] if extras else 0,
                            "modo_tiempo": extras[2] if extras else 0,
                            "d_ante_tareas": int.from_bytes(extras[3:5], "little")
                            if extras
                            else 0,
                            "d_fin_de_tareas": extras[5] if extras else 0,
                            "bomba_marcha_duracion": int.from_bytes(extras[6:8], "little")
                            if extras
                            else 0,
                            "proximo_ciclon": int.from_bytes(extras[8:10], "little")
                            if extras
                            else 0,
                        }
                _LOGGER.debug(
                    "Full config S section: offset=%d next_offset=%d slots=%d",
                    section_offset,
                    i,
                    max_outputs,
                )

            elif section == ord("H"):
                if remaining < riego_header_size:
                    return truncated("H", i)
                riego_id = data[i + 1]
                label_len = data[i + riego_header_size - 1]
                if len(data) - (i + riego_header_size) < label_len:
                    return truncated("H label", i + riego_header_size - 1)
                riego_label = f"Riego {chr(65 + riego_id)}"
                if label_len:
                    custom_label = data[
                        i + riego_header_size : i + riego_header_size + label_len
                    ].decode("utf-8", errors="ignore")
                    if custom_label.strip():
                        riego_label = custom_label
                zonas_duracion = {}
                for zona_idx in range(max_riego_zonas):
                    offset = i + 15 + zona_idx * 2
                    zonas_duracion[f"duracion_{zona_idx + 1}"] = (
                        data[offset] | (data[offset + 1] << 8)
                    )
                self._data["riegos"][riego_id] = {
                    "id": riego_id,
                    "slot_id": riego_id,
                    "estado": data[i + 2],
                    "enabled": data[i + 10],
                    "label": riego_label,
                    "use_sensor_lluvia": data[i + 9],
                    "zonas": zonas_duracion,
                }
                i += riego_header_size + label_len

            elif section == ord("R"):
                if remaining < 4:
                    return truncated("R", i)
                self._data["auto_riego"] = data[i + 1] != 0
                self._data["active_horario"] = data[i + 2]
                self._data["lluvia_bloqueado"] = data[i + 3] == 1
                i += 4

            elif section == ord("L"):
                if remaining < 4:
                    return truncated("L", i)
                tarea_id = data[i + 1]
                record_size = 6 if tarea_id == 0 else 4
                if remaining < record_size:
                    return truncated("L", i)
                tarea = {
                    "id": tarea_id,
                    "tipo": f"{data[i + 2]:02X}",
                    "modo": data[i + 3],
                    "duracion": int.from_bytes(data[i + 4 : i + 6], "little")
                    if tarea_id == 0
                    else 0,
                }
                self._data["tareas"][tarea_id] = tarea
                i += record_size

            elif section == ord("b"):
                if remaining < 3:
                    return truncated("b", i)
                self._data["bateria"] = int.from_bytes(data[i + 1 : i + 3], "little")
                i += 3

            elif section == ord("u"):
                if remaining < 4:
                    return truncated("u", i)
                self._data["uart_reset_count"] = int.from_bytes(data[i + 2 : i + 4], "little")
                i += 4

            elif section == ord("c"):
                if remaining < 3:
                    return truncated("c", i)
                self._data["esp_reset_count"] = int.from_bytes(data[i + 1 : i + 3], "little")
                i += 3

            else:
                _LOGGER.debug(
                    "Skipping unknown full configuration byte at offset %d: 0x%02X",
                    i,
                    section,
                )
                i += 1

        if not outputs_seen:
            _LOGGER.warning("No output section found in full configuration")
            return False

        self.data_ready.set()
        _LOGGER.debug(
            "Full config parsed: inputs=%d outputs=%d tanks=%d next_offset=%d",
            len(self._data["inputs"]),
            len(self._data["outputs"]),
            len(self._data["tanks"]),
            i,
        )
        return True

    async def _parse_running_data(self, data: bytes) -> None:
        """Parsea actualizaciones parciales en tiempo real enviadas por la placa en la trama 'D'."""
        if "pic_version" not in self._data:
            _LOGGER.debug("Ignoring running data received before the full configuration")
            return

        if len(data) < 6 or data[0] != ord("D"):
            _LOGGER.warning("Ignoring truncated or invalid running data frame")
            return

        def truncated(section: str, offset: int) -> None:
            _LOGGER.warning(
                "Truncated running data section %s at offset %d",
                section,
                offset,
            )

        i = 6
        while i < len(data):
            section = data[i]
            remaining = len(data) - i

            if section == ord("B"):
                if remaining >= 7:
                    self._data["pump"]["estado"] = data[i + 1]
                    self._data["pump"]["pausa_externa"] = data[i + 2]
                    self._data["pump"]["marcha"] = (
                        data[i + 3]
                        | (data[i + 4] << 8)
                        | (data[i + 5] << 16)
                        | (data[i + 6] << 24)
                    )
                    i += 7
                elif remaining >= 3:
                    self._data["pump"]["estado"] = data[i + 1]
                    self._data["pump"]["pausa_externa"] = data[i + 2]
                    i += 3
                else:
                    truncated("B", i)
                    return

            elif section == ord("b"):
                if remaining < 3:
                    truncated("b", i)
                    return
                self._data["bateria"] = int.from_bytes(data[i + 1 : i + 3], "little")
                i += 3

            elif section == ord("E"):
                if remaining < 3:
                    truncated("E", i)
                    return
                input_id = data[i + 1]
                raw_estado = data[i + 2] == 1
                inp = self._data.get("inputs", {}).get(input_id)
                if inp:
                    invert = inp.get("invert", False)
                    inp["raw_estado"] = raw_estado
                    inp["estado"] = raw_estado ^ invert
                i += 3

            elif section == ord("R"):
                if remaining < 3:
                    truncated("R", i)
                    return
                self._data["active_horario"] = data[i + 1]
                self._data["lluvia_bloqueado"] = data[i + 2] == 1
                i += 3

            elif section == ord("S"):
                if remaining < 3:
                    truncated("S", i)
                    return
                tipo = data[i + 1]
                estado = data[i + 2]
                tipo_upper = tipo & 0xF0
                tipo_id = (tipo & 0x0F) - 1
                tank = self._data.get("tanks", {}).get(tipo_id)
                ciclon = self._data.get("ciclon", {}).get(tipo_id)
                extra_size = 4 if tipo_upper == OUTPUT_TYPE_TANQUE else 3
                if (
                    tipo_upper == OUTPUT_TYPE_CICLON
                    and ciclon
                    and ciclon.get("modo_tiempo")
                ):
                    extra_size = 5
                if remaining < extra_size:
                    truncated("S", i)
                    return

                output = self._data.get("outputs_by_tipo", {}).get(tipo)
                if tipo_upper == OUTPUT_TYPE_TANQUE:
                    _LOGGER.debug(
                        "Running tank update: offset=%d raw=%s type=0x%02X "
                        "tank_id=%d state=%d level=%d",
                        i,
                        data[i : i + extra_size].hex(" "),
                        tipo,
                        tipo_id,
                        estado,
                        data[i + 3],
                    )
                if output:
                    output["estado"] = estado
                    if tipo_upper == OUTPUT_TYPE_ZONA and tipo_id in self._data["zones"]:
                        self._data["zones"][tipo_id]["estado"] = estado
                    elif tipo_upper == OUTPUT_TYPE_TANQUE and tank:
                        tank["estado"] = estado
                        tank["nivel"] = data[i + 3]
                    elif tipo_upper == OUTPUT_TYPE_PISCINA and tipo_id in self._data["pools"]:
                        self._data["pools"][tipo_id]["estado"] = estado
                    elif tipo_upper == OUTPUT_TYPE_MANGUERA and tipo_id in self._data["mangueras"]:
                        self._data["mangueras"][tipo_id]["estado"] = estado
                    elif tipo_upper == OUTPUT_TYPE_CICLON and ciclon:
                        ciclon["estado"] = estado
                        if extra_size == 5:
                            ciclon["proximo_ciclon"] = int.from_bytes(
                                data[i + 3 : i + 5], "little"
                            )
                i += extra_size

            elif section == ord("H"):
                if remaining < 9:
                    truncated("H", i)
                    return
                riego_id = data[i + 1]
                riego = self._data.get("riegos", {}).get(riego_id)
                if riego is not None:
                    riego["estado"] = data[i + 2]
                    riego["active_zona"] = data[i + 3]
                    riego["duracion"] = int.from_bytes(data[i + 5 : i + 9], "little")
                i += 9

            elif section == ord("L"):
                if remaining < 4:
                    truncated("L", i)
                    return
                tarea_id = data[i + 1]
                record_size = 6 if tarea_id == 0 else 4
                if remaining < record_size:
                    truncated("L", i)
                    return
                self._data["tareas"][tarea_id] = {
                    "id": tarea_id,
                    "tipo": f"{data[i + 2]:02X}",
                    "modo": data[i + 3],
                    "duracion": int.from_bytes(data[i + 4 : i + 6], "little")
                    if tarea_id == 0
                    else 0,
                }
                i += record_size

            elif section == ord("u"):
                if remaining < 4:
                    truncated("u", i)
                    return
                self._data["uart_reset_count"] = int.from_bytes(data[i + 2 : i + 4], "little")
                i += 4

            elif section == ord("c"):
                if remaining < 3:
                    truncated("c", i)
                    return
                self._data["esp_reset_count"] = int.from_bytes(data[i + 1 : i + 3], "little")
                i += 3

            elif section == ord("k"):
                if remaining < 2:
                    truncated("k", i)
                    return
                self._data["button_state"] = data[i + 1]
                i += 2
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

    async def set_tank_mode(self, tank_id: int, automatic: bool) -> None:
        """Set a tank to automatic or manual mode."""
        tank = self._data.get("tanks", {}).get(tank_id)
        if not tank:
            _LOGGER.warning("Tank %d not found while changing mode", tank_id)
            return
        if tank.get("tipo_flotante", 0) == 0:
            raise HomeAssistantError(
                "No se puede cambiar el modo del tanque sin un flotante configurado"
            )

        mode = 1 if automatic else 0
        _LOGGER.debug("Changing tank mode: tank_id=%d requested_mode=%d", tank_id, mode)
        await self._send_command(f"#@T{tank_id}A{mode};#@+;")
        tank["modo"] = mode
        _LOGGER.debug(
            "Tank mode command sent: tank_id=%d local_mode=%d (awaiting device update)",
            tank_id,
            mode,
        )
        self._notify_callbacks()

    async def set_pool_state(self, pool_id: int, on: bool) -> None:
        await self._set_output_state("pools", pool_id, on)

    async def set_manguera_state(self, manguera_id: int, on: bool) -> None:
        await self._set_output_state("mangueras", manguera_id, on)

    async def set_ciclon_state(self, ciclon_id: int, on: bool) -> None:
        await self._set_output_state("ciclon", ciclon_id, on)

    async def set_riego_state(self, riego_id: int, on: bool) -> None:
        riego = self._data.get("riegos", {}).get(riego_id)
        if not riego:
            return

        slot_id = riego["slot_id"]
        state = 1 if on else 0
        command = f"#@H{int_to_hex(slot_id)}M{state};"
        await self._send_command(command)

    # NUEVO MÉTODO: Modifica la duración en minutos de una salida dinámica (Pool, Zone, etc.)
    async def set_output_duration(self, entity_type: str, entity_id: int, duration_minutes: int) -> None:
        """Cambia la duración en minutos de una salida dinámica enviando #@S{slot}D{minutos};#@+;"""
        entity = self._data.get(entity_type, {}).get(entity_id)
        if not entity:
            _LOGGER.warning("%s %d no encontrado al cambiar duración", entity_type.capitalize(), entity_id)
            return

        slot_id = entity["slot_id"]
        command = f"#@S{int_to_hex(slot_id)}D{duration_minutes};#@+;"
        await self._send_command(command)

        entity["duracion"] = duration_minutes
        for callback in self._callbacks:
            try:
                callback(self._data)
            except Exception as err:
                _LOGGER.error("Error en callback al cambiar duración: %s", err)

    # NUEVO MÉTODO: Modifica la duración en minutos de una zona en un programa de Riego
    async def set_riego_zona_duration(self, riego_id: int, zona_idx: int, duration_minutes: int) -> None:
        """Cambia la duración en minutos de una zona en un programa de Riego enviando #@H{slot}Z{zona}D{minutos};#@+;"""
        riego = self._data.get("riegos", {}).get(riego_id)
        if not riego:
            _LOGGER.warning("Riego %d no encontrado al cambiar duración", riego_id)
            return

        slot_id = riego["slot_id"]
        command = f"#@H{int_to_hex(slot_id)}Z{int_to_hex(zona_idx)}D{duration_minutes};#@+;"
        await self._send_command(command)

        if "zonas" in riego:
            riego["zonas"][f"duracion_{zona_idx + 1}"] = duration_minutes

        for callback in self._callbacks:
            try:
                callback(self._data)
            except Exception as err:
                _LOGGER.error("Error en callback al cambiar duración de riego: %s", err)

    async def set_auto_riego(self, on: bool) -> None:
        state = 1 if on else 0
        command = f"#@RA{state};#@+;"
        await self._send_command(command)
        self._data["auto_riego"] = on
        for callback in self._callbacks:
            try:
                callback(self._data)
            except Exception as err:
                _LOGGER.error("Error in callback: %s", err)

    async def reboot_device(self) -> None:
        """Envía el comando de reinicio a la placa CHI Smart."""
        _LOGGER.info("Enviando comando de reinicio a Hidromotic...")
        # Comando de reinicio del sistema (equivalente a onSistemaReset() en app.js)
        await self._send_command("i.e")

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

    def is_lluvia_bloqueado(self) -> bool:
        return self._data.get("lluvia_bloqueado", False)

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
