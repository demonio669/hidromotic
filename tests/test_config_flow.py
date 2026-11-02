"""Tests for Hidromotic config-flow validation."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.hidromotic.client import normalize_device_identifier
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
    async def test_device_identifier_is_normalized_and_validated(self) -> None:
        self.assertEqual(normalize_device_identifier("CHI/7096C4"), "chi_7096c4")
        self.assertEqual(
            normalize_device_identifier(" chi/C985AB "), "chi_c985ab"
        )
        self.assertIsNone(normalize_device_identifier("CHI/"))
        self.assertIsNone(normalize_device_identifier("CHI/C9/5AB"))
        self.assertIsNone(normalize_device_identifier(None))

    async def test_validate_input_uses_normalized_device_identifier(self) -> None:
        client = MagicMock()
        client.connect = AsyncMock(return_value=True)
        client.disconnect = AsyncMock()
        client.data_ready = asyncio.Event()
        client.data_ready.set()
        client.device_id_ready = asyncio.Event()
        client.device_id_ready.set()
        client.data = {"device_id": "CHI/7096C4", "is_mini": True}

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
                "device_id": "chi_7096c4",
            },
        )
        client.disconnect.assert_awaited_once()

    async def test_validate_input_rejects_missing_or_invalid_device_id(self) -> None:
        client = MagicMock()
        client.connect = AsyncMock(return_value=True)
        client.disconnect = AsyncMock()
        client.data_ready = asyncio.Event()
        client.data_ready.set()
        client.device_id_ready = asyncio.Event()
        client.device_id_ready.set()
        client.data = {"device_id": "unknown", "is_mini": False}

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
        client.device_id_ready = asyncio.Event()
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
                    "device_id": "chi_7096c4",
                }
            ),
        ):
            result = await flow.async_step_local({"host": "chi.local"})

        self.assertEqual(result, {"type": "create_entry"})
        flow.async_set_unique_id.assert_awaited_once_with("chi_7096c4")
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

    async def test_reconfigure_flow_routes_to_selected_connection_method(self) -> None:
        flow = HidromoticConfigFlow()
        entry = MagicMock()
        entry.data = {CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL}
        flow._get_reconfigure_entry = MagicMock(return_value=entry)
        flow.async_step_reconfigure_cloud = AsyncMock(return_value={"type": "form"})
        flow.async_step_reconfigure_local = AsyncMock(return_value={"type": "form"})

        result = await flow.async_step_reconfigure()
        self.assertEqual(result["step_id"], "reconfigure")

        await flow.async_step_reconfigure({CONF_CONNECTION_TYPE: CONNECTION_TYPE_CLOUD})
        flow.async_step_reconfigure_cloud.assert_awaited_once()

        await flow.async_step_reconfigure({CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL})
        flow.async_step_reconfigure_local.assert_awaited_once()

    async def test_reconfigure_updates_existing_entry_for_same_device(self) -> None:
        flow = HidromoticConfigFlow()
        entry = MagicMock()
        entry.unique_id = "chi_7096c4"
        flow._get_reconfigure_entry = MagicMock(return_value=entry)
        flow.async_update_reload_and_abort = MagicMock(
            return_value={"type": "abort"}
        )

        with patch(
            "custom_components.hidromotic.config_flow.validate_input",
            AsyncMock(
                return_value={
                    "title": "CHI Smart (Cloud)",
                    "device_id": "chi_7096c4",
                }
            ),
        ):
            result = await flow.async_step_reconfigure_cloud(
                {"username": "account", "password": "new-secret"}
            )

        self.assertEqual(result, {"type": "abort"})
        flow.async_update_reload_and_abort.assert_called_once_with(
            entry,
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_CLOUD,
                "username": "account",
                "password": "new-secret",
            },
            title="CHI Smart (Cloud)",
        )

    async def test_reconfigure_rejects_a_different_device(self) -> None:
        flow = HidromoticConfigFlow()
        entry = MagicMock()
        entry.unique_id = "chi_7096c4"
        flow._get_reconfigure_entry = MagicMock(return_value=entry)
        flow.async_update_reload_and_abort = MagicMock()

        with patch(
            "custom_components.hidromotic.config_flow.validate_input",
            AsyncMock(
                return_value={
                    "title": "CHI Smart (other)",
                    "device_id": "chi_001122",
                }
            ),
        ):
            result = await flow.async_step_reconfigure_local({"host": "other"})

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {"base": "different_device"})
        flow.async_update_reload_and_abort.assert_not_called()

    async def test_cloud_validation_uses_account_client_and_persists_identity(self) -> None:
        client = MagicMock()
        client.connect = AsyncMock(return_value=True)
        client.disconnect = AsyncMock()
        client.data_ready = asyncio.Event()
        client.data_ready.set()
        client.device_id_ready = asyncio.Event()
        client.device_id_ready.set()
        client.data = {"device_id": "CHI/C985AB", "is_mini": False}
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
                "device_id": "chi_c985ab",
            },
        )
        client.disconnect.assert_awaited_once()
