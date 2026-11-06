"""Tests for Hidromotic config-entry setup and unloading."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from awesomeversion import AwesomeVersion
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.hidromotic import async_setup_entry, async_unload_entry
from custom_components.hidromotic.const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_TYPE_CLOUD,
)


class HidromoticSetupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.hass = MagicMock()
        self.hass.config_entries.async_entries.return_value = []
        self.entry = MagicMock()
        self.entry.data = {"host": "chi.local"}
        self.entry.entry_id = "entry-1"
        self.entry.unique_id = "aabbccddeeff"
        self.client = MagicMock()
        self.client.data = {
            "mac": "AA:BB:CC:DD:EE:FF",
            "device_id": "CHI/C985AB",
        }
        self.coordinator = MagicMock()
        self.coordinator.async_setup = AsyncMock(return_value=True)
        self.coordinator.async_shutdown = AsyncMock()
        self.integration = MagicMock(version=AwesomeVersion("1.0.53"))
        self.integration_lookup = AsyncMock(return_value=self.integration)
        self.hass.config_entries.async_forward_entry_setups = AsyncMock()
        self.coordinator_factory_patch = patch(
            "custom_components.hidromotic.HidromoticCoordinator",
            return_value=self.coordinator,
        )
        self.coordinator_factory = self.coordinator_factory_patch.start()
        self.addCleanup(self.coordinator_factory_patch.stop)
        self.patches = [
            patch(
                "custom_components.hidromotic.async_get_clientsession",
                return_value=object(),
            ),
            patch(
                "custom_components.hidromotic.async_get_integration",
                new=self.integration_lookup,
            ),
            patch(
                "custom_components.hidromotic.HidromoticClient",
                return_value=self.client,
            ),
        ]
        for mocked in self.patches:
            mocked.start()
            self.addCleanup(mocked.stop)

    async def test_setup_entry_initializes_coordinator_and_platforms(self) -> None:
        result = await async_setup_entry(self.hass, self.entry)

        self.assertTrue(result)
        self.assertIs(self.entry.runtime_data, self.coordinator)
        self.coordinator_factory.assert_called_once_with(
            self.hass, self.client, self.entry, "1.0.53"
        )
        self.integration_lookup.assert_awaited_once_with(self.hass, "hidromotic")
        self.hass.config_entries.async_forward_entry_setups.assert_awaited_once()

    async def test_setup_entry_selects_cloud_client_from_config_entry(self) -> None:
        self.entry.unique_id = "chi_c985ab"
        self.entry.data = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_CLOUD,
            "username": "account",
            "password": "secret",
        }
        session = object()
        with (
            patch(
                "custom_components.hidromotic.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.hidromotic.HidromoticCloudClient",
                return_value=self.client,
            ) as cloud_client,
        ):
            await async_setup_entry(self.hass, self.entry)

        cloud_client.assert_called_once_with(
            "account",
            "secret",
            session=session,
            device_id="chi_c985ab",
        )

    async def test_setup_entry_migrates_mac_unique_id_to_device_id(self) -> None:
        self.entry.unique_id = "aabbccddeeff"

        await async_setup_entry(self.hass, self.entry)

        self.hass.config_entries.async_update_entry.assert_called_once_with(
            self.entry, unique_id="chi_c985ab"
        )

    async def test_setup_entry_rejects_connection_or_identity_failures(self) -> None:
        self.coordinator.async_setup.return_value = False
        with self.assertRaises(ConfigEntryNotReady):
            await async_setup_entry(self.hass, self.entry)
        self.coordinator.async_shutdown.assert_awaited_once()

        self.coordinator.async_setup.return_value = True
        self.client.data = {"mac": "AA:BB:CC:DD:EE:FF", "device_id": "invalid"}
        with self.assertRaises(ConfigEntryNotReady):
            await async_setup_entry(self.hass, self.entry)
        self.assertEqual(self.coordinator.async_shutdown.await_count, 2)

    async def test_setup_entry_rejects_duplicate_device_id(self) -> None:
        self.entry.unique_id = "other-id"
        duplicate = MagicMock(entry_id="entry-2", unique_id="chi_c985ab")
        self.hass.config_entries.async_entries.return_value = [self.entry, duplicate]

        with self.assertRaises(ConfigEntryNotReady):
            await async_setup_entry(self.hass, self.entry)

        self.coordinator.async_shutdown.assert_awaited_once()

    async def test_unload_shuts_down_only_after_platforms_unload(self) -> None:
        self.entry.runtime_data = self.coordinator
        self.hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        self.assertTrue(await async_unload_entry(self.hass, self.entry))
        self.coordinator.async_shutdown.assert_awaited_once()

        self.coordinator.async_shutdown.reset_mock()
        self.hass.config_entries.async_unload_platforms.return_value = False
        self.assertFalse(await async_unload_entry(self.hass, self.entry))
        self.coordinator.async_shutdown.assert_not_awaited()
