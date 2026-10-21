"""WebSocket client for Hidromotic CHI Smart irrigation controllers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import logging
from typing import Any

import aiohttp

# Importación de constantes de tipos de salida, estados y niveles de tanque
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


# -------------------------------------------------------------------
# Funciones Auxiliares de Conversión
# -------------------------------------------------------------------

def hex_to_int(h: str) -> int:
    """Convierte un carácter hexadecimal a entero (soporta A, B, C como 10, 11, 12)."""
    if h == "A":
        return 10
    if h == "B":
        return 11
    if h == "C":
        return 12
    return int(h)


def int_to_hex(i: int) -> str:
    """Convierte un entero a carácter hexadecimal (soporta 10, 11, 12 como A, B, C)."""
    if i == 10:
        return "A"
    if i == 11:
        return "B"
    if i == 12:
        return "C"
    return str(i)


# -------------------------------------------------------------------
# Cliente WebSocket Principal
# -------------------------------------------------------------------

class HidromoticClient:
    """Cliente WebSocket asíncrono para la comunicación con la controladora Hidromotic."""

    RECONNECT_INTERVAL = 30  # Intervalo de reintento de conexión en segundos

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Inicializa los atributos del cliente."""
        self.host = host
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session = session
        self._owns_session = session is None  # Indica si el cliente gestiona su propia sesión HTTP
        self._callbacks: list[Callable[[dict[str, Any]], None]] = []  # Suscriptores a eventos de actualización
        self._connected = False
        self._should_reconnect = True
        self._reconnect_task: asyncio.Task[None] | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._data: dict[str, Any] = {}

        # Evento asíncrono para indicar cuándo se recibieron los datos iniciales de configuración ('C')
        self.data_ready = asyncio.Event()

        # Cerrojo de asincronía para evitar condiciones de carrera al enviar comandos o mutar self._data
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Retorna True si el WebSocket está conectado."""
        return self._connected

    @property
    def data(self) -> dict[str, Any]:
        """Retorna el diccionario con la estructura actual de datos del dispositivo."""
        return self._data

    def register_callback(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Registra un callback para notificar cambios de estado a Home Assistant."""
        self._callbacks.append(callback)
        # Retorna una función lambda para desuscubrir el callback fácilmente
        return lambda: self._callbacks.remove(callback)

    async def connect(self) -> bool:
        """Establece la conexión WebSocket con el endpoint /rpc de la controladora."""
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()
                self._owns_session = True

            url = f"ws://{self.host}/rpc"
            _LOGGER.debug("Connecting to %s", url)
            self._ws = await self._session.ws_connect(url, heartbeat=30)
            self._connected = True
            _LOGGER.info("Connected to Hidromotic at %s", self.host)

            # Inicia la tarea en segundo plano para escuchar los mensajes entrantes
            self._listener_task = asyncio.create_task(self._listen())

            # Envía comando de handshake/inicio y solicita la configuración completa (#@C;)
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
        """Cierra de forma limpia la conexión WebSocket y libera las tareas asíncronas."""
        self._should_reconnect = False
        self._connected = False
        self.data_ready.clear()

        # Cancelación de tareas activas de reconexión y escucha
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
        """Empaqueta y envía un comando en formato JSON-RPC sobre el WebSocket."""
        if not self._ws or self._ws.closed:
            _LOGGER.warning("Cannot send command, not connected")
            return

        async with self._lock:
            # Selecciona el formato adecuado según el prefijo del comando
            if command.startswith("#"):
                payload = f'{{"method":"hdmt","params":{{"c":"{command}"}}}}'
            else:
                payload = f'{{"id":1111,"method":"hdmt","params":{{"c":"{command}"}}}}'

            _LOGGER.debug("Sending command: %s", payload)

            try:
                # Timeout de seguridad para evitar bloqueos si falla la red
                await asyncio.wait_for(self._ws.send_str(payload), timeout=5.0)
            except TimeoutError:
                _LOGGER.error("Timeout sending command to Hidromotic. Disconnecting to force recovery.")
                await self._ws.close()
            except Exception as err:
                _LOGGER.error("Error sending command to Hidromotic: %s", err)

    async def _listen(self) -> None:
        """Bucle continuo para consumir los mensajes recibidos desde el WebSocket."""
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
            self.data_ready.clear()  # Resetea el estado de datos listos al desconectarse
            if self._should_reconnect:
                self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """Gestiona el bucle de reintentos periódicos de reconexión."""
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
        """Procesa respuestas en formato texto (JSON)."""
        try:
            parsed = json.loads(data)
            _LOGGER.debug("Received JSON: %s", parsed)
        except json.JSONDecodeError:
            _LOGGER.debug("Non-JSON text received: %s", data)

    async def _process_binary(self, data: bytes) -> None:
        """Procesa paquetes de datos binarios garantizando exclusión mutua mediante Lock."""
        if len(data) < 2:
            return

        cmd = chr(data[0])  # Primer byte indica el tipo de comando ('C' o 'D')
        _LOGGER.debug("Processing binary command: %s, length: %d, data:%s", cmd, len(data), data)

        # Protege el parseo para evitar que dos tramas modifiquen self._data al mismo tiempo
        async with self._lock:
            if cmd == "C":
                await self._parse_full_config(data)
            elif cmd == "D":
                await self._parse_running_data(data)

        # Notifica a Home Assistant sobre los nuevos datos parseados
        for callback in self._callbacks:
            try:
                callback(self._data)
            except Exception as err:
                _LOGGER.error("Error in callback: %s", err)

    # -------------------------------------------------------------------
    # Parseo de Trama Binaria de Configuración Completa ('C')
    # -------------------------------------------------------------------

    async def _parse_full_config(self, data: bytes) -> None:
        """Parsea la trama binaria inicial con la configuración general de salidas."""
        is_mini = data[1] == 77  # 'M' ASCII = 77 (Placa Mini de 6 salidas)
        max_outputs = 6 if is_mini else 12

        self._data["is_mini"] = is_mini
        self._data["pic_version"] = data[2] | (data[3] << 8)
        self._data["pic_id"] = f"0x{data[6]:02X}"

        # Estructura de colecciones internas
        self._data["zones"] = {}
        self._data["tanks"] = {}
        self._data["pools"] = {}
        self._data["mangueras"] = {}
        self._data["ciclon"] = {}
        self._data["pump"] = {}
        self._data["riegos"] = {}
        self._data["outputs"] = {}

        # Índice optimizado O(1) para buscar rápidamente por tipo de salida
        self._data["outputs_by_tipo"] = {}

        etc = ""
        nivel = ""
        modo = ""

        if "auto_riego" not in self._data:
            self._data["auto_riego"] = True

        # Búsqueda de marcadores de sección binarios ('B' para Bomba, 'S' para Salidas)
        b_pos = None
        s_pos = None
        r_pos = None
        for idx in range(16, len(data)):
            if data[idx] == 0x42 and b_pos is None:
                b_pos = idx
            elif data[idx] == 0x53 and s_pos is None:
                s_pos = idx
                break

        # Lectura del estado de la bomba
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

        # Bucle de parseo para las salidas físicas de la placa
        while i < len(data) - 6 and slot_id < max_outputs:
            tipo = data[i]

            # Slot vacío / no configurado
            if tipo == 0x00:
                i += 6
                slot_id += 1
                continue

            # Determinación del tipo de hardware conectado a la salida
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

            # Extracción del nombre personalizado (etiqueta) de la salida
            label = ""
            if 0 < label_len <= 32 and i + 6 + label_len <= len(data):
                try:
                    label = data[i + 6 : i + 6 + label_len].decode("utf-8", errors="ignore")
                except UnicodeDecodeError:
                    label = ""
                    label_len = 0
            else:
                label_len = 0

            # Lectura de parámetros específicos para tanques
            if is_tank and not (estado == STATE_DISABLED):
                if i + 6 + label_len + 2 < len(data):
                    modo = data[i + 6 + label_len]
                    etc = data[i + 6 + label_len + 1]
                    nivel = data[i + 6 + label_len + 2]

            # Lectura de parámetros específicos para ciclones
            if is_ciclon and not (estado == STATE_DISABLED):
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

            # Guardado en colecciones generales e índice directo
            self._data["outputs"][slot_id] = output_data
            self._data["outputs_by_tipo"][tipo] = output_data

            # Guardado en colecciones especializadas
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
                    "automatico_tareas_enabled": locals().get("automatico_tareas_enabled", 0),
                    "automatico_fin_tareas_enabled": locals().get("automatico_fin_tareas_enabled", 0),
                    "automatico_tiempo_bomba_enabled": locals().get("automatico_tiempo_bomba_enabled", 0),
                    "automatico_tareas": locals().get("automatico_tareas", 0),
                    "automatico_fin_tareas": locals().get("automatico_fin_tareas", 0),
                    "automatico_tiempo_bomba": locals().get("automatico_tiempo_bomba", 0),
                }

        # Búsqueda de la sección 'R' (Auto Riego)
        for idx in range(i, len(data)):
            if data[idx] == 0x52 and r_pos is None:
                r_pos = idx
                break

        if r_pos is not None and r_pos + 1 < len(data):
            self._data["auto_riego"] = data[r_pos + 1] == 1

        # Parseo de programas de riego automáticos
        header_size = 40
        while i < len(data):
            tipo_riego = data[i]

            if tipo_riego != 0x48:
                i += header_size
                continue

            if i + 38 < len(data):
                riego_id = data[i + 1]
                riego_estado = data[i + 2]
                riego_enabled = data[i + 10]
                riego_label = "Riego " + chr(65 + riego_id)
                riego_use_sensor_lluvia = data[i + 9]

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

        # Dispara el evento notificando que la configuración completa terminó de cargarse
        self.data_ready.set()

    # -------------------------------------------------------------------
    # Parseo de Trama Binaria de Datos en Tiempo Real ('D')
    # -------------------------------------------------------------------

    async def _parse_running_data(self, data: bytes) -> None:
        """Parsea actualizaciones de estado diferidas o en tiempo real."""
        i = 6
        while i < len(data):
            section = chr(data[i])

            # Actualización de Bomba
            if section == "B":
                if i + 2 < len(data):
                    self._data["pump"]["estado"] = data[i + 1]
                    self._data["pump"]["pausa_externa"] = data[i + 2]
                i += 6

            # Actualización de Auto Riego
            elif section == "R":
                if i + 1 < len(data):
                    self._data["auto_riego"] = data[i + 1] == 1
                i += 2

            # Actualización de Estado de Salidas (Switches)
            elif section == "S":
                step = 3
                if i + 2 < len(data):
                    tipo = data[i + 1]
                    estado = data[i + 2]

                    # Búsqueda directa O(1) usando el índice creado en 'C'
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
                                step = 4  # Ajuste de desplazamiento: las tramas de tanque ocupan 4 bytes
                        elif tipo_upper == OUTPUT_TYPE_PISCINA and tipo_id in self._data.get("pools", {}):
                            self._data["pools"][tipo_id]["estado"] = estado
                        elif tipo_upper == OUTPUT_TYPE_MANGUERA and tipo_id in self._data.get("mangueras", {}):
                            self._data["mangueras"][tipo_id]["estado"] = estado
                        elif tipo_upper == OUTPUT_TYPE_CICLON and tipo_id in self._data.get("ciclon", {}):
                            self._data["ciclon"][tipo_id]["estado"] = estado
                i += step

            # Actualización de Programas de Riego
            elif section == "H":
                if i + 2 < len(data):
                    riego_id = data[i + 1]
                    estado = data[i + 2]
                    if riego_id in self._data.get("riegos", {}):
                        self._data["riegos"][riego_id]["estado"] = estado
                i += 3
            else:
                i += 1

    # -------------------------------------------------------------------
    # Métodos de Control y Envío de Estados
    # -------------------------------------------------------------------

    async def _set_output_state(self, entity_type: str, entity_id: int, on: bool) -> None:
        """Método genérico para cambiar el estado de una salida por su slot_id."""
        entity = self._data.get(entity_type, {}).get(entity_id)
        if not entity:
            _LOGGER.warning("%s %d not found", entity_type.capitalize(), entity_id)
            return

        slot_id = entity["slot_id"]
        state = 1 if on else 0
        command = f"#@S{int_to_hex(slot_id)}M{state};"

        await self._send_command(command)

    async def set_zone_state(self, zone_id: int, on: bool) -> None:
        """Enciende o apaga una zona de riego."""
        await self._set_output_state("zones", zone_id, on)

    async def set_tank_state(self, tank_id: int, on: bool) -> None:
        """Enciende o apaga el llenado de un tanque."""
        await self._set_output_state("tanks", tank_id, on)

    async def set_pool_state(self, pool_id: int, on: bool) -> None:
        """Enciende o apaga el llenado de una piscina."""
        await self._set_output_state("pools", pool_id, on)

    async def set_manguera_state(self, manguera_id: int, on: bool) -> None:
        """Enciende o apaga una salida tipo manguera."""
        await self._set_output_state("mangueras", manguera_id, on)

    async def set_riego_state(self, riego_id: int, on: bool) -> None:
        """Activa o desactiva un programa de riego automático."""
        riego = self._data.get("riegos", {}).get(riego_id)
        if not riego:
            return

        slot_id = riego["slot_id"]
        state = 1 if on else 0
        command = f"#@H{int_to_hex(slot_id)}M{state};"
        await self._send_command(command)

    async def set_auto_riego(self, on: bool) -> None:
        """Habilita o deshabilita el modo Auto Riego global."""
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
        """Solicita una relectura limpia de la configuración enviando #@C;."""
        await self._send_command("#@C;")

    # -------------------------------------------------------------------
    # Consultores de Datos y Getters Seguros
    # -------------------------------------------------------------------

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

    def is_zone_on(self, zone_id: int) -> bool:
        zone = self._data.get("zones", {}).get(zone_id)
        return zone.get("estado", 0) == 1 if zone else False

    def is_tank_full(self, tank_id: int) -> bool:
        tank = self._data.get("tanks", {}).get(tank_id)
        return tank.get("nivel", 0xFF) == TANK_FULL if tank else False

    def is_tank_empty(self, tank_id: int) -> bool:
        tank = self._data.get("tanks", {}).get(tank_id)
        return tank.get("nivel", 0xFF) == TANK_EMPTY if tank else False

    def get_tank_level(self, tank_id: int) -> str:
        """Retorna la representación en texto del nivel del tanque mapeando las constantes."""
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
