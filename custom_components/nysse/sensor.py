"""Platform for sensor integration."""
from __future__ import annotations
from dateutil import parser

import logging
import json
import pytz
import voluptuous as vol
from .fetch_stop_points import fetch_stop_points
import homeassistant.helpers.config_validation as cv
from datetime import timedelta, datetime
from homeassistant import config_entries, core
from homeassistant.components.sensor import SensorEntity, PLATFORM_SCHEMA
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_STOPS,
    CONF_STATION,
    CONF_MAX,
    DEFAULT_ICON,
    DEFAULT_MAX,
    DEFAULT_NAME,
    DOMAIN,
    NYSSE_JOURNEYS_URL,
    NYSSE_STOP_URL,
)
from .network import request
from .nysse_data import NysseData


_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=1)

CONFIG_STOP = vol.Schema(
    {
        vol.Required(CONF_STATION): cv.string,
        vol.Optional(CONF_MAX, default=DEFAULT_MAX): cv.positive_int,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_STOPS): vol.All(cv.ensure_list, [CONFIG_STOP]),
    }
)

LOCAL = pytz.timezone("Europe/Helsinki")


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup sensors from a config entry created in the integrations UI."""
    config = hass.data[DOMAIN][config_entry.entry_id]
    name = config[CONF_NAME] if CONF_NAME in config else DEFAULT_NAME
    stops = config[CONF_STOPS]

    sensors = []
    for stop in stops:
        if stop["station"] is not None:
            sensors.append(
                NysseSensor(
                    name,
                    stop["station"],
                    stop["max"] if "max" in stop else DEFAULT_MAX,
                )
            )

    async_add_entities(sensors, update_before_add=True)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the sensor platform."""
    name = config.get(CONF_NAME)
    stops = config.get(CONF_STOPS)

    sensors = []
    for stop in stops:
        if stop["station"] is not None:
            sensors.append(
                NysseSensor(
                    name,
                    stop["station"],
                    stop["max"],
                )
            )

    async_add_entities(sensors, update_before_add=True)


class NysseSensor(SensorEntity):
    """Representation of a Sensor."""

    def __init__(self, name, station, maximum):
        """Initialize the sensor."""
        self._platformname = name
        self._name = name + "_" + station
        self.station_no = station
        self.max_items = int(maximum)

        self._state = None
        self._destination = ""
        self._nysse_data = NysseData()
        self._departures = []
        self._stops = []
        self._journeys = []
        self._journeys_modified = []
        self._journeys_date = datetime.now().strftime("%A")

    def modify_journey_data(self, journeys, next_day):
        journeys_data = []

        if next_day:
            delta = timedelta(days=1)
        else:
            delta = timedelta(seconds=0)

        for page in journeys:
            for journey in page["body"]:
                for stop_point in journey["calls"]:
                    if stop_point["stopPoint"]["shortName"] == self.station_no and (
                        LOCAL.localize(parser.parse(stop_point["arrivalTime"]) + delta)
                    ) > datetime.now().astimezone(LOCAL):
                        data_set = {}
                        data_set["lineRef"] = journey["lineUrl"].split("/")[7]
                        data_set["destinationShortName"] = journey["calls"][
                            len(journey["calls"]) - 1
                        ]["stopPoint"]["shortName"]
                        data_set["non-realtime"] = True
                        data_set2 = {}
                        data_set2["expectedArrivalTime"] = stop_point["arrivalTime"]
                        data_set["call"] = data_set2

                        json_dump = json.dumps(data_set)

                        journeys_data.append(json.loads(json_dump))

        return journeys_data

    @property
    def unique_id(self):
        return self._platformname + "_" + self.station_no

    @property
    def name(self) -> str:
        station = self._nysse_data.get_station_name()
        return "{0} - {1} ({2})".format(self._platformname, station, self.station_no)

    @property
    def icon(self):
        """Icon of the sensor."""
        return DEFAULT_ICON

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    async def async_update(self):
        """Fetch new state data for the sensor.
        This is the only method that should fetch new data for Home Assistant.
        """
        if len(self._stops) == 0:
            self._stops = await fetch_stop_points(False)

        journeys_index = 0

        arrival_url = NYSSE_STOP_URL.format(self.station_no)

        if self._nysse_data.is_data_stale(self.max_items):
            try:
                arrivals = await request(arrival_url)

                if not arrivals:
                    _LOGGER.warning("There was no reply from Nysse servers")
                    self._state = "Cannot reach Nysse"
                    return
                arrivals = json.loads(arrivals)

                next_day = bool(
                    parser.parse(self._journeys_date)
                    > parser.parse(datetime.now().strftime("%A"))
                )

                self._journeys_modified = self.modify_journey_data(
                    self._journeys, next_day
                )

                if len(self._journeys_modified) < self.max_items:
                    self._journeys_modified.clear()
                    self._journeys.clear()
                    _LOGGER.info("Fetching timetable data for %s", self._journeys_date)

                    while True:
                        journeys_url = NYSSE_JOURNEYS_URL.format(
                            self.station_no, self._journeys_date, journeys_index
                        )

                        journeys_data = await request(journeys_url)

                        if not journeys_data:
                            _LOGGER.warning("There was no reply from Nysse servers")
                            self._state = "Cannot reach Nysse"
                            return

                        journeys_data_json = json.loads(journeys_data)

                        self._journeys.append(journeys_data_json)

                        if journeys_data_json["data"]["headers"]["paging"]["moreData"]:
                            journeys_index += 100

                        else:
                            self._journeys_modified = self.modify_journey_data(
                                self._journeys, next_day
                            )

                            if len(self._journeys_modified) < self.max_items:
                                self._journeys_modified.clear()
                                journeys_index = 0
                                self._journeys_date = (
                                    datetime.now() + timedelta(days=1)
                                ).strftime("%A")
                            else:
                                break

            except OSError:
                _LOGGER.warning("Something broke")
                self._state = "Cannot reach Nysse"
                return

            self._nysse_data.populate(
                arrivals, self._journeys_modified, self.station_no, self._stops
            )

        self._nysse_data.sort_data(self.max_items)
        self._state = self._nysse_data.get_state()
        self._departures = self._nysse_data.get_departures()

    @property
    def extra_state_attributes(self):
        attributes = {}
        attributes["last_refresh"] = self._nysse_data.get_last_update()

        if self._nysse_data.is_empty():
            return attributes

        attributes["departures"] = self._departures
        self._destination = self._departures[0]["destination"]
        attributes["station_name"] = self._nysse_data.get_station_name()

        return attributes
