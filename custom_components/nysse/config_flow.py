from typing import Any, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import selector

from .const import (
    CONF_LINES,
    CONF_MAX,
    CONF_STATION,
    CONF_TIMELIMIT,
    DEFAULT_MAX,
    DEFAULT_TIMELIMIT,
    DOMAIN,
)
from .fetch_api import fetch_lines, fetch_stop_points


@config_entries.HANDLERS.register(DOMAIN)
class NysseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Nysse config flow."""

    def __init__(self) -> None:
        """Initialize."""
        self.data: dict[str, Any] = {}
        self.stations = []
        self.title = "Nysse"

    async def async_step_user(self, user_input: Optional[dict[str, Any]] = None):
        errors = {}

        self.stations = await fetch_stop_points(True)
        if len(self.stations) == 0:
            errors["base"] = "no_stop_points"

        data_schema = {
            vol.Required(CONF_STATION): selector(
                {
                    "select": {
                        "options": self.stations,
                        "mode": "dropdown",
                        "custom_value": "true",
                    }
                }
            )
        }

        if user_input is not None:
            try:
                await self.validate_stop(user_input[CONF_STATION])
            except ValueError:
                errors[CONF_STATION] = "invalid_station"

            if not errors:
                await self.async_set_unique_id(user_input[CONF_STATION])
                self._abort_if_unique_id_configured()
                self.data[CONF_STATION] = user_input[CONF_STATION]

                for station in self.stations:
                    if station["value"] == user_input[CONF_STATION]:
                        self.title = station["label"]
                        break

                return await self.async_step_options()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(data_schema),
            errors=errors,
        )

    async def async_step_options(self, user_input: Optional[dict[str, Any]] = None):
        errors = {}

        lines = await fetch_lines(self.data[CONF_STATION])
        if len(lines) == 0:
            errors["base"] = "no_lines"

        options_schema = {
            vol.Required(CONF_LINES, default=lines): cv.multi_select(lines),
            vol.Optional(CONF_TIMELIMIT, default=DEFAULT_TIMELIMIT): selector(
                {
                    "number": {
                        "min": 0,
                        "max": 60,
                        "unit_of_measurement": "min",
                    }
                }
            ),
            vol.Optional(CONF_MAX, default=DEFAULT_MAX): selector(
                {"number": {"min": 1, "max": 30}}
            ),
        }
        if user_input is not None:
            try:
                await self.validate_lines(user_input[CONF_LINES])
            except ValueError:
                errors[CONF_LINES] = "invalid_lines"
            if not errors:
                self.data = {
                    "station": self.data[CONF_STATION],
                    "lines": user_input[CONF_LINES],
                    "timelimit": user_input[CONF_TIMELIMIT],
                    "max": user_input[CONF_MAX],
                }
                return self.async_create_entry(title=self.title, data=self.data)

        return self.async_show_form(
            step_id="options",
            data_schema=vol.Schema(options_schema),
            errors=errors,
        )

    async def validate_stop(self, stop_id):
        for station in self.stations:
            if station["value"] == stop_id:
                return
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
        self.config_entry = config_entry
        self.data: dict[str, Any] = {}
        self.title = ""
        self.stations = []

    async def async_step_init(
        self, user_input: dict[str, Any] = None
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}

        if user_input is not None:
            self.stations = await fetch_stop_points(True)
            if len(self.stations) == 0:
                errors["base"] = "no_stop_points"

            for station in self.stations:
                if station["value"] == self.config_entry.data[CONF_STATION]:
                    self.title = station["label"]
                    break

            self.data = {
                "station": self.config_entry.data[CONF_STATION],
                "lines": self.config_entry.data[CONF_LINES],
                "timelimit": user_input[CONF_TIMELIMIT],
                "max": user_input[CONF_MAX],
            }
            return self.async_create_entry(title="", data=self.data)

        if self.config_entry.options:
            options_schema = vol.Schema(
                {
                    vol.Optional(
                        CONF_TIMELIMIT,
                        default=self.config_entry.options[CONF_TIMELIMIT],
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
                        CONF_MAX, default=self.config_entry.options[CONF_MAX]
                    ): selector({"number": {"min": 1, "max": 30}}),
                }
            )
        else:
            options_schema = vol.Schema(
                {
                    vol.Optional(
                        CONF_TIMELIMIT,
                        default=self.config_entry.data[CONF_TIMELIMIT],
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
                        CONF_MAX, default=self.config_entry.data[CONF_MAX]
                    ): selector({"number": {"min": 1, "max": 30}}),
                }
            )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
        )
