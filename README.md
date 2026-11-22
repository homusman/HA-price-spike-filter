# Price Spike Filter

A Home Assistant integration that filters future electricity prices before they reach an optimiser such as HAEO.

It reads an existing price sensor, including Amber Express in advanced-price-predicted mode, and publishes **Filtered price**, **Raw price** and **Baseline price** sensors. All three expose a HAEO-compatible `forecast` attribute. The current observation passes through within its stated interval.

## Install with HACS

1. In HACS, open **Custom repositories** and add `https://github.com/homusman/HA-price-spike-filter` as an **Integration**.
2. Download **Price Spike Filter** and restart Home Assistant Core.
3. Open **Settings → Devices & services → Add integration → Price Spike Filter**.
4. Select the upstream price sensor and give the filter a name, such as **Import** or **Feed-in**.
5. Use **Configure** on the integration entry to adjust the policy.

Create one entry for each tariff channel you want to filter. The source sensor must already provide the price model you want to use. For Amber Express, select its price sensor configured to use advanced-price-predicted.

### Upgrading from the helper version

Update through HACS and restart Home Assistant Core. Existing filters move from
the Helpers tab to **Settings → Devices & services → Integrations → Price Spike Filter**.
Their settings, source mappings, devices and sensor entity IDs are preserved;
do not delete or recreate them. HAEO references to existing filtered sensors continue to work.

Use **Configure** on the relevant entry to edit filtering parameters. Use its
**⋮ → Reconfigure** to change the source or filter name, or **⋮ → Delete** to
remove that filter. Separate import and feed-in filters appear under the same
Price Spike Filter integration.

For manual installation, extract the release ZIP into `config/custom_components/price_spike_filter/`, then restart Core. The folder should contain `manifest.json` directly.

Home Assistant **2026.1.1 or later** is required. Releases include `price_spike_filter.zip` and its SHA-256 checksum.

## Connect to HAEO

First inspect the filtered sensor's `forecast` attribute alongside the raw sensor. Then choose **Filtered price** as the corresponding Grid tariff input in HAEO. The sensor state is the current price. Future prices are in its `forecast` attribute.

Filtering occurs upstream of the optimiser, so it changes the prices the optimiser uses to plan storage and EV charging. If you already apply tariff discounts inside the Homusman acceptance gate, account for that additional attenuation when choosing your settings.

Output preserves the source's price sign. A positive feed-in price from Amber Express stays a positive feed-in price. The filter normalises supported cent units to `$/kWh`. It performs no exchange-rate conversion.

## Initial settings

These defaults are an operating policy for uncertain forecasts. They have not been calibrated as spike probabilities.

| Setting | Default | Effect |
| --- | --- | --- |
| Enable filtering | On | Turn off for a normalised raw forecast |
| Preserve near-term prices | 1 hour | Keep intervals starting within this lead time unchanged |
| Time weighting midpoint | 12 hours | Retain approximately half the deviation at this lead time, before extra spike suppression |
| Transition width | 2 hours | Smooth the time curve and the onset of extra suppression |
| Minimum retained deviation | 0 | Approach the baseline far ahead |
| Median baseline window | 6 hours | Use a centred, duration-weighted median |
| Spike scale | $0.10/kWh | Set the deviation scale for additional suppression |
| Maximum extra spike suppression | 0.9 | Remove up to 90% of a large distant deviation after time weighting |
| Extra suppression direction | Positive | Apply the extra reduction to prices above the baseline |
| Maximum source age | 30 minutes | Make output unavailable if the source stops reporting |

The time midpoint must be later than the preserved window. A minimum retention of 1 disables time attenuation, while a maximum spike suppression of 0 disables extra spike attenuation. Time weighting affects both positive and negative deviations. The direction setting controls only the extra spike attenuation.

## How it works

For every source interval, the baseline is the duration-weighted median of prices in a centred window. Unequal forecast resolutions receive weights based on the time they cover. A one-hour $10/kWh outlier among otherwise ordinary prices cannot pull this median upward merely through its magnitude.

Beyond the preserved window, a normalised logistic curve shrinks the deviation from that baseline. A second factor reduces large deviations according to their magnitude and lead time.

```text
filtered = baseline + (raw − baseline) × time_retention × spike_retention
```

Time retention starts at 1 at the preserved-window boundary and approaches the configured minimum. Extra spike suppression ramps from zero beyond that boundary. At one spike scale, the magnitude curve reaches about 63% of its maximum. Neither curve is an absolute price cap.

