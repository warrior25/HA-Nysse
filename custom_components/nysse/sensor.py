"""Platform for sensor integration."""
from __future__ import annotations
from dateutil import parser

import logging
import json
import pytz
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from datetime import timedelta, datetime
import time
from homeassistant import config_entries, core
from homeassistant.components.sensor import SensorEntity, PLATFORM_SCHEMA
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .network import request
from .nysse_data import NysseData
from .fetch_stop_points import fetch_stop_points
from .const import (
    CONF_STOPS,
    CONF_STATION,
    CONF_MAX,
    DEFAULT_MAX,
    DEFAULT_ICON,
    PLATFORM_NAME,
    DOMAIN,
    NYSSE_JOURNEYS_URL,
    NYSSE_STOP_URL,
    WEEKDAYS,
)

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
        vol.Required(CONF_STOPS): vol.All(cv.ensure_list, [CONFIG_STOP]),
    }
)

LOCAL_TZ = pytz.timezone("Europe/Helsinki")

async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup sensors from a config entry created in the integrations UI."""
    config = hass.data[DOMAIN][config_entry.entry_id]
    stops = config[CONF_STOPS]

    sensors = []
    for stop in stops:
        if stop["station"] is not None:
            sensors.append(
                NysseSensor(
                    PLATFORM_NAME,
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
    stops = config.get(CONF_STOPS)

    sensors = []
    for stop in stops:
        if stop["station"] is not None:
            sensors.append(
                NysseSensor(
                    PLATFORM_NAME,
                    stop["station"],
                    stop["max"],
                )
            )

    async_add_entities(sensors, update_before_add=True)


class NysseSensor(SensorEntity):
    """Representation of a Sensor."""

    def __init__(self, name, station, maximum):
        """Initialize the sensor."""

        # Defaults to Nysse
        self._platformname = name
        self._unique_id = name + "_" + station
        self.station_no = station
        self.max_items = int(maximum)

        self._station_name = ""
        self._state = None
        self._destination = ""
        self._nysse_data = NysseData()
        self._departures = []
        self._stops = []
        self._journeys = {}

        self._current_weekday_int = -1

    def remove_stale_journeys(self):
        journeys_to_remove = []
        for journey in self._journeys[self._current_weekday_int]:
            if (parser.parse(journey["call"]["expectedArrivalTime"])) < (datetime.now().astimezone(LOCAL_TZ)):
                journeys_to_remove.append(journey)
        for journey in journeys_to_remove:
            self._journeys[self._current_weekday_int].remove(journey)

    async def fetch_stops(self):
        if len(self._stops) == 0:
            _LOGGER.info("Fectching stops")
            self._stops = await fetch_stop_points(False)

    def modify_journey_data(self, journeys, weekday_int):
        journeys_data = []

        if weekday_int == self._current_weekday_int:
            delta = timedelta(seconds=0)
        elif weekday_int > self._current_weekday_int:
            delta = timedelta(days=(weekday_int - self._current_weekday_int))
        else:
            delta = timedelta(days=(7 - self._current_weekday_int + weekday_int))

        for journey in journeys["body"]:

            for stop_point in journey["calls"]:

                if stop_point["stopPoint"]["shortName"] == self.station_no:

                    data_set = {}
                    data_set["lineRef"] = journey["lineUrl"].split("/")[7]
                    data_set["destinationShortName"] = journey["calls"][len(journey["calls"]) - 1]["stopPoint"]["shortName"]
                    data_set["non-realtime"] = True
                    data_set2 = {}

                    data_set2["expectedArrivalTime"] = (datetime.now().astimezone(LOCAL_TZ)+delta).strftime("%Y-%m-%d") + "T" + stop_point["arrivalTime"] + datetime.now(LOCAL_TZ).strftime("%z")[:3] + ":" + datetime.now(LOCAL_TZ).strftime("%z")[3:]

                    data_set["call"] = data_set2

                    json_dump = json.dumps(data_set)

                    journeys_data.append(json.loads(json_dump))

        return journeys_data

    async def async_update(self):
        """Fetch new state data for the sensor.
        This is the only method that should fetch new data for Home Assistant.
        """

        await self.fetch_stops()
        self._current_weekday_int = datetime.today().weekday()

        departure_url = NYSSE_STOP_URL.format(self.station_no)

        try:
            _LOGGER.info("%s: Fectching departures from %s", self.station_no, departure_url)
            departures = await request(departure_url)

            if not departures:
                _LOGGER.warning("%s: Can't fetch departures. Incorrect response from %s", self.station_no, departure_url)
                departures = []
            else:
                departures = json.loads(departures)

            total_journeys_left = 0
            if len(self._journeys) == 7:
                for i in range(7):
                    total_journeys_left += len(self._journeys[i])

            if total_journeys_left < self.max_items:
                _LOGGER.info("%s: Not enough timetable data remaining. Trying to fetch new data", self.station_no)
                self._journeys.clear()

                for weekday in WEEKDAYS:

                    journeys_index = 0
                    weekday_int = time.strptime(weekday, "%A").tm_wday

                    while True:
                        journeys_url = NYSSE_JOURNEYS_URL.format(
                            self.station_no, weekday, journeys_index
                        )

                        _LOGGER.info("%s: Fetching timetable data from %s", self.station_no, journeys_url)
                        journeys_data = await request(journeys_url)

                        if not journeys_data:
                            _LOGGER.error("%s: Can't fetch timetables. Incorrect response from %s", self.station_no, journeys_url)
                            return

                        journeys_data_json = json.loads(journeys_data)

                        modified_journey_data = self.modify_journey_data(
                            journeys_data_json, weekday_int
                        )

                        if not weekday_int in self._journeys:
                            self._journeys[weekday_int] = []

                        for journey in modified_journey_data:
                            self._journeys[weekday_int].append(journey)

                        if journeys_data_json["data"]["headers"]["paging"]["moreData"]:
                            journeys_index += 100
                        else:
                            break

        except OSError:
            _LOGGER.warning("%s: Unknown exception. Check your internet connection", self.station_no)
            return

        self._nysse_data.remove_stale_data()
        self.remove_stale_journeys()

        _LOGGER.info("%s: Data fetching complete. Populating sensor with data", self.station_no)
        self._nysse_data.populate(
            departures, self._journeys, self.station_no, self._stops, self.max_items
        )

        self._state = self._nysse_data.get_state()
        self._departures = self._nysse_data.get_departures()

    @property
    def unique_id(self):
        return self._unique_id

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        self._station_name = self._nysse_data.get_station_name()
        return "{0} ({1})".format(self._station_name, self.station_no)

    @property
    def icon(self):
        """Icon of the sensor."""
        return DEFAULT_ICON

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        attributes = {}
        attributes["last_refresh"] = self._nysse_data.get_last_update()

        if len(self._departures) != 0:
            attributes["departures"] = self._departures
            self._destination = self._departures[0]["destination"]
            attributes["station_name"] = self._station_name

        return attributes
