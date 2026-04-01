from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import selector

from .const import (
    CONF_LINES,
    CONF_STATION,
    DOMAIN,
    MAX,
    REALTIME,
    TIMELIMIT,
    UPDATE_INTERVAL,
)
from .fetch_api import get_route_ids, get_stops


def format_stops(stops):
    """Format stop selector options and mappings.

    Return tuple values:
    - selector options for UI
    - mapping from displayed value to stop_id
    - mapping from stop_id to displayed value
    """
    options = []
    display_to_stop_id = {}
    stop_id_to_display = {}

    for stop in stops:
        display_value = f"{stop['stop_name']} ({stop['stop_id']})"
        options.append({"label": display_value, "value": display_value})
        display_to_stop_id[display_value] = stop["stop_id"]
        stop_id_to_display[stop["stop_id"]] = display_value

    options.sort(key=lambda option: option["label"])

    return options, display_to_stop_id, stop_id_to_display


@config_entries.HANDLERS.register(DOMAIN)
class NysseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Nysse config flow."""

    def __init__(self) -> None:
        """Initialize."""
        self.data: dict[str, Any] = {}
        self.stations = []
        self.station_display_to_stop_id: dict[str, str] = {}
        self.station_stop_id_to_display: dict[str, str] = {}
        self.title = "Nysse"

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors = {}

        stops = await get_stops()
        # TODO: check error handling
        if len(stops) == 0:
            errors["base"] = "no_stop_points"
        (
            self.stations,
            self.station_display_to_stop_id,
            self.station_stop_id_to_display,
        ) = format_stops(stops)

        data_schema = {
            vol.Required(CONF_STATION): selector(
                {
                    "select": {
                        "options": self.stations,
                        "mode": "dropdown",
                        "custom_value": True,
                    }
                }
            )
        }

        if user_input is not None:
            try:
                stop_id = await self.validate_stop(user_input[CONF_STATION])
            except ValueError:
                errors[CONF_STATION] = "invalid_station"

            if not errors:
                await self.async_set_unique_id(stop_id)
                self._abort_if_unique_id_configured()
                self.data[CONF_STATION] = stop_id
                self.title = self.station_stop_id_to_display.get(stop_id, stop_id)

                return await self.async_step_options()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(data_schema),
            errors=errors,
        )

    async def async_step_options(self, user_input: dict[str, Any] | None = None):
        errors = {}

        lines = await get_route_ids(self.data[CONF_STATION])
        if len(lines) == 0:
            errors["base"] = "no_lines"

        options_schema = {
            vol.Required(CONF_LINES, default=lines): cv.multi_select(lines),
            vol.Optional(TIMELIMIT.name, default=TIMELIMIT.default): selector(
                {
                    "number": {
                        "min": 0,
                        "max": 60,
                        "unit_of_measurement": "min",
                    }
                }
            ),
            vol.Optional(MAX.name, default=MAX.default): selector(
                {"number": {"min": 1, "max": 30}}
            ),
            vol.Optional("advanced_options"): section(
                vol.Schema(
                    {
                        vol.Optional(REALTIME.name, default=REALTIME.default): bool,
                        vol.Optional(
                            UPDATE_INTERVAL.name, default=UPDATE_INTERVAL.default
                        ): selector(
                            {
                                "number": {
                                    "min": UPDATE_INTERVAL.min,
                                    "max": UPDATE_INTERVAL.max,
                                    "unit_of_measurement": "s",
                                }
                            }
                        ),
                    }
                ),
                {"collapsed": True},
            ),
        }
        if user_input is not None:
            try:
                await self.validate_lines(user_input[CONF_LINES])
            except ValueError:
                errors[CONF_LINES] = "invalid_lines"
            if not errors:
                advanced_options = user_input.get("advanced_options", {})
                self.data = {
                    "station": self.data[CONF_STATION],
                    "lines": user_input[CONF_LINES],
                    "timelimit": user_input[TIMELIMIT.name],
                    "max": user_input[MAX.name],
                    "realtime": advanced_options.get(REALTIME.name, REALTIME.default),
                    "scan_interval": advanced_options.get(
                        UPDATE_INTERVAL.name, UPDATE_INTERVAL.default
                    ),
                }
                return self.async_create_entry(title=self.title, data=self.data)

        return self.async_show_form(
            step_id="options",
            data_schema=vol.Schema(options_schema),
            errors=errors,
        )

    async def validate_stop(self, stop_id):
        if stop_id in self.station_display_to_stop_id:
            return self.station_display_to_stop_id[stop_id]

        # Accept plain stop_id values for backwards compatibility.
        if stop_id in self.station_stop_id_to_display:
            return stop_id

        raise ValueError

    async def validate_lines(self, lines):
        if len(lines) < 1:
            raise ValueError

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handles options flow for the component."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self.data: dict[str, Any] = {}
        self.title = ""
        self.stations = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}

        if user_input is not None:
            stops = await get_stops()
            # TODO: check error handling
            if len(stops) == 0:
                errors["base"] = "no_stop_points"
            self.stations, _, stop_id_to_display = format_stops(stops)
            self.title = stop_id_to_display.get(
                self._config_entry.data[CONF_STATION],
                self._config_entry.data[CONF_STATION],
            )

            self.data = {
                "station": self._config_entry.data[CONF_STATION],
                "lines": self._config_entry.data[CONF_LINES],
                "timelimit": user_input[TIMELIMIT.name],
                "max": user_input[MAX.name],
                "realtime": user_input.get("advanced_options", {}).get(
                    REALTIME.name,
                    self._config_entry.options.get(
                        REALTIME.name,
                        self._config_entry.data.get(REALTIME.name, REALTIME.default),
                    ),
                ),
                "scan_interval": user_input.get("advanced_options", {}).get(
                    UPDATE_INTERVAL.name,
                    self._config_entry.options.get(
                        UPDATE_INTERVAL.name,
                        self._config_entry.data.get(
                            UPDATE_INTERVAL.name, UPDATE_INTERVAL.default
                        ),
                    ),
                ),
            }
            return self.async_create_entry(title="", data=self.data)

        current_timelimit = self._config_entry.options.get(
            TIMELIMIT.name, self._config_entry.data[TIMELIMIT.name]
        )
        current_max = self._config_entry.options.get(
            MAX.name, self._config_entry.data[MAX.name]
        )
        current_realtime = self._config_entry.options.get(
            REALTIME.name, self._config_entry.data.get(REALTIME.name, REALTIME.default)
        )
        current_scan_interval = self._config_entry.options.get(
            UPDATE_INTERVAL.name,
            self._config_entry.data.get(UPDATE_INTERVAL.name, UPDATE_INTERVAL.default),
        )

        options_schema = vol.Schema(
            {
                vol.Optional(
                    TIMELIMIT.name,
                    default=current_timelimit,
                ): selector(
                    {
                        "number": {
                            "min": 0,
                            "max": 60,
                            "unit_of_measurement": "min",
                        }
                    }
                ),
                vol.Optional(
                    MAX.name,
                    default=current_max,
                ): selector({"number": {"min": 1, "max": 30}}),
                vol.Optional("advanced_options"): section(
                    vol.Schema(
                        {
                            vol.Optional(REALTIME.name, default=current_realtime): bool,
                            vol.Optional(
                                UPDATE_INTERVAL.name,
                                default=current_scan_interval,
                            ): selector(
                                {
                                    "number": {
                                        "min": 30,
                                        "max": 300,
                                        "unit_of_measurement": "s",
                                    }
                                }
                            ),
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
        )
