"""Cloud WebSocket transport for Hidromotic accounts."""

from __future__ import annotations

import asyncio
import logging

import aiohttp
from homeassistant.exceptions import HomeAssistantError

from .client import HidromoticClient

_LOGGER = logging.getLogger(__name__)


class HidromoticCloudClient(HidromoticClient):
    """Connect to the account cloud while reusing the local protocol parser."""

    LOGIN_URL = "https://hidromotic.com/"
    WEBSOCKET_URL = "wss://hidromotic.com/ws"

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        super().__init__("hidromotic.com", session=session)
        self._username = username
        self._password = password

    async def connect(self) -> bool:
        """Log in, open the cloud socket, and request initial device data."""
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()
                self._owns_session = True

            async with self._session.post(
                self.LOGIN_URL,
                data={"u": self._username, "p": self._password},
            ) as response:
                await response.read()
                response.raise_for_status()

            self._ws = await self._session.ws_connect(
                self.WEBSOCKET_URL,
                heartbeat=30,
            )
            self._set_connected(True)
            self._listener_task = asyncio.create_task(self._listen())

            await self._send_command("e.d")
            await self._send_command("#@C;")
        except (aiohttp.ClientError, HomeAssistantError, OSError, TimeoutError) as err:
            _LOGGER.debug("Failed to connect to Hidromotic cloud: %s", err)
            self._set_connected(False)
            return False

        return True

    async def _send_command(self, command: str) -> None:
        """Send raw cloud protocol commands, unlike local JSON-RPC requests."""
        await self._send_text_payload(command, command)
