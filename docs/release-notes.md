# Price Spike Filter v0.1.4 — Amber forecast Recorder patch

Automatically excludes the built-in Amber Electric forecast sensors' large
`forecasts` attribute from Recorder, preventing the 16 KiB oversized-attributes
warning without changing Recorder YAML or excluding the whole sensor.

- Full live forecasts remain available to HAEO and dashboards.
- Numeric price history and small metadata remain recordable.
- Covers existing/new Amber forecast entities, including renamed ones.
- Does not suppress warnings, delete history, edit Core files or change filtering.

The narrow runtime compatibility patch uses Home Assistant entity recording
metadata. Update Price Spike Filter in HACS and restart; no configuration changes
are needed. A future Core update may require compatibility maintenance.

Regression tests exercise Recorder's real attribute serializer with an oversized
forecast and verify that live data and unrelated entities remain untouched.
