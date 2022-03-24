import logging
from typing import Any, Optional

from homeassistant import config_entries
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import CONF_STOPS, CONF_STATION, CONF_MAX, DEFAULT_MAX, DOMAIN, STOPS

_LOGGER = logging.getLogger(__name__)


@config_entries.HANDLERS.register(DOMAIN)
class NysseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Nysse config flow."""

    def __init__(self) -> None:
        """Initialize."""
        self.data: dict[str, Any] = {CONF_STOPS: []}

    async def async_step_user(self, user_input: Optional[dict[str, Any]] = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self.data[CONF_STOPS].append(
                {
                    "station": user_input[CONF_STATION],
                    "max": user_input[CONF_MAX],
                }
            )
            # If user ticked the box show this form again so they can add an
            # additional station.
            if user_input.get("add_another", False):
                return await self.async_step_user()

            return self.async_create_entry(
                title=user_input[CONF_STATION], data=self.data
            )

        stations = dict(sorted(STOPS.items(), key=lambda item: item[1]))
        for k in stations.keys():
            stations[k] += " (" + k + ")"

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
