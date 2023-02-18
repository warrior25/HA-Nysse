"""Platform for sensor integration."""
from __future__ import annotations
from dateutil import parser

import logging
import json
import pytz
from datetime import timedelta, datetime
import time
from homeassistant import config_entries, core
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .network import request
from .nysse_data import NysseData
from .fetch_stop_points import fetch_stop_points
from .const import (
    CONF_STOPS,
    DEFAULT_MAX,
    DEFAULT_ICON,
    DEFAULT_TIMELIMIT,
    DEFAULT_LINES,
    PLATFORM_NAME,
    DOMAIN,
    NYSSE_JOURNEYS_URL,
    NYSSE_STOP_URL,
    WEEKDAYS,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)

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
                    stop["timelimit"] if "timelimit" in stop else DEFAULT_TIMELIMIT,
                    stop["lines"] if "lines" in stop else DEFAULT_LINES,
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
                    stop["timelimit"],
                    stop["lines"],
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
        self.lines = [line.strip() for line in lines.split(",")]

        self._station_name = ""
        self._state = None
        self._destination = ""
        self._nysse_data = NysseData()
        self._departures = []
        self._stops = []
        self._journeys = {}
        self._live_data = []

        self._current_weekday_int = -1

    def remove_stale_data(self):
        removed_journey_count = 0
        journeys_to_remove = []
        departures_to_remove = []

        for weekday in range(0, 7):
            for journey in self._journeys[weekday]:
                if parser.parse(
                    journey["call"]["expectedArrivalTime"]
                ) < datetime.now().astimezone(LOCAL_TZ) + timedelta(
                    minutes=self.timelimit
                ) or (
                    journey["lineRef"] not in self.lines and self.lines[0] != "all"
                ):
                    journeys_to_remove.append(journey)
            for journey1 in journeys_to_remove:
                removed_journey_count += 1
                self._journeys[weekday].remove(journey1)
            journeys_to_remove.clear()

        if self.station_no in self._live_data["body"]:
            for item in self._live_data["body"][self.station_no]:
                for journey in self._journeys[self._current_weekday_int]:
                    if (
                        parser.parse(journey["call"]["expectedArrivalTime"])
                        == self._nysse_data.get_departure_time(
                            item, False, "aimedArrival"
                        )
                        and journey not in journeys_to_remove
                    ):
                        journeys_to_remove.append(journey)

                if (
                    self._nysse_data.time_to_station(item, True) < (self.timelimit * 60)
                ) or (item["lineRef"] not in self.lines and self.lines[0] != "all"):
                    departures_to_remove.append(item)

        for journey1 in journeys_to_remove:
            removed_journey_count += 1
            self._journeys[self._current_weekday_int].remove(journey1)

        if removed_journey_count > 0:
            _LOGGER.info(
                "%s: Removed %s stale or unwanted journeys",
                self.station_no,
                removed_journey_count,
            )

        if len(departures_to_remove) > 0:
            _LOGGER.info(
                "%s: Removing %s stale or unwanted departures",
                self.station_no,
                len(departures_to_remove),
            )
            for item in departures_to_remove:
                self._live_data["body"][self.station_no].remove(item)

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
                    data_set["destinationShortName"] = journey["calls"][
                        len(journey["calls"]) - 1
                    ]["stopPoint"]["shortName"]
                    data_set["non-realtime"] = True
                    data_set2 = {}

                    data_set2["expectedArrivalTime"] = (
                        (datetime.now().astimezone(LOCAL_TZ) + delta).strftime(
                            "%Y-%m-%d"
                        )
                        + "T"
                        + stop_point["arrivalTime"]
                        + datetime.now(LOCAL_TZ).strftime("%z")[:3]
                        + ":"
                        + datetime.now(LOCAL_TZ).strftime("%z")[3:]
                    )

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
            _LOGGER.info(
                "%s: Fectching departures from %s", self.station_no, departure_url
            )
            self._live_data = await request(departure_url)

            if not self._live_data:
                _LOGGER.warning(
                    "%s: Can't fetch departures. Incorrect response from %s",
                    self.station_no,
                    departure_url,
                )
                self._live_data = []
            else:
                self._live_data = json.loads(self._live_data)

            total_journeys_left = 0
            if len(self._journeys) == 7:
                for i in range(7):
                    total_journeys_left += len(self._journeys[i])

            if total_journeys_left < self.max_items:
                _LOGGER.info(
                    "%s: Not enough timetable data remaining. Trying to fetch new data",
                    self.station_no,
                )
                self._journeys.clear()

                for weekday in WEEKDAYS:
                    journeys_index = 0
                    weekday_int = time.strptime(weekday, "%A").tm_wday

                    while True:
                        journeys_url = NYSSE_JOURNEYS_URL.format(
                            self.station_no, weekday, journeys_index
                        )

                        _LOGGER.info(
                            "%s: Fetching timetable data from %s",
                            self.station_no,
                            journeys_url,
                        )
                        journeys_data = await request(journeys_url)

                        if not journeys_data:
                            _LOGGER.error(
                                "%s: Can't fetch timetables. Incorrect response from %s",
                                self.station_no,
                                journeys_url,
                            )
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
            _LOGGER.error(
                "%s: Unknown exception. Check your internet connection", self.station_no
            )
            return

        self.remove_stale_data()

        _LOGGER.info(
            "%s: Data fetching complete. Populating sensor with data", self.station_no
        )
        self._nysse_data.populate(
            self._live_data,
            self._journeys,
            self.station_no,
            self._stops,
            self.max_items,
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
