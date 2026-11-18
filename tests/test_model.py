"""Numerical and parsing regressions, runnable without Home Assistant."""

import importlib
import sys
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

package = ModuleType("price_filter_model_test")
package.__path__ = [str(Path(__file__).parents[1] / "custom_components/price_spike_filter")]
sys.modules.setdefault(package.__name__, package)
model = importlib.import_module("price_filter_model_test.model")
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def attributes(values=None, unit="$/kWh"):
    values = values or [0.2] * 48
    return {
        "unit_of_measurement": unit,
        "forecast": [
            {"time": (NOW + timedelta(hours=index)).isoformat(), "value": value} for index, value in enumerate(values)
        ],
    }


class ModelTests(unittest.TestCase):
    def test_ten_dollar_spike_does_not_raise_the_median_baseline(self):
        values = [0.2] * 48
        values[24] = 10
        snapshot = model.parse_source("0.3", attributes(values), NOW)
        result = model.filter_forecast(snapshot, NOW, model.Settings())
        self.assertEqual(result.raw[24].value, 10)
        self.assertEqual(result.baseline[24].value, 0.2)
        self.assertGreater(result.filtered[24].value, 0.2)
        self.assertLess(result.filtered[24].value, 0.25)
        self.assertEqual(result.current_price, 0.3)
        self.assertEqual(result.filtered[0].value, 0.3)
        self.assertGreater(result.changed_intervals, 0)
        self.assertGreater(result.largest_adjustment, 9)
        self.assertEqual(values[24], 10)

    def test_near_term_window_and_disabled_policy_preserve_prices(self):
        values = [0.2] * 48
        values[1] = 10
        snapshot = model.parse_source("0.3", attributes(values), NOW)
        result = model.filter_forecast(snapshot, NOW, model.Settings())
        self.assertEqual(result.filtered[1].value, 10)
        disabled = model.filter_forecast(snapshot, NOW, model.Settings(enabled=False))
        self.assertEqual(disabled.raw, disabled.filtered)
        self.assertEqual(disabled.changed_intervals, 0)

    def test_timer_releases_suppression_as_a_spike_approaches(self):
        values = [0.2] * 48
        values[24] = 10
        snapshot = model.parse_source("0.3", attributes(values), NOW)
        distant = model.filter_forecast(snapshot, NOW, model.Settings())
        near = model.filter_forecast(snapshot, NOW + timedelta(hours=23.5), model.Settings())
        self.assertLess(distant.filtered[24].value, 0.25)
        self.assertEqual(near.filtered[24].value, 10)

    def test_constant_prices_stay_constant(self):
        for value in (-0.2, 0, 0.2, 10):
            snapshot = model.parse_source(str(value), attributes([value] * 48), NOW)
            result = model.filter_forecast(snapshot, NOW, model.Settings())
            self.assertEqual(result.raw, result.filtered)

    def test_suppression_direction_and_scale_are_configurable(self):
        for spike, direction in ((10, "positive"), (-10, "negative")):
            values = [0.2] * 48
            values[24] = spike
            snapshot = model.parse_source("0.3", attributes(values), NOW)
            base = model.Settings(minimum_retention=1, spike_direction=direction)
            strong = model.filter_forecast(snapshot, NOW, base)
            weak = model.filter_forecast(snapshot, NOW, replace(base, spike_scale=100))
            self.assertLess(abs(strong.filtered[24].value - 0.2), abs(weak.filtered[24].value - 0.2))
            other = "negative" if direction == "positive" else "positive"
            excluded = model.filter_forecast(snapshot, NOW, replace(base, spike_direction=other))
            self.assertEqual(excluded.filtered[24].value, spike)

    def test_duration_weighting_is_independent_of_sampling_density(self):
        hour = timedelta(hours=1)
        regular = tuple(
            model.Point(NOW + index * hour, NOW + (index + 1) * hour, value)
            for index, value in enumerate([0.2, 0.2, 10, 0.2, 0.2])
        )
        dense = [
            model.Point(
                point.start + timedelta(minutes=index * 5),
                point.start + timedelta(minutes=(index + 1) * 5),
                point.value,
            )
            for point in regular[:2]
            for index in range(12)
        ] + list(regular[2:])
        settings = model.Settings()
        a = model.filter_forecast(model.Snapshot(0.2, regular), NOW, settings)
        b = model.filter_forecast(model.Snapshot(0.2, tuple(dense)), NOW, settings)
        self.assertEqual(a.baseline[2].value, b.baseline[24].value)
        self.assertEqual(a.filtered[2].value, b.filtered[24].value)

    def test_cent_units_and_negative_prices_keep_their_sign(self):
        for unit in ("c/kWh", "¢/kWh"):
            snapshot = model.parse_source("-10", attributes([-10, 1000], unit), NOW)
            self.assertEqual(snapshot.current_price, -0.1)
            self.assertEqual(snapshot.points[1].value, 10)

    def test_current_interval_is_inserted_without_overwriting_the_remaining_forecast(self):
        source = attributes([0.5, 0.4])
        source.update({"start_time": NOW.isoformat(), "end_time": (NOW + timedelta(minutes=5)).isoformat()})
        snapshot = model.parse_source("0.3", source, NOW)
        self.assertEqual([point.value for point in snapshot.points], [0.3, 0.5, 0.4])
        self.assertEqual(snapshot.points[1].start, NOW + timedelta(minutes=5))
        self.assertEqual(snapshot.points[0].end, snapshot.points[1].start)

    def test_bad_forecasts_fail_without_publishing_partial_data(self):
        bad = [
            {"unit_of_measurement": "W", "forecast": attributes()["forecast"]},
            {**attributes(), "forecast": []},
            {**attributes(), "forecast": [{"time": NOW.isoformat(), "value": float("nan")}]},
            {**attributes(), "forecast": [{"time": "2026-01-01T00:00:00", "value": 0.2}]},
            {**attributes(), "forecast": [{"time": NOW.isoformat(), "value": 0.2}] * 2},
            {**attributes(), "forecast": [None]},
            {**attributes(), "forecast": attributes()["forecast"] * 100},
        ]
        for source in bad:
            with self.subTest(source=repr(source)[:80]), self.assertRaises(ValueError):
                model.parse_source("0.3", source, NOW)

    def test_expired_current_interval_and_forecast_are_rejected(self):
        source = attributes()
        source.update({"start_time": (NOW - timedelta(hours=1)).isoformat(), "end_time": NOW.isoformat()})
        with self.assertRaises(ValueError):
            model.parse_source("0.3", source, NOW)
        with self.assertRaises(ValueError):
            model.parse_source("0.3", attributes([0.2, 0.3]), NOW + timedelta(days=1))

    def test_explicit_ends_gaps_singletons_and_timezone_offsets(self):
        source = attributes([0.2, 0.3])
        source["forecast"][0]["time"] = "2026-01-01T11:00:00+11:00"
        self.assertEqual(model.parse_source("0.3", source, NOW).points[0].start, NOW)
        source["forecast"][0]["end_time"] = (NOW + timedelta(minutes=30)).isoformat()
        with self.assertRaises(ValueError):
            model.parse_source("0.3", source, NOW)
        one = attributes([0.2])
        one["forecast"][0]["end_time"] = (NOW + timedelta(hours=1)).isoformat()
        self.assertEqual(len(model.parse_source("0.3", one, NOW).points), 1)

    def test_policy_settings_reject_nonfinite_and_inconsistent_values(self):
        for changes in (
            {"midpoint_hours": 1},
            {"minimum_retention": 2},
            {"spike_scale": 0},
            {"transition_hours": float("nan")},
            {"enabled": "true"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                model.Settings.from_options(changes)
