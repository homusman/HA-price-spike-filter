# Price Spike Filter v0.1.3 — interval rollover continuity

Fixes recurring half-hour unavailability while Amber updates its current price.
An expired or slightly early current observation no longer invalidates a still-fresh forecast that
covers the new interval. The active forecast value is used with
`current_price_estimated: true`; arrival of the new observation clears that flag.
Observed prices are only applied within their stated intervals.

Source-age limits, source unavailability, missing coverage and malformed-forecast
checks remain active. No dispatcher fallback or HAEO plan validation is disabled.

Update in HACS and restart Home Assistant. Existing filter settings and entity IDs
are preserved. This addresses the logged price-filter/HAEO/dispatcher failure chain;
independent Load forecast outages still need their own diagnosis.

When an early Amber update removes the previous interval entirely, the filter
can use its previously validated forecast only while it covers the present and
its original source report remains within the source-age limit. There is no
zero-fill or extrapolation of an expired observation.
