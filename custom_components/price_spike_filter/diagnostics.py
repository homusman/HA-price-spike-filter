"""Export policy and summary diagnostics with source identifiers redacted."""

from dataclasses import asdict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .model import Settings


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    coordinator = getattr(entry, "runtime_data", None)
    data = coordinator.data if coordinator else None
    return {
        "source_entity": "**REDACTED**",
        "settings": asdict(coordinator.settings if coordinator else Settings.from_options(entry.options)),
        "available": coordinator.last_update_success if coordinator else False,
        "forecast_intervals": len(data.raw) if data else 0,
        "changed_intervals": data.changed_intervals if data else 0,
        "largest_adjustment": data.largest_adjustment if data else None,
    }
