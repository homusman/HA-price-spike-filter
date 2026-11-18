"""React to source changes and recalculate as forecast lead times decrease."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_SOURCE, CONF_SOURCE_REGISTRY_ID
from .model import Result, Settings, filter_forecast, parse_source

_LOGGER = logging.getLogger(__name__)


def source_entity_id(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Resolve an entity registry ID so sensor renames keep working."""
    registry_id = entry.data.get(CONF_SOURCE_REGISTRY_ID)
    if registry_id and (entity := er.async_get(hass).async_get(registry_id)):
        return entity.entity_id
    return entry.data[CONF_SOURCE]


class PriceFilterCoordinator(DataUpdateCoordinator[Result]):
    """Manage a local, read-only price transformation."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=timedelta(minutes=1),
            always_update=False,
        )
        self.entry = entry
        self.settings = Settings.from_options(entry.options)
        self._source = None
        self._unsubscribe = None

    @callback
    def async_subscribe(self) -> None:
        """Follow the configured source, including a renamed entity."""
        source = source_entity_id(self.hass, self.entry)
        if source == self._source:
            return
        self.async_stop()
        self._source = source
        self._unsubscribe = async_track_state_change_event(self.hass, [source], self._source_changed)

    async def _source_changed(self, _event) -> None:
        await self.async_request_refresh()

    @callback
    def async_stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self._source = None

    async def _async_update_data(self) -> Result:
        source = source_entity_id(self.hass, self.entry)
        state = self.hass.states.get(source)
        if state is None or state.state in ("unknown", "unavailable"):
            raise UpdateFailed("Source price sensor is unavailable")
        now = dt_util.utcnow()
        age = (now - state.last_reported).total_seconds()
        if age < -60 or age > self.settings.max_source_age_minutes * 60:
            raise UpdateFailed("Source price sensor is stale")
        try:
            snapshot = parse_source(state.state, state.attributes, now)
            result = await self.hass.async_add_executor_job(filter_forecast, snapshot, now, self.settings)
        except ValueError as error:
            raise UpdateFailed(str(error)) from error
        if self._unsubscribe is not None:
            self.async_subscribe()
        return result
