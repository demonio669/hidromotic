"""Cloud WebSocket transport for Hidromotic accounts."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import logging
from typing import Any

import aiohttp
from homeassistant.exceptions import HomeAssistantError

from .client import (
    INPUT_TYPE_MAP,
    HidromoticClient,
    _redact_sensitive_data,
    normalize_device_identifier,
)
from .const import CONNECTION_TYPE_CLOUD

_LOGGER = logging.getLogger(__name__)


class HidromoticCloudClient(HidromoticClient):
    """Translate account-cloud snapshots and patches to the local entity model."""

    LOGIN_URL = "https://hidromotic.com/login"
    WEBSOCKET_URL = "wss://hidromotic.com/ws"
    connection_type = CONNECTION_TYPE_CLOUD

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
        device_id: str | None = None,
    ) -> None:
        super().__init__("hidromotic.com", session=session)
        self._username = username
        self._password = password
        self.account_username = username
        self._expected_device_id = (
            device_id.lower() if device_id and device_id.lower().startswith("chi_")
            else None
        )
        self._device: str | None = None
        self._state: dict[str, Any] | None = None
        self._seq: int | None = None
        self._patches: list[dict[str, Any]] = []
        self._config_lock = asyncio.Lock()
        self._last_config_error: dict[str, Any] | None = None

    async def connect(self) -> bool:
        """Log in and open the socket, which sends initial snapshots itself."""
        self._state = None
        self._seq = None
        self._patches.clear()
        self.data_ready.clear()
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()
                self._owns_session = True

            async with self._session.post(
                self.LOGIN_URL,
                data={
                    "login": self._username,
                    "password": self._password,
                },
                allow_redirects=False,
            ) as response:
                if response.status != 303 or response.headers.get("Location") != "/":
                    raise HomeAssistantError("Inicio de sesión Cloud rechazado")
                # Home Assistant's shared session may use a DummyCookieJar.
                cookies = "; ".join(
                    f"{name}={cookie.coded_value}"
                    for name, cookie in response.cookies.items()
                )

            self._ws = await self._session.ws_connect(
                self.WEBSOCKET_URL,
                heartbeat=30,
                origin="https://hidromotic.com",
                headers={"Cookie": cookies} if cookies else {},
            )
            self._set_connected(True)
            self._listener_task = asyncio.create_task(self._listen())

        except (aiohttp.ClientError, HomeAssistantError, OSError, TimeoutError) as err:
            _LOGGER.debug("Failed to connect to Hidromotic cloud: %s", err)
            self._set_connected(False)
            return False

        return True

    async def _send_command(self, command: str) -> None:
        """Route controller commands through the JSON cloud gateway."""
        await self._send_gateway_command(command)

    async def _send_gateway_command(self, command: str | dict[str, Any]) -> None:
        if not self.data_ready.is_set():
            raise HomeAssistantError("El dispositivo Cloud no tiene datos disponibles")
        await self._send_cloud_message({"cmd": command})

    async def set_auto_riego(self, on: bool) -> None:
        async with self._config_lock:
            await super().set_auto_riego(on)
            if self._state is not None:
                self._state["pic"].setdefault("riego", {})["modo"] = int(on)

    async def set_tank_mode(self, tank_id: int, automatic: bool) -> None:
        tank = self._data.get("tanks", {}).get(tank_id)
        if not tank or not tank.get("tipo_flotante"):
            raise HomeAssistantError(
                "No se puede cambiar el modo del tanque sin un flotante configurado"
            )
        await self._update_output_config("tanks", tank_id, "tanque_auto", automatic)

    async def set_output_duration(
        self, entity_type: str, entity_id: int, duration_minutes: int
    ) -> None:
        await self._update_output_config(
            entity_type, entity_id, "duracion", duration_minutes
        )

    async def _update_output_config(
        self, entity_type: str, entity_id: int, field: str, value: int | bool
    ) -> None:
        async with self._config_lock:
            entity = self._data.get(entity_type, {}).get(entity_id)
            if entity is None or self._state is None or not self.data_ready.is_set():
                raise HomeAssistantError("La salida Cloud no está disponible")
            outputs = self._state["pic"]["salidas"]
            config = []
            for output in outputs:
                if not isinstance(output, dict):
                    raise HomeAssistantError("La configuración de salidas Cloud está incompleta")
                item = {
                    "tipo": output["tipo"],
                    "bomba": output.get("bomba", 0) == 1,
                    "desc": output.get("desc", ""),
                    "duracion": output.get("duracion", 0),
                }
                if output.get("tanque"):
                    item["tanque_auto"] = output["tanque"].get("modo", 0) != 0
                config.append(item)
            slot = entity["slot_id"]
            config[slot][field] = value
            await self._send_gateway_command({"config": {"salidas": config}})
            if field == "tanque_auto":
                outputs[slot]["tanque"]["modo"] = int(value)
                entity["modo"] = int(value)
            else:
                outputs[slot][field] = value
                entity[field] = value
            self._notify_callbacks()

    async def set_riego_zona_duration(
        self, riego_id: int, zona_idx: int, duration_minutes: int
    ) -> None:
        async with self._config_lock:
            if self._state is None or not self.data_ready.is_set():
                raise HomeAssistantError("El dispositivo Cloud no tiene datos disponibles")
            pic = self._state["pic"]
            schedules = [
                {
                    "i": schedule["i"],
                    "habilitado": schedule["habilitado"] == 1,
                    "hora": schedule["hora"],
                    "paridad": schedule["paridad"],
                    "dias": schedule["dias"],
                    "lluvia": bool(schedule.get("accesorios", 0) & 1),
                    "zonas_min": list(schedule["zonas_min"]),
                }
                for schedule in pic.get("horarios", [])
            ]
            schedule = next((h for h in schedules if h["i"] == riego_id), None)
            if schedule is None or not 0 <= zona_idx < len(schedule["zonas_min"]):
                raise HomeAssistantError("La zona del programa Cloud no está disponible")
            schedule["zonas_min"][zona_idx] = duration_minutes
            await self._send_gateway_command({
                "config": {"riego": {
                    "auto": pic.get("riego", {}).get("modo", 0) != 0,
                    "horarios": schedules,
                }},
            })
            for original in pic["horarios"]:
                if original["i"] == riego_id:
                    original["zonas_min"][zona_idx] = duration_minutes
            self._data["riegos"][riego_id]["zonas"][f"duracion_{zona_idx + 1}"] = duration_minutes
            self._notify_callbacks()

    async def reboot_device(self) -> None:
        """Use the cloud action corresponding to the local Wi-Fi module reset."""
        await self._send_gateway_command({"accion": "reiniciar_wifi"})

    async def _send_cloud_message(self, message: dict[str, Any]) -> None:
        if self._device is None:
            raise HomeAssistantError("No se identificó un dispositivo CHI en Cloud")
        payload = json.dumps({"product": "chi", "device": self._device, **message})
        await self._send_text_payload(payload, str(message))

    async def refresh(self) -> None:
        """Request a new gateway snapshot instead of a binary configuration."""
        await self._send_cloud_message({"sync": True})

    async def _resync(self) -> None:
        self._state = None
        self._seq = None
        self._patches.clear()
        self.data_ready.clear()
        self._notify_callbacks()
        await self.refresh()

    async def _process_text(self, data: str) -> None:
        """Apply the same numbered snapshot/patch protocol as the cloud web app."""
        try:
            message = json.loads(data)
            if not isinstance(message, dict):
                raise ValueError("Expected a cloud message object")
            if message.get("product") != "chi":
                return
            device = message.get("device")
            if not isinstance(device, str):
                raise ValueError("Missing CHI device identifier")
            identity = normalize_device_identifier(f"CHI/{device}")
            if identity is None:
                raise ValueError("Invalid CHI device identifier")
            if self._expected_device_id and identity != self._expected_device_id:
                return
            if self._device is not None and device != self._device:
                return
            self._device = device
            kind = message.get("kind")
            if kind not in ("state", "patch"):
                _LOGGER.debug(
                    "Cloud %s: %s", kind,
                    _redact_sensitive_data(message.get("data")),
                )
                return
            body = message["data"]
            if not isinstance(body, dict):
                raise ValueError("Missing cloud message data")
            seq = body.get("seq")
            if not isinstance(seq, int) or isinstance(seq, bool):
                raise ValueError("Invalid cloud sequence number")
            if kind == "state":
                state = body.get("state")
                if not isinstance(state, dict):
                    raise ValueError("Invalid cloud snapshot")
                self._state = state
                self._seq = seq
                queued = sorted(
                    (patch for patch in self._patches if patch["seq"] > seq),
                    key=lambda patch: patch["seq"],
                )
                self._patches.clear()
                for patch in queued:
                    if self._seq is not None and patch["seq"] <= self._seq:
                        continue
                    if not await self._apply_patch(patch):
                        return
            elif self._state is None:
                self._patches.append(body)
                return
            elif not await self._apply_patch(body):
                return
            await self._publish_state()
        except (ValueError, TypeError, KeyError, IndexError) as err:
            _LOGGER.warning("Invalid Hidromotic cloud message: %s", err)
            if self._device is not None:
                await self._resync()

    async def _apply_patch(self, patch: dict[str, Any]) -> bool:
        seq = patch["seq"]
        if self._seq is not None and seq <= self._seq:
            return False
        if self._seq is None or seq != self._seq + 1:
            _LOGGER.warning("Hidromotic cloud sequence gap; requesting a snapshot")
            await self._resync()
            return False
        state = deepcopy(self._state)
        ops = patch.get("ops")
        if not isinstance(ops, list):
            raise ValueError("Invalid cloud patch operations")
        for op in ops:
            if not isinstance(op, dict) or not isinstance(op.get("p"), list):
                raise ValueError("Invalid cloud patch path")
            path = op["p"]
            if any(
                not isinstance(key, (str, int)) or isinstance(key, bool)
                or isinstance(key, int) and key < 0
                for key in path
            ):
                raise ValueError("Invalid cloud patch key")
            if not path:
                state = op.get("v")
                continue
            target = state
            for index, key in enumerate(path):
                if isinstance(target, list) and isinstance(key, int):
                    if key >= len(target):
                        target.extend([None] * (key + 1 - len(target)))
                elif not isinstance(target, dict) or not isinstance(key, str):
                    raise ValueError("Invalid cloud patch container")
                if index == len(path) - 1:
                    if op.get("d"):
                        if isinstance(target, dict):
                            target.pop(key, None)
                        else:
                            target[key] = None
                    else:
                        target[key] = op.get("v")
                else:
                    child = target.get(key) if isinstance(target, dict) else target[key]
                    if child is None:
                        child = [] if isinstance(path[index + 1], int) else {}
                        target[key] = child
                    target = child
        if not isinstance(state, dict):
            raise ValueError("Cloud patch did not produce a state object")
        self._state = state
        self._seq = seq
        return True

    async def _publish_state(self) -> None:
        """Expose decoded cloud fields using the existing entity data keys."""
        if self._state is None:
            return
        state = self._state
        config_status = state.get("config_estado")
        if isinstance(config_status, dict) and config_status.get("estado") == "error":
            if config_status != self._last_config_error:
                _LOGGER.error(
                    "Hidromotic cloud rejected configuration: %s",
                    _redact_sensitive_data(config_status),
                )
                self._last_config_error = deepcopy(config_status)
        else:
            self._last_config_error = None
        pic = state.get("pic") or {}
        if not isinstance(pic, dict):
            raise ValueError("Invalid cloud PIC state")
        for field in ("entradas", "salidas", "horarios", "tareas"):
            if pic.get(field) is not None and not isinstance(pic[field], list):
                raise ValueError(f"Invalid cloud PIC {field}")
        mini = bool(state.get("mini", False))
        data: dict[str, Any] = {
            "c_msg": self._data.get("c_msg", 0),
            "device_id": f"CHI/{self._device}",
            "is_mini": mini,
            "pic_name": "CHI Smart Mini" if mini else "CHI Smart",
            "pic_version": state.get("v"),
            "pic_fecha": pic.get("fecha"),
            "pic_rev": pic.get("pic_rev"),
            "zones": {}, "tanks": {}, "pools": {}, "mangueras": {}, "ciclon": {},
            "outputs": {}, "outputs_by_tipo": {}, "inputs": {}, "riegos": {},
            "tareas": {},
        }
        if isinstance(pic.get("pic_id"), int):
            data["pic_id"] = f"0x{pic['pic_id']:02X}"
        pump = pic.get("bomba") or {}
        if not isinstance(pump, dict):
            raise ValueError("Invalid cloud pump state")
        data["pump"] = {
            dest: pump[source] for source, dest in (
                ("estado", "estado"), ("pausa_externa", "pausa_externa"),
                ("marcha_min", "marcha"), ("off_duracion_ms", "t0_offduracion"),
                ("on_delay_ms", "t1_ondelay"), ("off_delay_ms", "t2_desactivando"),
                ("pozo_seco_start_s", "t3_pozoseco"),
                ("pozo_seco_retry_s", "t4_pozoseco_auto_recover"),
            ) if source in pump
        }
        for entry in pic.get("entradas") or []:
            if entry is None:
                continue
            if not isinstance(entry, dict):
                raise ValueError("Invalid cloud input")
            tipo = entry.get("tipo", 0)
            invert = bool(entry.get("invert", 0))
            raw = bool(entry.get("estado", 0))
            input_id = entry["i"]
            data["inputs"][input_id] = {
                "id": input_id, "tipo": tipo,
                "tipo_name": INPUT_TYPE_MAP.get(tipo, f"Tipo {tipo}"),
                "invert": invert, "actual": entry.get("actual", 0),
                "raw_estado": raw, "estado": raw ^ invert,
            }
        categories = {
            0x10: ("mangueras", "Manguera"), 0x20: ("tanks", "Tanque"),
            0x40: ("zones", "Zona"), 0x50: ("pools", "Piscina"),
            0x60: ("ciclon", "Ciclon"),
        }
        for slot, output in enumerate(pic.get("salidas") or []):
            if output is None:
                continue
            if not isinstance(output, dict):
                raise ValueError("Invalid cloud output")
            tipo = output.get("tipo", 0)
            if tipo == 0:
                continue
            output_id = (tipo & 0x0F) - 1
            if output_id < 0:
                raise ValueError("Invalid cloud output type")
            common = {
                "id": output_id, "slot_id": slot,
                "estado": output.get("estado", 0),
                "duracion": output.get("duracion", 0),
                "label": output.get("desc", ""),
            }
            raw_output = {
                **common, "tipo": f"{tipo:02X}", "tipo_raw": tipo,
                "bomba": output.get("bomba", 0),
            }
            data["outputs"][slot] = raw_output
            data["outputs_by_tipo"][tipo] = raw_output
            if tipo & 0xF0 not in categories:
                continue
            category, name = categories[tipo & 0xF0]
            entity = {**common, "label": common["label"] or f"{name} {output_id + 1}"}
            if category == "tanks":
                tank = output.get("tanque") or {}
                if not isinstance(tank, dict):
                    raise ValueError("Invalid cloud tank state")
                entity.update(
                    modo=tank.get("modo", 0), nivel=tank.get("nivel", 0),
                    tipo_flotante=tank.get("tipo", 0),
                )
            elif category == "ciclon":
                ciclon = output.get("ciclon") or {}
                if not isinstance(ciclon, dict):
                    raise ValueError("Invalid cloud cyclone state")
                entity.update({
                    dest: ciclon[source] for source, dest in (
                        ("modo_ante_tareas", "modo_ante_tareas"),
                        ("modo_fin_de_tareas", "modo_fin_de_tareas"),
                        ("modo_tiempo", "modo_tiempo"),
                        ("d_ante_tareas_s", "d_ante_tareas"),
                        ("d_fin_de_tareas_s", "d_fin_de_tareas"),
                        ("bomba_marcha_duracion_min", "bomba_marcha_duracion"),
                        ("proximo_ciclon", "proximo_ciclon"),
                    ) if source in ciclon
                })
            data[category][output_id] = entity
        for schedule in pic.get("horarios") or []:
            if schedule is None:
                continue
            if not isinstance(schedule, dict):
                raise ValueError("Invalid cloud schedule")
            index = schedule["i"]
            data["riegos"][index] = {
                "id": index, "slot_id": index, "estado": schedule.get("estado", 0),
                "enabled": schedule.get("habilitado", 0),
                "label": schedule.get("desc") or f"Riego {chr(65 + index)}",
                "use_sensor_lluvia": schedule.get("accesorios", 0) & 1,
                "active_zona": schedule.get("zona_activa", 0),
                "duracion": schedule.get("duracion", 0),
                "zonas": {
                    f"duracion_{i + 1}": minutes
                    for i, minutes in enumerate(schedule.get("zonas_min") or [])
                },
            }
        irrigation = pic.get("riego") or {}
        if not isinstance(irrigation, dict):
            raise ValueError("Invalid cloud irrigation state")
        data.update(
            auto_riego=bool(irrigation.get("modo", 0)),
            active_horario=irrigation.get("horario_activo", 0),
            lluvia_bloqueado=bool(irrigation.get("lluvia", 0)),
        )
        for source, dest in (("bateria", "bateria"), ("esp_resets", "esp_reset_count")):
            if source in pic:
                data[dest] = pic[source]
        if isinstance(pic.get("uart"), dict) and "resets" in pic["uart"]:
            data["uart_reset_count"] = pic["uart"]["resets"]
        for index, task in enumerate(pic.get("tareas") or []):
            if task is not None:
                if not isinstance(task, dict):
                    raise ValueError("Invalid cloud task")
                data["tareas"][index] = {
                    "id": index, "tipo": f"{task.get('tipo', 0):02X}",
                    "modo": task.get("modo", 0), "duracion": task.get("restante", 0),
                }

        self._data = data
        self.device_id_ready.set()
        self.mac_ready.clear()
        if (
            isinstance(pic.get("salidas"), list)
            and state.get("online") is not False
            and not any(
                state.get(key) for key in ("sin_respuesta", "pic_falla", "error_formato")
            )
        ):
            self.data_ready.set()
        else:
            self.data_ready.clear()
        esp = state.get("esp") or {}
        if not isinstance(esp, dict):
            raise ValueError("Invalid cloud ESP state")
        await super()._process_text(json.dumps({**esp, "id": data["device_id"]}))
