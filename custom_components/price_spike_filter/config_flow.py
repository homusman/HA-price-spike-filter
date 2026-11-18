"""Configure the source and the operator's forecast policy."""

from dataclasses import asdict

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import CONF_SOURCE, CONF_SOURCE_REGISTRY_ID, DOMAIN
from .coordinator import source_entity_id
from .model import NUMERIC_RANGES, Settings, parse_source


def source_schema(values: dict | None = None) -> vol.Schema:
    values = values or {}
    return vol.Schema(
        {
            vol.Required("name", default=values.get("name", "Price spike filter")): str,
            vol.Required(CONF_SOURCE, default=values.get(CONF_SOURCE, vol.UNDEFINED)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
        }
    )


def settings_schema(values: dict) -> vol.Schema:
    defaults = asdict(Settings())
    fields = {
        vol.Required("enabled", default=values.get("enabled", True)): selector.BooleanSelector(),
        vol.Required("spike_direction", default=values.get("spike_direction", "positive")): selector.SelectSelector(
            selector.SelectSelectorConfig(options=["positive", "negative", "both"], translation_key="spike_direction")
        ),
    }
    for name, (minimum, maximum) in NUMERIC_RANGES.items():
        fields[vol.Required(name, default=values.get(name, defaults[name]))] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=minimum,
                max=maximum,
                step="any",
                mode=selector.NumberSelectorMode.BOX,
            )
        )
    return vol.Schema(fields)


class PriceFilterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def _validate_source(self, user_input: dict) -> tuple[dict, str]:
        source = user_input[CONF_SOURCE]
        state = self.hass.states.get(source)
        if state is None or state.state in ("unknown", "unavailable"):
            raise ValueError("Source unavailable")
        if state.attributes.get("price_spike_filter") == DOMAIN:
            raise ValueError("Select an upstream price source")
        parse_source(state.state, state.attributes, dt_util.utcnow())
        entity = er.async_get(self.hass).async_get(source)
        identity = entity.id if entity else source
        data = {"name": user_input["name"], CONF_SOURCE: source}
        if entity:
            data[CONF_SOURCE_REGISTRY_ID] = entity.id
        return data, identity

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                data, identity = self._validate_source(user_input)
            except ValueError:
                errors[CONF_SOURCE] = "invalid_source"
            else:
                await self.async_set_unique_id(identity)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=data["name"], data=data)
        return self.async_show_form(step_id="user", data_schema=source_schema(user_input), errors=errors)

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            try:
                data, identity = self._validate_source(user_input)
            except ValueError:
                errors[CONF_SOURCE] = "invalid_source"
            else:
                if any(
                    other.entry_id != entry.entry_id and other.unique_id == identity
                    for other in self._async_current_entries()
                ):
                    errors[CONF_SOURCE] = "already_configured"
                else:
                    return self.async_update_reload_and_abort(entry, unique_id=identity, title=data["name"], data=data)
        values = user_input or {**entry.data, CONF_SOURCE: source_entity_id(self.hass, entry)}
        return self.async_show_form(step_id="reconfigure", data_schema=source_schema(values), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PriceFilterOptionsFlow()


class PriceFilterOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                Settings.from_options(user_input)
            except ValueError:
                errors["base"] = "invalid_settings"
            else:
                return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=settings_schema(user_input or dict(self.config_entry.options)),
            errors=errors,
        )
