"""Tests for the Hidromotic account-cloud transport."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.hidromotic.cloud_client import HidromoticCloudClient


class FakeResponse:
    def __init__(self) -> None:
        self.status = 303
        self.headers = {"Location": "/"}

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
            data={
                "u": "account",
                "p": "5f4dcc3b5aa765d61d8327deb882cf99",
            },
            allow_redirects=False,
        )
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

    async def test_login_rejects_response_without_success_redirect(self) -> None:
        response = FakeResponse()
        response.status = 200
        session = MagicMock()
        session.post.return_value = response
        session.ws_connect = AsyncMock()
        client = HidromoticCloudClient("account", "password", session=session)

        self.assertFalse(await client.connect())
        session.ws_connect.assert_not_awaited()

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
