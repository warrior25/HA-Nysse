"""Platform for sensor integration."""
from __future__ import annotations
import logging
import json
from datetime import timedelta, datetime
import pytz
from dateutil import parser
from homeassistant import config_entries, core
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .network import get
from .nysse_data import NysseData
from .fetch_api import fetch_stop_points
from .const import (
    DEFAULT_MAX,
    DEFAULT_ICON,
    DEFAULT_TIMELIMIT,
    PLATFORM_NAME,
    NYSSE_JOURNEYS_URL,
    NYSSE_STOP_URL,
    WEEKDAYS,
    AIMED_ARRIVAL_TIME,
    AIMED_DEPARTURE_TIME,
    EXPECTED_ARRIVAL_TIME,
    EXPECTED_DEPARTURE_TIME,
    DEPARTURE,
    JOURNEY,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)
PAGE_SIZE = 100


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup sensors from a config entry created in the integrations UI."""

    sensors = []
    if "station" in config_entry.options:
        sensors.append(
            NysseSensor(
                PLATFORM_NAME,
                config_entry.options["station"],
                config_entry.options["max"]
                if "max" in config_entry.options
                else DEFAULT_MAX,
                config_entry.options["timelimit"]
                if "timelimit" in config_entry.options
                else DEFAULT_TIMELIMIT,
                config_entry.options["lines"],
                hass.config.time_zone,
            )
        )
    else:
        sensors.append(
            NysseSensor(
                PLATFORM_NAME,
                config_entry.data["station"],
                config_entry.data["max"] if "max" in config_entry.data else DEFAULT_MAX,
                config_entry.data["timelimit"]
                if "timelimit" in config_entry.data
                else DEFAULT_TIMELIMIT,
                config_entry.data["lines"],
                hass.config.time_zone,
            )
        )

    async_add_entities(sensors, update_before_add=True)


class NysseSensor(SensorEntity):
    """Representation of a Sensor."""

    def __init__(self, name, station, maximum, timelimit, lines, time_zone) -> None:
        """Initialize the sensor."""

        # Defaults to Nysse
        self._platformname = name
        self._unique_id = name + "_" + station
        self.station_no = station
        self.max_items = int(maximum)
        self.timelimit = int(timelimit)
        self.lines = lines

        self._station_name = ""
        self._state = None
        self._nysse_data = NysseData()
        self._departures = []
        self._stops = []
        self._journeys = []
        self._live_data = []

        self._current_weekday_int = -1
        self._last_update_time = None
        self._time_zone = pytz.timezone(time_zone)

    async def fetch_stops(self):
        if len(self._stops) == 0:
            _LOGGER.debug("Fetching stops")
            self._stops = await fetch_stop_points(False)
            if len(self._stops) == 0:
                _LOGGER.error("Failed to fetch stops")

    def remove_stale_data(self, departures, journeys):
        removed_journey_count = 0
        removed_departures_count = 0

        # Remove stale journeys based on departure time and stop code
        for journey in journeys[:]:
            if journey["departureTime"] < self._last_update_time + timedelta(
                minutes=self.timelimit
            ) or (journey["stopCode"] != self.station_no):
                journeys.remove(journey)
                removed_journey_count += 1

        # Remove stale departures based on time and line
        for departure in departures[:]:
            if departure["line"] in self.lines:
                matching_journeys = [
                    journey
                    for journey in journeys
                    if journey["departureTime"] == departure["aimedArrivalTime"]
                ]
                for journey in matching_journeys:
                    journeys.remove(journey)
                    removed_journey_count += 1

            if (
                departure["departureTime"]
                < self._last_update_time + timedelta(minutes=self.timelimit)
                or departure["line"] not in self.lines
            ):
                departures.remove(departure)
                removed_departures_count += 1

        if removed_journey_count > 0:
            _LOGGER.debug(
                "%s: Removed %s stale or unwanted journeys",
                self.station_no,
                removed_journey_count,
            )

        if removed_departures_count > 0:
            _LOGGER.debug(
                "%s: Removed %s stale or unwanted departures",
                self.station_no,
                removed_departures_count,
            )

        return departures, journeys

    async def fetch_departures(self):
        url = NYSSE_STOP_URL.format(self.station_no)
        _LOGGER.debug(
            "%s: Fectching departures from %s",
            self.station_no,
            url + "&indent=yes",
        )
        data = await get(url)
        if not data:
            _LOGGER.warning(
                "%s: Can't fetch departures. Incorrect response from %s",
                self.station_no,
                url,
            )
        unformatted_departures = json.loads(data)
        return self.format_departures(unformatted_departures)

    async def fetch_journeys(self):
        journeys = []

        async def fetch_data_for_weekday(weekday_index):
            journeys_index = 0
            weekday_string = WEEKDAYS[weekday_index]
            while True:
                url = NYSSE_JOURNEYS_URL.format(
                    self.station_no, weekday_string, journeys_index
                )
                _LOGGER.debug(
                    "%s: Fetching timetable data from %s",
                    self.station_no,
                    url + "&indent=yes",
                )
                data = await get(url)
                if not data:
                    _LOGGER.error(
                        "%s: Can't fetch timetables. Incorrect response from %s",
                        self.station_no,
                        url + "&indent=yes",
                    )
                    return

                unformatted_journeys = json.loads(data)
                formatted_journeys = self.format_journeys(
                    unformatted_journeys, weekday_index
                )

                for journey in formatted_journeys:
                    journeys.append(journey)

                if unformatted_journeys["data"]["headers"]["paging"]["moreData"]:
                    journeys_index += PAGE_SIZE
                else:
                    break

        for i in range(self._current_weekday_int, self._current_weekday_int + 7):
            await fetch_data_for_weekday(i % 7)

        return journeys

    def format_departures(self, departures):
        if self.station_no in departures["body"]:
            body = departures["body"][self.station_no]
            formatted_data = []
            for departure in body:
                formatted_departure = {
                    "line": departure["lineRef"],
                    "destinationCode": departure["destinationShortName"],
                    "departureTime": self.get_departure_time(departure, DEPARTURE),
                    "aimedArrivalTime": self.get_departure_time(
                        departure, DEPARTURE, time_type=AIMED_ARRIVAL_TIME
                    ),
                    "realtime": True,
                }
                formatted_data.append(formatted_departure)
            return formatted_data
        return []

    def format_journeys(self, journeys, weekday):
        formatted_data = []

        if weekday == self._current_weekday_int:
            delta = timedelta(seconds=0)
        elif weekday > self._current_weekday_int:
            delta = timedelta(days=weekday - self._current_weekday_int)
        else:
            delta = timedelta(days=7 - self._current_weekday_int + weekday)

        for journey in journeys["body"]:
            for call in journey["calls"]:
                formatted_journey = {
                    "line": journey["lineUrl"].split("/")[7],
                    "stopCode": call["stopPoint"]["shortName"],
                    "destinationCode": journey["calls"][-1]["stopPoint"]["shortName"],
                    "departureTime": self.get_departure_time(call, JOURNEY, delta),
                    "realtime": False,
                }
                formatted_data.append(formatted_journey)
        return formatted_data

    def get_departure_time(
        self, item, item_type, delta=timedelta(seconds=0), time_type=""
    ):
        if item_type == DEPARTURE:
            if time_type != "":
                return parser.parse(item["call"][time_type]) or "unavailable"
            return (
                parser.parse(item["call"][EXPECTED_ARRIVAL_TIME])
                or parser.parse(item["call"][EXPECTED_DEPARTURE_TIME])
                or parser.parse(item["call"][AIMED_ARRIVAL_TIME])
                or parser.parse(item["call"][AIMED_DEPARTURE_TIME])
                or "unavailable"
            )
        if item_type == JOURNEY:
            return parser.parse(
                (self._last_update_time + delta).strftime("%Y-%m-%dT")
                + item["arrivalTime"]
                + self._last_update_time.strftime("%z")[:3]
                + ":"
                + self._last_update_time.strftime("%z")[3:]
            )

    async def async_update(self) -> None:
        """Fetch new state data for the sensor.
        This is the only method that should fetch new data for Home Assistant.
        """
        self._last_update_time = datetime.now().astimezone(self._time_zone)
        self._current_weekday_int = self._last_update_time.weekday()

        try:
            await self.fetch_stops()

            departures = await self.fetch_departures()
            departures, self._journeys = self.remove_stale_data(
                departures, self._journeys
            )

            if len(self._journeys) < self.max_items:
                _LOGGER.debug(
                    "%s: Not enough timetable data remaining. Trying to fetch new data",
                    self.station_no,
                )
                journeys = await self.fetch_journeys()

                departures, self._journeys = self.remove_stale_data(
                    departures, journeys
                )

                _LOGGER.debug(
                    "%s: Got %s valid departures and %s valid journeys",
                    self.station_no,
                    len(departures),
                    len(self._journeys),
                )

            _LOGGER.debug("%s: Data fetching complete", self.station_no)
            self._nysse_data.populate(
                departures,
                self._journeys,
                self.station_no,
                self._stops,
                self.max_items,
                self._last_update_time,
            )
            self._state = self._nysse_data.get_state()
            self._departures = self._nysse_data.get_departures()
        except OSError as err:
            _LOGGER.error("%s: Failed to update sensor: %s", self.station_no, err)

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        self._station_name = self._nysse_data.get_station_name()
        return "{0} ({1})".format(self._station_name, self.station_no)

    @property
    def icon(self) -> str:
        """Icon of the sensor."""
        return DEFAULT_ICON

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        attributes = {}
        attributes["last_refresh"] = self._nysse_data.get_last_update()

        if len(self._departures) != 0:
            attributes["departures"] = self._departures
            attributes["station_name"] = self._station_name

        return attributes
