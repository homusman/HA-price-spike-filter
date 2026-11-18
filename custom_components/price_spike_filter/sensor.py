"""Publish normalised raw, filtered and baseline price forecasts."""

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PriceFilterCoordinator, source_entity_id


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([PriceSensor(entry.runtime_data, entry, kind) for kind in ("filtered", "raw", "baseline")])


class PriceSensor(CoordinatorEntity[PriceFilterCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:chart-bell-curve"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = frozenset({"forecast"})

    def __init__(self, coordinator: PriceFilterCoordinator, entry: ConfigEntry, kind: str) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.kind = kind
        self._attr_unique_id = f"{entry.entry_id}_{kind}"
        self._attr_translation_key = kind
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Homusman",
            model="Price Spike Filter",
        )
        if kind != "filtered":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return None
        data = self.coordinator.data
        return data.baseline[0].value if self.kind == "baseline" else data.current_price

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return {}
        data = self.coordinator.data
        points = getattr(data, self.kind)
        return {
            "forecast": [{"time": point.start.isoformat(), "value": point.value} for point in points],
            "forecast_end": points[-1].end.isoformat(),
            "interpolation_mode": "previous",
            "price_spike_filter": DOMAIN,
            "source_entity": source_entity_id(self.hass, self.entry),
            "filter_enabled": self.coordinator.settings.enabled,
            "changed_intervals": data.changed_intervals,
            "largest_adjustment": data.largest_adjustment,
        }
