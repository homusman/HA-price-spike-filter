"""Set up Price Spike Filter."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_when_setup

from .coordinator import PriceFilterCoordinator
from .recorder_guard import async_install_amber_guard

PLATFORMS = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Keep large built-in Amber forecasts live without recording their arrays."""
    async_when_setup(hass, "amberelectric", async_install_amber_guard)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = PriceFilterCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_subscribe()
    entry.async_on_unload(coordinator.async_stop)
    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    return True


async def async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
