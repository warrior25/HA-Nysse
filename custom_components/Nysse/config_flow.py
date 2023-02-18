from typing import Any, Optional
from homeassistant import config_entries
from .fetch_stop_points import fetch_stop_points
from homeassistant.helpers.selector import selector
import voluptuous as vol

from .const import (
    CONF_STOPS,
    CONF_STATION,
    CONF_MAX,
    DEFAULT_MAX,
    CONF_TIMELIMIT,
    DEFAULT_TIMELIMIT,
    CONF_LINES,
    DEFAULT_LINES,
    DOMAIN,
)


@config_entries.HANDLERS.register(DOMAIN)
class NysseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Nysse config flow."""

    def __init__(self) -> None:
        """Initialize."""
        self.data: dict[str, Any] = {CONF_STOPS: []}

    async def async_step_user(self, user_input: Optional[dict[str, Any]] = None):
        errors: dict[str, str] = {}

        stations = await fetch_stop_points(True)
        if not stations:
            return

        data_schema = {
            vol.Required(CONF_STATION): selector(
                {
                    "select": {
                        "options": stations,
                        "mode": "dropdown",
                        "custom_value": "true",
                    }
                }
            ),
            vol.Optional(CONF_LINES, default=DEFAULT_LINES): str,
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
                await self.validate_stop(user_input[CONF_STATION], stations)
            except ValueError:
                errors[CONF_STATION] = "invalid_station"

            if not errors:
                self.data[CONF_STOPS].append(
                    {
                        "station": user_input[CONF_STATION],
                        "max": user_input[CONF_MAX],
                        "timelimit": user_input[CONF_TIMELIMIT],
                        "lines": user_input[CONF_LINES],
                    }
                )
                integration_title = "Nysse"

                for station in stations:
                    if station["value"] == user_input[CONF_STATION]:
                        integration_title = station["label"]
                        break

                return self.async_create_entry(title=integration_title, data=self.data)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(data_schema),
            errors=errors,
        )

    async def validate_stop(self, stop_id, stations):
        for station in stations:
            if station["value"] == stop_id:
                return
        raise ValueError
