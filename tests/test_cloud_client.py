"""Tests for the Hidromotic account-cloud transport."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.hidromotic.cloud_client import HidromoticCloudClient


class FakeResponse:
    def __init__(self) -> None:
        self.read = AsyncMock(return_value=b"")
        self.raise_for_status = MagicMock()

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
            "https://hidromotic.com/",
            data={"u": "account", "p": "password"},
        )
        response.read.assert_awaited_once()
        response.raise_for_status.assert_called_once()
        session.ws_connect.assert_awaited_once_with(
            "wss://hidromotic.com/ws",
            heartbeat=30,
        )
        self.assertEqual(
            [call.args[0] for call in send.await_args_list],
            ["e.d", "#@C;"],
        )
        await client.disconnect()
        self.assertTrue(websocket.closed)

    async def test_commands_are_sent_as_raw_cloud_protocol_text(self) -> None:
        websocket = BlockingWebSocket()
        client = HidromoticCloudClient("account", "password")
        client._ws = websocket

        with patch(
            "custom_components.hidromotic.client.asyncio.sleep",
            new=AsyncMock(),
        ):
            await client._send_command("e.d")
            await client._send_command("#@C;")

        self.assertEqual(
            [call.args[0] for call in websocket.send_str.await_args_list],
            ["e.d", "#@C;"],
        )
