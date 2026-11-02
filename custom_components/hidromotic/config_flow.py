"""Config flow for Hidromotic integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector

from .client import HidromoticClient, normalize_mac_address
from .cloud_client import HidromoticCloudClient
from .const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_TYPE_CLOUD,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
    INITIAL_DATA_WAIT_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_TYPE_LOCAL): vol.In(
            [CONNECTION_TYPE_LOCAL, CONNECTION_TYPE_CLOUD]
        ),
    }
)
STEP_LOCAL_DATA_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})
STEP_CLOUD_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): TextSelector({"type": "password"}),
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    session = async_get_clientsession(hass)
    connection_type = data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_LOCAL)
    if connection_type == CONNECTION_TYPE_CLOUD:
        client = HidromoticCloudClient(
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            session=session,
        )
    else:
        client = HidromoticClient(data[CONF_HOST], session=session)

    try:
        if not await client.connect():
            raise CannotConnect

        try:
            await asyncio.wait_for(
                asyncio.gather(client.data_ready.wait(), client.mac_ready.wait()),
                timeout=INITIAL_DATA_WAIT_SECONDS,
            )
        except TimeoutError:
            _LOGGER.error("Timeout esperando configuración y MAC del dispositivo")
            raise CannotConnect

        device_id = normalize_mac_address(client.data.get("mac"))
        if device_id is None:
            _LOGGER.error("El dispositivo no informó una dirección MAC válida")
            raise CannotConnect

        is_mini = client.data.get("is_mini", False)
        name = "CHI Smart Mini" if is_mini else "CHI Smart"
        title = (
            f"{name} (Cloud)"
            if connection_type == CONNECTION_TYPE_CLOUD
            else f"{name} ({data[CONF_HOST]})"
        )

    finally:
        await client.disconnect()

    return {"title": title, "device_id": device_id}


class HidromoticConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hidromotic."""

    VERSION = 1

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a connection method when reconfiguring an existing device."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            if user_input[CONF_CONNECTION_TYPE] == CONNECTION_TYPE_CLOUD:
                return await self.async_step_reconfigure_cloud()
            return await self.async_step_reconfigure_local()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONNECTION_TYPE,
                        default=entry.data.get(
                            CONF_CONNECTION_TYPE, CONNECTION_TYPE_LOCAL
                        ),
                    ): vol.In([CONNECTION_TYPE_LOCAL, CONNECTION_TYPE_CLOUD]),
                }
            ),
        )

    async def async_step_reconfigure_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update the direct connection host."""
        entry = self._get_reconfigure_entry()
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST, "")): str
            }
        )
        return await self._async_reconfigure_connection(
            user_input, CONNECTION_TYPE_LOCAL, schema, "reconfigure_local"
        )

    async def async_step_reconfigure_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update the Hidromotic Cloud account credentials."""
        entry = self._get_reconfigure_entry()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")
                ): str,
                vol.Required(CONF_PASSWORD): TextSelector({"type": "password"}),
            }
        )
        return await self._async_reconfigure_connection(
            user_input, CONNECTION_TYPE_CLOUD, schema, "reconfigure_cloud"
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose local or cloud connectivity."""
        if user_input is not None:
            if user_input[CONF_CONNECTION_TYPE] == CONNECTION_TYPE_CLOUD:
                return await self.async_step_cloud()
            return await self.async_step_local()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
        )

    async def async_step_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a direct connection to the CHI."""
        return await self._async_finish_connection(
            user_input,
            CONNECTION_TYPE_LOCAL,
            STEP_LOCAL_DATA_SCHEMA,
            "local",
        )

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a connection through the Hidromotic account cloud."""
        return await self._async_finish_connection(
            user_input,
            CONNECTION_TYPE_CLOUD,
            STEP_CLOUD_DATA_SCHEMA,
            "cloud",
        )

    async def _async_finish_connection(
        self,
        user_input: dict[str, Any] | None,
        connection_type: str,
        schema: vol.Schema,
        step_id: str,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_CONNECTION_TYPE: connection_type, **user_input}
            try:
                info = await validate_input(self.hass, data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["device_id"])
                self._abort_if_unique_id_configured(updates=data)
                return self.async_create_entry(title=info["title"], data=data)

        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors,
        )

    async def _async_reconfigure_connection(
        self,
        user_input: dict[str, Any] | None,
        connection_type: str,
        schema: vol.Schema,
        step_id: str,
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_CONNECTION_TYPE: connection_type, **user_input}
            try:
                info = await validate_input(self.hass, data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception while reconfiguring")
                errors["base"] = "unknown"
            else:
                if normalize_mac_address(entry.unique_id) != info["device_id"]:
                    errors["base"] = "different_device"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data=data,
                        title=info["title"],
                    )

        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
