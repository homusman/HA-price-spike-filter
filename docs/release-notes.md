# Price Spike Filter v0.1.0

An independent Home Assistant helper for filtering future tariff spikes before the forecast reaches HAEO or another optimiser.

- Select an Amber Express price sensor or another sensor publishing HAEO time/value forecasts.
- Compare filtered prices with separate raw and robust median-baseline forecast sensors.
- Configure the preserved near-term window, time weighting, spike magnitude suppression and source age limit.
- Update on source changes and once per minute as lead times decrease.
- Manage sources through Reconfigure and filtering policy through Configure.

Defaults preserve the next hour, use a 12-hour time midpoint and a six-hour median window, and apply up to 90% extra suppression to large positive deviations. These are operator policy settings rather than calibrated spike probabilities.

Add `https://github.com/homusman/HA-price-spike-filter` to HACS as a custom Integration repository, install Price Spike Filter, restart Core and add the integration. Then inspect its forecasts before choosing its Filtered price sensor as a HAEO Grid tariff input.
