"""Tests for coordinator lifecycle, data forwarding, and commands."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.hidromotic.coordinator import HidromoticCoordinator


class HidromoticCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.client.host = "chi.local"
        self.client.connected = True
        self.client.data_ready = asyncio.Event()
        self.client.mac_ready = asyncio.Event()
        self.client.data = {"zones": {0: {}}}
        self.client.connect = AsyncMock(return_value=True)
        self.client.disconnect = AsyncMock()
        self.client.register_callback = MagicMock(return_value=MagicMock())
        self.entry = MagicMock()
        self.coordinator = HidromoticCoordinator(MagicMock(), self.client, self.entry)

    async def test_setup_waits_for_configuration_and_mac(self) -> None:
        self.client.data_ready.set()
        self.client.mac_ready.set()
        self.coordinator.async_set_updated_data = MagicMock()

        self.assertTrue(await self.coordinator.async_setup())

        self.client.register_callback.assert_called_once_with(
            self.coordinator._on_data_update
        )
        self.coordinator.async_set_updated_data.assert_called_once_with(self.client.data)

    async def test_setup_returns_false_on_connection_failure_and_timeout(self) -> None:
        self.client.connect.return_value = False
        self.assertFalse(await self.coordinator.async_setup())

        self.client.connect.return_value = True
        with patch(
            "custom_components.hidromotic.coordinator.INITIAL_DATA_WAIT_SECONDS",
            0.001,
        ):
            self.assertFalse(await self.coordinator.async_setup())

    async def test_shutdown_unregisters_callback_and_disconnects(self) -> None:
        await self.coordinator.async_setup()
        await self.coordinator.async_shutdown()

        self.client.disconnect.assert_awaited_once()

    async def test_data_update_marks_coordinator_unavailable_and_recovers(self) -> None:
        self.coordinator._has_received_initial_data = True
        self.client.connected = False
        self.coordinator._on_data_update({})
        self.assertFalse(self.coordinator.last_update_success)

        self.client.connected = True
        self.client.data_ready.set()
        self.coordinator._on_data_update(self.client.data)
        self.assertTrue(self.coordinator.last_update_success)
        self.assertIs(self.coordinator.data, self.client.data)

    async def test_command_and_getter_methods_delegate_to_client(self) -> None:
        command_methods = {
            "async_set_zone_state": "set_zone_state",
            "async_set_tank_state": "set_tank_state",
            "async_set_pool_state": "set_pool_state",
            "async_set_manguera_state": "set_manguera_state",
            "async_set_ciclon_state": "set_ciclon_state",
            "async_set_riego_state": "set_riego_state",
        }
        for method in command_methods.values():
            setattr(self.client, method, AsyncMock())

        for coordinator_method, client_method in command_methods.items():
            await getattr(self.coordinator, coordinator_method)(1, True)
            getattr(self.client, client_method).assert_awaited_once_with(1, True)
            getattr(self.client, client_method).reset_mock()

        self.client.refresh = AsyncMock()
        await self.coordinator.async_refresh_data()
        self.client.refresh.assert_awaited_once()

        for name in ("zones", "tanks", "pools", "mangueras", "riegos", "ciclon", "pump"):
            method = getattr(self.client, f"get_{name}")
            method.return_value = {name: {}}
            self.assertEqual(getattr(self.coordinator, f"get_{name}")(), {name: {}})