As an interval approaches, filtering gradually releases. The preserved window and the source's current interval use original prices. With the defaults, a $10/kWh outlier 24 hours away in an otherwise $0.20/kWh forecast becomes approximately $0.20/kWh. The same interval is restored to its raw price when it enters the preserved window.

A long high-price plateau occupying most of the median window can still raise the baseline. Adjust the window and policy with that limitation in mind. Reducing a forecast spike can also reduce preparation for a spike that ultimately happens.

## Source format and availability

Supported source units are `$/kWh`, `AUD/kWh`, `c/kWh` and `¢/kWh`. The sensor needs a numeric current-price state and a nonempty `forecast` list of at most 2,048 timezone-aware records.

```yaml
unit_of_measurement: $/kWh
forecast:
  - time: "2026-11-18T15:00:00+11:00"
    value: 0.30
  - time: "2026-11-18T15:30:00+11:00"
    value: 0.24
```

Each price holds until the next timestamp. The final interval uses its explicit `end_time`, the source's `forecast_end`, or the duration of the preceding interval. A single forecast record needs an explicit end. The source may provide `start_time` and `end_time` for the current price, as Amber Express does. That current reading is inserted into the appropriate interval.

At interval rollover, Amber may publish its next observation slightly early or late. If the
source is still fresh and its forecast covers the current time, the filter uses
that interval's forecast price and reports `current_price_estimated: true`. The
expired observation is not extended into the new interval, and an early observation
is not applied before its interval starts. A valid new observation
automatically restores `current_price_estimated: false`. If an early update has
already removed the previous interval, a previously validated forecast may bridge
the gap only while it covers now and its original source report is still fresh.

Unavailable or stale source readings, missing current-time forecast coverage,
nonfinite prices, malformed timestamps, duplicate timestamps and explicit gaps or
overlaps make the output unavailable. Missing data is not silently replaced by zero.

Source changes trigger updates. A one-minute timer also recalculates lead-time weighting and checks availability. Sensor renames are resolved through the Home Assistant entity registry. To select a different source, use **Reconfigure**.

## Diagnostics and storage

Filtered sensor attributes include the number of changed intervals, the largest price adjustment and the forecast end. Raw and baseline sensors allow direct comparison. Home Assistant's downloadable integration diagnostics include the settings and summary values with source identifiers redacted.

The large forecast attributes are excluded from Recorder. The integration keeps its current computation in memory and persists its configuration through Home Assistant. It reads local state and registers sensor entities. It has no credentials, outbound API client or actuator services.

## Recovery and rollback

If output becomes unavailable, check the upstream sensor's availability, units, forecast timestamps and last report time. A stale or malformed source recovers automatically when valid data arrives.

To bypass filtering, disable it in **Configure**, or select the original upstream tariff sensor in HAEO. To roll back an integration version, choose an earlier release in HACS and restart Core.

## Development

The parser and filtering model use the Python standard library. Run the numerical tests with:

```shell
python -m unittest discover -s tests -p test_model.py -v
```

The complete suite runs against Home Assistant 2026.1.1 under Python 3.13:

```shell
python -m pip install homeassistant==2026.1.1 ruff==0.14.10
ruff check .
ruff format --check .
python -m unittest discover -s tests -v
```

GitHub Actions runs the tests, lint checks, Home Assistant manifest validation and HACS validation before publishing a release from the default branch.


## Built-in Amber forecast Recorder compatibility

From v0.1.4, this integration automatically adds a narrowly scoped runtime patch
for the built-in Amber Electric integration's forecast sensors. Only their large
`forecasts` attribute is excluded from Recorder. Numeric price history and smaller
metadata continue to be recorded; full live attributes remain available to HAEO,
dashboards and filtering. Existing Recorder configuration is untouched.

The patch covers existing Amber forecast entities and applies the exclusion
before new ones first publish. It follows the entity class rather than hardcoded
entity IDs, so renamed forecast sensors are covered. Other Amber entities and
other integrations are unchanged. Recorder logging is not suppressed, and no
Home Assistant Core files are edited.

This is a compatibility shim around Home Assistant entity metadata, not a native
Amber configuration option. It is installed when Price Spike Filter loads and
Amber Electric is set up. Update in HACS and restart; no new entry, source mapping
or YAML changes are needed. Removing or rolling back Price Spike Filter and
restarting removes this compatibility patch. Previously logged warnings remain
in the log; stored history is not purged.
