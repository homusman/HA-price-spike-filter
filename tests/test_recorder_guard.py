"""Verify the patch prevents oversized recording without losing live forecasts."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.components.recorder.db_schema import StateAttributes
from homeassistant.core import Event, State

from custom_components.price_spike_filter.recorder_guard import (
    async_install_amber_guard,
    protect_forecast_class,
    protect_forecast_entity,
)


def entity_type():
    class Forecast:
        def __init__(self):
            self._state_info = {"unrecorded_attributes": frozenset({"already_excluded"})}
            self.async_write_ha_state = Mock()
            self.seen_when_added = None

        async def async_added_to_hass(self):
            self.seen_when_added = self._state_info["unrecorded_attributes"]

    return Forecast


class RecorderGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_entities_are_protected_before_first_publish_and_hook_is_idempotent(self):
        cls = entity_type()
        protect_forecast_class(cls)
        hook = cls.async_added_to_hass
        protect_forecast_class(cls)
        self.assertIs(cls.async_added_to_hass, hook)
        entity = cls()
        await entity.async_added_to_hass()
        self.assertEqual(entity.seen_when_added, {"forecasts", "already_excluded"})

    async def test_only_amber_forecast_entities_are_retrofitted(self):
        cls = entity_type()
        forecast = cls()
        unrelated = entity_type()()
        integration = SimpleNamespace(
            async_get_platform=AsyncMock(return_value=SimpleNamespace(AmberForecastSensor=cls))
        )
        with (
            patch(
                "custom_components.price_spike_filter.recorder_guard.async_get_integration",
                AsyncMock(return_value=integration),
            ),
            patch(
                "custom_components.price_spike_filter.recorder_guard.async_get_platforms",
                return_value=[SimpleNamespace(entities={"renamed_forecast": forecast, "other": unrelated})],
            ),
        ):
            await async_install_amber_guard(Mock(), "amberelectric")
        self.assertIn("forecasts", forecast._state_info["unrecorded_attributes"])
        self.assertNotIn("forecasts", unrelated._state_info["unrecorded_attributes"])
        forecast.async_write_ha_state.assert_called_once()
        unrelated.async_write_ha_state.assert_not_called()

    async def test_real_recorder_serialization_keeps_small_metadata_and_live_data(self):
        entity = entity_type()()
        live = {
            "forecasts": [{"time": str(index), "value": 0.2} for index in range(2000)],
            "unit_of_measurement": "$/kWh",
            "channel_type": "general",
            "already_excluded": "secret",
        }
        self.assertGreater(len(json.dumps(live)), 16384)
        state = State("sensor.home_general_forecast", "0.2", live, state_info=entity._state_info)
        protect_forecast_entity(entity)
        event = Event("state_changed", {"new_state": state})
        with patch("homeassistant.components.recorder.db_schema._LOGGER.warning") as warning:
            saved = json.loads(StateAttributes.shared_attrs_bytes_from_event(event, None))
        warning.assert_not_called()
        self.assertNotIn("forecasts", saved)
        self.assertNotIn("already_excluded", saved)
        self.assertEqual(saved["channel_type"], "general")
        self.assertEqual(state.state, "0.2")
        self.assertEqual(len(state.attributes["forecasts"]), 2000)

    async def test_existing_native_exclusion_is_left_intact(self):
        entity = entity_type()()
        entity._state_info["unrecorded_attributes"] |= {"forecasts"}
        before = entity._state_info["unrecorded_attributes"]
        self.assertFalse(protect_forecast_entity(entity))
        self.assertIs(entity._state_info["unrecorded_attributes"], before)
