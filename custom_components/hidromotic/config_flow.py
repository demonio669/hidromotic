"""Config flow for Hidromotic integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, INITIAL_DATA_WAIT_SECONDS
from .client import HidromoticClient, hex_to_int, int_to_hex

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    client = HidromoticClient(data[CONF_HOST])
    initial_data_event = asyncio.Event()

    def _on_initial_data(_: dict[str, Any]) -> None:
        """Callback para cuando lleguen los primeros datos."""
        if not initial_data_event.is_set():
            initial_data_event.set()

    remove_callback = None
    try:
        # Registramos un callback temporal para escuchar el primer paquete
        remove_callback = client.register_callback(_on_initial_data)

        if not await client.connect():
            raise CannotConnect

        # Esperamos dinámicamente hasta recibir datos o agotar el tiempo
        try:
            async with asyncio.timeout(INITIAL_DATA_WAIT_SECONDS):
                await initial_data_event.wait()
        except TimeoutError:
            _LOGGER.warning("Tiempo agotado esperando datos iniciales (pic_id) del dispositivo")

        # Get device info
        device_id = client.data.get("pic_id", "unknown")
        is_mini = client.data.get("is_mini", False)
        name = "CHI Smart Mini" if is_mini else "CHI Smart"

    finally:
        # Limpiamos el callback de forma segura
        if remove_callback:
            try:
                remove_callback()
            except ValueError:
                pass
        await client.disconnect()

    # Convertimos explícitamente a string
    return {"title": f"{name} ({data[CONF_HOST]})", "device_id": str(device_id)}


class HidromoticConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hidromotic."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                device_id = info["device_id"]

                if device_id == "unknown":
                    device_id = user_input[CONF_HOST]

                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: user_input[CONF_HOST]})

                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
