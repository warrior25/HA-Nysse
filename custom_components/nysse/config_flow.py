from typing import Any, Optional

from homeassistant import config_entries
from .fetch_stop_points import fetch_stop_points
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import (
    CONF_STOPS,
    CONF_STATION,
    CONF_MAX,
    DEFAULT_MAX,
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
        if user_input is not None:
            self.data[CONF_STOPS].append(
                {
                    "station": user_input[CONF_STATION],
                    "max": user_input[CONF_MAX],
                }
            )
            # If user ticked the box show this form again so they can add an
            # additional station.

            if user_input.get("add_another", True):
                return await self.async_step_user()

            if len(self.data[CONF_STOPS]) > 1:
                return self.async_create_entry(title="Many stations", data=self.data)

            return self.async_create_entry(
                title=stations[user_input[CONF_STATION]], data=self.data
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STATION): vol.In(stations),
                    vol.Optional(CONF_MAX, default=DEFAULT_MAX): cv.positive_int,
                    vol.Optional("add_another", default=False): cv.boolean,
                }
            ),
            errors=errors,
        )
