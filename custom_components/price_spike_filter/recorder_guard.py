"""Narrow Recorder compatibility patch for built-in Amber forecast sensors."""

import logging
from functools import wraps

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import async_get_platforms
from homeassistant.loader import async_get_integration

_LOGGER = logging.getLogger(__name__)
_ATTRIBUTE = "forecasts"


def protect_forecast_entity(entity) -> bool:
    """Exclude only the bulky forecast attribute, without changing live data."""
    info = getattr(entity, "_state_info", None)
    if not isinstance(info, dict):
        return False
    excluded = info.get("unrecorded_attributes", frozenset())
    if not isinstance(excluded, (set, frozenset)):
        return False
    if _ATTRIBUTE in excluded:
        return False
    info["unrecorded_attributes"] = frozenset(excluded) | {_ATTRIBUTE}
    return True


def protect_forecast_class(entity_type) -> None:
    """Apply metadata before newly added Amber forecast entities first publish."""
    original = entity_type.async_added_to_hass
    if getattr(original, "_price_filter_recorder_guard", False):
        return

    @wraps(original)
    async def guarded_added(entity):
        protect_forecast_entity(entity)
        await original(entity)

    guarded_added._price_filter_recorder_guard = True
    entity_type.async_added_to_hass = guarded_added


async def async_install_amber_guard(hass: HomeAssistant, _component: str) -> None:
    """Patch Amber only after its dependencies load; cover existing entities too."""
    try:
        integration = await async_get_integration(hass, "amberelectric")
        platform = await integration.async_get_platform("sensor")
        entity_type = platform.AmberForecastSensor
    except (ImportError, AttributeError):
        _LOGGER.warning("Amber forecast Recorder compatibility patch unavailable for this Home Assistant version")
        return
    protect_forecast_class(entity_type)
    for entity_platform in async_get_platforms(hass, "amberelectric"):
        for entity in entity_platform.entities.values():
            if isinstance(entity, entity_type) and protect_forecast_entity(entity):
                entity.async_write_ha_state()
