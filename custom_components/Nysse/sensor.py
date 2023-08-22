"""Platform for sensor integration."""
from __future__ import annotations
import logging
import json
from itertools import cycle
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
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)
PAGE_SIZE = 100

LOCAL_TZ = pytz.timezone("Europe/Helsinki")


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
            )
        )

    async_add_entities(sensors, update_before_add=True)


class NysseSensor(SensorEntity):
    """Representation of a Sensor."""

    def __init__(self, name, station, maximum, timelimit, lines):
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
        self._destination = ""
        self._nysse_data = NysseData()
        self._departures = []
        self._stops = []
        self._journeys = []
        self._live_data = []

        self._current_weekday_int = -1
        self._last_update_time = None

    async def fetch_stops(self):
        if len(self._stops) == 0:
            _LOGGER.debug("Fetching stops")
            self._stops = await fetch_stop_points(False)
            if len(self._stops) == 0:
                _LOGGER.error("Failed to fetch stops")

    def strip_journey_data(self, journeys, weekday_int):
        if weekday_int == self._current_weekday_int:
            delta = timedelta(seconds=0)
        elif weekday_int > self._current_weekday_int:
            delta = timedelta(days=weekday_int - self._current_weekday_int)
        else:
            delta = timedelta(days=7 - self._current_weekday_int + weekday_int)

        journeys_data = []
        for journey in journeys["body"]:
            for stop_point in journey["calls"]:
                if stop_point["stopPoint"]["shortName"] == self.station_no:
                    formatted_journey = self.format_journey(journey, stop_point, delta)
                    json_dump = json.dumps(formatted_journey)
                    journeys_data.append(json.loads(json_dump))
        return journeys_data

    def format_journey(self, journey, stop_point, delta):
        line_ref = journey["lineUrl"].split("/")[7]
        destination_short_name = journey["calls"][-1]["stopPoint"]["shortName"]
        expected_arrival_time = (
            (self._last_update_time + delta).strftime("%Y-%m-%dT")
            + stop_point["arrivalTime"]
            + self._last_update_time.strftime("%z")[:3]
            + ":"
            + self._last_update_time.strftime("%z")[3:]
        )

        formatted_data = {
            "lineRef": line_ref,
            "destinationShortName": destination_short_name,
            "non-realtime": True,
            "call": {"expectedArrivalTime": expected_arrival_time},
        }
        return formatted_data

    def remove_stale_data(self):
        removed_journey_count = 0
        removed_departures = []

        # Remove stale journeys based on time and lineRef
        for journey in self._journeys[:]:
            arrival_time = parser.parse(journey["call"]["expectedArrivalTime"])
            if arrival_time < self._last_update_time + timedelta(
                minutes=self.timelimit
            ) or (journey["lineRef"] not in self.lines):
                self._journeys.remove(journey)
                removed_journey_count += 1

        # Remove stale departures based on time and lineRef
        if len(self._live_data) > 0 and self.station_no in self._live_data["body"]:
            for item in self._live_data["body"][self.station_no][:]:
                time_to_station = self._nysse_data.time_to_station(
                    item, self._last_update_time, True
                )
                if (time_to_station < (self.timelimit * 60)) or item[
                    "lineRef"
                ] not in self.lines:
                    removed_departures.append(item)
                    self._live_data["body"][self.station_no].remove(item)

        # Remove corresponding journeys for removed departures
        for item in removed_departures:
            departure_time = self._nysse_data.get_departure_time(
                item, False, "aimedArrival"
            )
            matching_journeys = [
                journey
                for journey in self._journeys
                if parser.parse(journey["call"]["expectedArrivalTime"])
                == departure_time
            ]
            for journey in matching_journeys:
                self._journeys.remove(journey)
                removed_journey_count += 1

        if removed_journey_count > 0:
            _LOGGER.debug(
                "%s: Removed %s stale or unwanted journeys",
                self.station_no,
                removed_journey_count,
            )

        if len(removed_departures) > 0:
            _LOGGER.debug(
                "%s: Removed %s stale or unwanted departures",
                self.station_no,
                len(removed_departures),
            )

    async def fetch_live_data(self):
        departure_url = NYSSE_STOP_URL.format(self.station_no)
        _LOGGER.debug(
            "%s: Fectching departures from %s", self.station_no, departure_url
        )
        live_data = await get(departure_url)
        if not live_data:
            _LOGGER.warning(
                "%s: Can't fetch departures. Incorrect response from %s",
                self.station_no,
                departure_url,
            )
        return json.loads(live_data)

    async def fetch_journeys(self):
        fetched_journeys = []

        async def fetch_data_for_weekday(weekday_index):
            journeys_index = 0
            weekday_string = WEEKDAYS[weekday_index]
            while True:
                journeys_url = NYSSE_JOURNEYS_URL.format(
                    self.station_no, weekday_string, journeys_index
                )
                _LOGGER.debug(
                    "%s: Fetching timetable data from %s",
                    self.station_no,
                    journeys_url,
                )
                journeys_data = await get(journeys_url)
                if not journeys_data:
                    _LOGGER.error(
                        "%s: Can't fetch timetables. Incorrect response from %s",
                        self.station_no,
                        journeys_url,
                    )
                    return

                journeys_data_json = json.loads(journeys_data)
                modified_journey_data = self.strip_journey_data(
                    journeys_data_json, weekday_index
                )

                for journey in modified_journey_data:
                    fetched_journeys.append(journey)

                if journeys_data_json["data"]["headers"]["paging"]["moreData"]:
                    journeys_index += PAGE_SIZE
                else:
                    break

        for i in range(self._current_weekday_int, self._current_weekday_int + 7):
            await fetch_data_for_weekday(i % 7)

        return fetched_journeys

    async def async_update(self):
        """Fetch new state data for the sensor.
        This is the only method that should fetch new data for Home Assistant.
        """
        self._last_update_time = datetime.now().astimezone(LOCAL_TZ)
        self._current_weekday_int = self._last_update_time.weekday()

        try:
            await self.fetch_stops()
            self.remove_stale_data()

            self._live_data = await self.fetch_live_data()

            if len(self._journeys) < self.max_items:
                _LOGGER.debug(
                    "%s: Not enough timetable data remaining. Trying to fetch new data",
                    self.station_no,
                )
                self._journeys = await self.fetch_journeys()
                self.remove_stale_data()
                _LOGGER.debug(
                    "%s: Got %s valid journeys", self.station_no, len(self._journeys)
                )

            _LOGGER.debug("%s: Data fetching complete", self.station_no)
            self._nysse_data.populate(
                self._live_data,
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
