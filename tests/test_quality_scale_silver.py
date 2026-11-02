"""Tests for Silver quality-scale requirements."""

import asyncio
import unittest
from unittest.mock import MagicMock

from custom_components.hidromotic import (
    binary_sensor,
    button,
    number,
    select,
    sensor,
    switch,
)
from custom_components.hidromotic.coordinator import HidromoticCoordinator


class HidromoticSilverRequirementTests(unittest.TestCase):
    def test_platforms_define_parallel_update_limits(self) -> None:
        self.assertEqual(switch.PARALLEL_UPDATES, 1)
        self.assertEqual(number.PARALLEL_UPDATES, 1)
        self.assertEqual(button.PARALLEL_UPDATES, 1)
        self.assertEqual(sensor.PARALLEL_UPDATES, 0)
        self.assertEqual(binary_sensor.PARALLEL_UPDATES, 0)
        self.assertEqual(select.PARALLEL_UPDATES, 1)

    def test_coordinator_logs_only_connection_state_transitions(self) -> None:
        coordinator = object.__new__(HidromoticCoordinator)
        coordinator.client = MagicMock(host="chi.local", connected=False)
        coordinator.client.data_ready = asyncio.Event()
        coordinator._has_received_initial_data = True
        coordinator.last_update_success = True
        coordinator.async_update_listeners = MagicMock()
        coordinator.async_set_updated_data = MagicMock()

        with self.assertLogs("custom_components.hidromotic.coordinator", "INFO") as logs:
            coordinator._on_data_update({})
            coordinator._on_data_update({})

        self.assertEqual(len(logs.records), 1)
        self.assertIn("was lost", logs.records[0].message)
        self.assertFalse(coordinator.last_update_success)
        coordinator.async_update_listeners.assert_called_once()

        coordinator.client.connected = True
        coordinator.client.data_ready.set()
        with self.assertLogs("custom_components.hidromotic.coordinator", "INFO") as logs:
            coordinator._on_data_update({"zones": {}})

        self.assertEqual(len(logs.records), 1)
        self.assertIn("restored", logs.records[0].message)
        coordinator.async_set_updated_data.assert_called_once_with({"zones": {}})
