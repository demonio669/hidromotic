"""Tests for Hidromotic config-flow validation."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.hidromotic.config_flow import CannotConnect, validate_input


class HidromoticConfigFlowValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_validate_input_uses_normalized_device_mac(self) -> None:
        client = MagicMock()
        client.connect = AsyncMock(return_value=True)
        client.disconnect = AsyncMock()
        client.data_ready = asyncio.Event()
        client.data_ready.set()
        client.mac_ready = asyncio.Event()
        client.mac_ready.set()
        client.data = {"mac": "AA:BB:CC:DD:EE:FF", "is_mini": True}

        with (
            patch(
                "custom_components.hidromotic.config_flow.async_get_clientsession",
                return_value=object(),
            ),
            patch(
                "custom_components.hidromotic.config_flow.HidromoticClient",
                return_value=client,
            ),
        ):
            result = await validate_input(MagicMock(), {"host": "chi.local"})

        self.assertEqual(
            result,
            {
                "title": "CHI Smart Mini (chi.local)",
                "device_id": "aabbccddeeff",
            },
        )
        client.disconnect.assert_awaited_once()

    async def test_validate_input_rejects_missing_or_invalid_mac(self) -> None:
        client = MagicMock()
        client.connect = AsyncMock(return_value=True)
        client.disconnect = AsyncMock()
        client.data_ready = asyncio.Event()
        client.data_ready.set()
        client.mac_ready = asyncio.Event()
        client.mac_ready.set()
        client.data = {"mac": "unknown", "is_mini": False}

        with (
            patch(
                "custom_components.hidromotic.config_flow.async_get_clientsession",
                return_value=object(),
            ),
            patch(
                "custom_components.hidromotic.config_flow.HidromoticClient",
                return_value=client,
            ),
        ):
            with self.assertRaises(CannotConnect):
                await validate_input(MagicMock(), {"host": "chi.local"})

        client.disconnect.assert_awaited_once()
