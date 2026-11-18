"""Exercise installation, events, options and unload against Home Assistant."""

import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import voluptuous_serialize
from homeassistant import bootstrap, config_entries, loader
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.price_spike_filter.config_flow import settings_schema
from custom_components.price_spike_filter.const import DOMAIN
from custom_components.price_spike_filter.diagnostics import async_get_config_entry_diagnostics
from custom_components.price_spike_filter.model import Settings


class HomeAssistantTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        component = Path(__file__).parents[1] / "custom_components" / DOMAIN
        shutil.copytree(
            component,
            Path(self.directory.name) / "custom_components" / DOMAIN,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        self.hass = HomeAssistant(self.directory.name)
        self.hass.config.skip_pip = True
        loader.async_setup(self.hass)
        self.hass.config_entries = config_entries.ConfigEntries(self.hass, {})
        await bootstrap.async_load_base_functionality(self.hass)
        await async_setup_component(self.hass, "homeassistant", {})
        self.source = "sensor.test_amber_price"
        self.source_attributes = self.forecast_attributes()
        self.hass.states.async_set(self.source, "0.3", self.source_attributes)

    def forecast_attributes(self):
        now = dt_util.utcnow()
        return {
            "unit_of_measurement": "$/kWh",
            "start_time": now.isoformat(),
            "end_time": (now + timedelta(minutes=5)).isoformat(),
            "forecast": [
                {"time": (now + timedelta(hours=index)).isoformat(), "value": 10 if index == 24 else 0.2}
                for index in range(48)
            ],
        }

    async def add_entry(self, options=None):
        entry = config_entries.ConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="Test prices",
            data={"name": "Test prices", "source_entity": self.source},
            options=options or {},
            source="user",
            unique_id=self.source,
            discovery_keys={},
            subentries_data=[],
        )
        await self.hass.config_entries.async_add(entry)
        await self.hass.async_block_till_done()
        self.assertEqual(entry.state, config_entries.ConfigEntryState.LOADED)
        return entry

    def sensor_id(self, entry, kind):
        return er.async_get(self.hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{kind}")

    async def asyncTearDown(self):
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.state == config_entries.ConfigEntryState.LOADED:
                await self.hass.config_entries.async_unload(entry.entry_id)
        await self.hass.async_stop(force=True)
        self.directory.cleanup()

    async def test_install_publishes_haeo_forecasts_and_recovers_from_source_failure(self):
        entry = await self.add_entry()
        filtered_id = self.sensor_id(entry, "filtered")
        filtered = self.hass.states.get(filtered_id)
        self.assertEqual(float(filtered.state), 0.3)
        self.assertEqual(filtered.attributes["interpolation_mode"], "previous")
        raw = self.hass.states.get(self.sensor_id(entry, "raw"))
        peak_time = self.source_attributes["forecast"][24]["time"]
        raw_peak = next(point["value"] for point in raw.attributes["forecast"] if point["time"] == peak_time)
        filtered_peak = next(point["value"] for point in filtered.attributes["forecast"] if point["time"] == peak_time)
        self.assertEqual(raw_peak, 10)
        self.assertLess(filtered_peak, 0.25)
        self.assertEqual(self.hass.states.get(self.source).attributes, self.source_attributes)
        with patch.object(self.hass.services, "async_call", new_callable=AsyncMock) as calls:
            self.hass.states.async_set(self.source, "unavailable")
            await entry.runtime_data.async_refresh()
            await self.hass.async_block_till_done()
            failed = self.hass.states.get(filtered_id)
            self.assertEqual(failed.state, "unavailable")
            self.assertNotIn("forecast", failed.attributes)
            self.hass.states.async_set(self.source, "0.3", self.forecast_attributes())
            await entry.runtime_data.async_refresh()
            await self.hass.async_block_till_done()
            self.assertEqual(float(self.hass.states.get(filtered_id).state), 0.3)
            calls.assert_not_awaited()
        coordinator = entry.runtime_data
        await self.hass.config_entries.async_unload(entry.entry_id)
        self.assertIsNone(coordinator._unsubscribe)

    async def test_options_reload_disables_filter_without_changing_entity_identity(self):
        entry = await self.add_entry()
        identity = self.sensor_id(entry, "filtered")
        result = await self.hass.config_entries.options.async_init(entry.entry_id)
        submitted = {
            **{key: getattr(Settings(), key) for key in Settings.__dataclass_fields__},
            "enabled": False,
        }
        result = await self.hass.config_entries.options.async_configure(result["flow_id"], submitted)
        self.assertEqual(result["type"], "create_entry")
        await self.hass.async_block_till_done()
        self.assertEqual(self.sensor_id(entry, "filtered"), identity)
        self.assertFalse(entry.runtime_data.settings.enabled)
        self.assertEqual(entry.runtime_data.data.raw, entry.runtime_data.data.filtered)

    async def test_config_flow_validates_source_and_prevents_duplicates(self):
        result = await self.hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        bad = await self.hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"name": "Test", "source_entity": "sensor.missing"},
        )
        self.assertEqual(bad["errors"], {"source_entity": "invalid_source"})
        good = await self.hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"name": "Test", "source_entity": self.source},
        )
        self.assertEqual(good["type"], "create_entry")
        await self.hass.async_block_till_done()
        duplicate = await self.hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        duplicate = await self.hass.config_entries.flow.async_configure(
            duplicate["flow_id"],
            {"name": "Another", "source_entity": self.source},
        )
        self.assertEqual(duplicate["reason"], "already_configured")

    async def test_source_rename_is_resolved_and_diagnostics_redact_identifiers(self):
        registry = er.async_get(self.hass)
        registered = registry.async_get_or_create(
            "sensor", "test_source", "private_source_id", suggested_object_id="test_amber_price"
        )
        entry = config_entries.ConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="Test prices",
            data={"source_entity": self.source, "source_registry_id": registered.id},
            options={},
            source="user",
            unique_id=registered.id,
            discovery_keys={},
            subentries_data=[],
        )
        await self.hass.config_entries.async_add(entry)
        await self.hass.async_block_till_done()
        renamed = "sensor.renamed_amber_price"
        registry.async_update_entity(registered.entity_id, new_entity_id=renamed)
        self.hass.states.async_set(renamed, "0.3", self.forecast_attributes())
        await entry.runtime_data.async_refresh()
        self.assertEqual(entry.runtime_data._source, renamed)
        diagnostics = await async_get_config_entry_diagnostics(self.hass, entry)
        self.assertNotIn("renamed_amber_price", repr(diagnostics))
        self.assertNotIn("private_source_id", repr(diagnostics))

    async def test_stale_input_cannot_keep_a_usable_forecast(self):
        entry = await self.add_entry()
        with patch(
            "custom_components.price_spike_filter.coordinator.dt_util.utcnow",
            return_value=dt_util.utcnow() + timedelta(hours=1),
        ):
            await entry.runtime_data.async_refresh()
        self.assertFalse(entry.runtime_data.last_update_success)

    async def test_numeric_options_serialize_for_the_ui(self):
        fields = voluptuous_serialize.convert(settings_schema({}), custom_serializer=cv.custom_serializer)
        numeric = [field for field in fields if field["name"] == "spike_scale"]
        self.assertIn("number", numeric[0]["selector"])
