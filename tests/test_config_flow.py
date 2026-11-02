"""Tests for Hidromotic config-flow validation."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.hidromotic.config_flow import (
    CannotConnect,
    HidromoticConfigFlow,
    validate_input,
)
from custom_components.hidromotic.const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_TYPE_CLOUD,
    CONNECTION_TYPE_LOCAL,
)


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

    async def test_validate_input_rejects_failed_connection(self) -> None:
        client = MagicMock()
        client.connect = AsyncMock(return_value=False)
        client.disconnect = AsyncMock()

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

    async def test_validate_input_maps_initial_data_timeout(self) -> None:
        client = MagicMock()
        client.connect = AsyncMock(return_value=True)
        client.disconnect = AsyncMock()
        client.data_ready = asyncio.Event()
        client.mac_ready = asyncio.Event()
        client.data = {}

        with (
            patch(
                "custom_components.hidromotic.config_flow.async_get_clientsession",
                return_value=object(),
            ),
            patch(
                "custom_components.hidromotic.config_flow.HidromoticClient",
                return_value=client,
            ),
            patch(
                "custom_components.hidromotic.config_flow.INITIAL_DATA_WAIT_SECONDS",
                0.001,
            ),
        ):
            with self.assertRaises(CannotConnect):
                await validate_input(MagicMock(), {"host": "chi.local"})

        client.disconnect.assert_awaited_once()

    async def test_user_flow_shows_form_and_maps_connection_errors(self) -> None:
        flow = HidromoticConfigFlow()
        form = await flow.async_step_user()
        self.assertEqual(form["step_id"], "user")

        with patch(
            "custom_components.hidromotic.config_flow.validate_input",
            AsyncMock(side_effect=CannotConnect),
        ):
            result = await flow.async_step_local({"host": "chi.local"})
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {"base": "cannot_connect"})

    async def test_user_flow_maps_unexpected_errors(self) -> None:
        flow = HidromoticConfigFlow()
        with patch(
            "custom_components.hidromotic.config_flow.validate_input",
            AsyncMock(side_effect=RuntimeError("unexpected")),
        ):
            result = await flow.async_step_local({"host": "chi.local"})

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {"base": "unknown"})

    async def test_user_flow_creates_entry_for_valid_device(self) -> None:
        flow = HidromoticConfigFlow()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

        with patch(
            "custom_components.hidromotic.config_flow.validate_input",
            AsyncMock(
                return_value={
                    "title": "CHI Smart (chi.local)",
                    "device_id": "aabbccddeeff",
                }
            ),
        ):
            result = await flow.async_step_local({"host": "chi.local"})

        self.assertEqual(result, {"type": "create_entry"})
        flow.async_set_unique_id.assert_awaited_once_with("aabbccddeeff")
        flow._abort_if_unique_id_configured.assert_called_once_with(
            updates={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                "host": "chi.local",
            }
        )
        flow.async_create_entry.assert_called_once_with(
            title="CHI Smart (chi.local)",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                "host": "chi.local",
            },
        )

    async def test_user_flow_routes_to_selected_connection_method(self) -> None:
        flow = HidromoticConfigFlow()
        flow.async_step_cloud = AsyncMock(return_value={"type": "form"})
        flow.async_step_local = AsyncMock(return_value={"type": "form"})

        await flow.async_step_user({CONF_CONNECTION_TYPE: CONNECTION_TYPE_CLOUD})
        flow.async_step_cloud.assert_awaited_once()

        await flow.async_step_user({CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL})
        flow.async_step_local.assert_awaited_once()

    async def test_cloud_validation_uses_account_client_and_persists_identity(self) -> None:
        client = MagicMock()
        client.connect = AsyncMock(return_value=True)
        client.disconnect = AsyncMock()
        client.data_ready = asyncio.Event()
        client.data_ready.set()
        client.mac_ready = asyncio.Event()
        client.mac_ready.set()
        client.data = {"mac": "AA:BB:CC:DD:EE:FF", "is_mini": False}
        session = object()

        with (
            patch(
                "custom_components.hidromotic.config_flow.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.hidromotic.config_flow.HidromoticCloudClient",
                return_value=client,
            ) as cloud_client,
        ):
            result = await validate_input(
                MagicMock(),
                {
                    CONF_CONNECTION_TYPE: CONNECTION_TYPE_CLOUD,
                    "username": "account",
                    "password": "secret",
                },
            )

        cloud_client.assert_called_once_with(
            "account",
            "secret",
            session=session,
        )
        self.assertEqual(
            result,
            {
                "title": "CHI Smart (Cloud)",
                "device_id": "aabbccddeeff",
            },
        )
        client.disconnect.assert_awaited_once()
