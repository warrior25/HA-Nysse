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
from .fetch_api import fetch_stop_points
from .const import *

_LOGGER = logging.getLogger(__name__)
# Changing this also affects
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

    def __init__(self, stop_code, maximum, timelimit, lines, time_zone) -> None:
        """Initialize the sensor."""

        self._unique_id = PLATFORM_NAME + "_" + stop_code
        self.stop_code = stop_code
        self.max_items = int(maximum)
        self.timelimit = int(timelimit)
        self.lines = lines

        self._journeys = []
        self._stops = []
        self._all_data = []

        self._current_weekday_int = -1
        self._last_update_time = None
        self._time_zone = pytz.timezone(time_zone)

        self._fetch_fail_counter = 0
        self._fetch_pause_counter = 0

    async def fetch_stops(self, force=False):
        if len(self._stops) == 0 or force:
            _LOGGER.debug("Fetching stops")
            self._stops = await fetch_stop_points(False)

    def remove_unwanted_data(self, departures, journeys):
        removed_journey_count = 0
        removed_departures_count = 0

        # Remove unwanted journeys based on departure time and stop code
        for journey in journeys[:]:
            if journey["departureTime"] < self._last_update_time + timedelta(
                minutes=self.timelimit
            ) or (journey["stopCode"] != self.stop_code):
                journeys.remove(journey)
                removed_journey_count += 1

        # Remove unwanted departures based on departure time and line number
        for departure in departures[:]:
            if departure["line"] in self.lines:
                # Remove journeys matching departures
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
                self.stop_code,
                removed_journey_count,
            )

        if removed_departures_count > 0:
            _LOGGER.debug(
                "%s: Removed %s stale or unwanted departures",
                self.stop_code,
                removed_departures_count,
            )

        return departures, journeys

    async def fetch_departures(self):
        url = NYSSE_STOP_URL.format(self.stop_code)
        _LOGGER.debug(
            "%s: Fectching departures from %s",
            self.stop_code,
            url + "&indent=yes",
        )
        data = await get(url)
        if not data:
            _LOGGER.warning(
                "%s: Can't fetch departures. Incorrect response from %s",
                self.stop_code,
                url,
            )
            return
        unformatted_departures = json.loads(data)
        return self.format_departures(unformatted_departures)

    async def fetch_journeys(self):
        journeys = []

        async def fetch_data_for_weekday(weekday_index):
            journeys_index = 0
            weekday_string = WEEKDAYS[weekday_index]
            while True:
                url = NYSSE_JOURNEYS_URL.format(
                    self.stop_code, weekday_string, journeys_index
                )
                _LOGGER.debug(
                    "%s: Fetching timetable data from %s",
                    self.stop_code,
                    url + "&indent=yes",
                )
                data = await get(url)
                if not data:
                    _LOGGER.error(
                        "%s: Can't fetch timetables. Incorrect response from %s",
                        self.stop_code,
                        url + "&indent=yes",
                    )
                    return

                unformatted_journeys = json.loads(data)
                formatted_journeys = self.format_journeys(
                    unformatted_journeys, weekday_index
                )

                for journey in formatted_journeys:
                    journeys.append(journey)

                try:
                    if unformatted_journeys["data"]["headers"]["paging"]["moreData"]:
                        journeys_index += PAGE_SIZE
                    else:
                        break
                except KeyError:
                    break

        for i in range(self._current_weekday_int, self._current_weekday_int + 7):
            await fetch_data_for_weekday(i % 7)

        return journeys

    def format_departures(self, departures):
        try:
            body = departures["body"][self.stop_code]
            formatted_data = []
            for departure in body:
                try:
                    formatted_departure = {
                        "line": departure["lineRef"],
                        "destinationCode": departure["destinationShortName"],
                        "departureTime": self.get_departure_time(departure, DEPARTURE),
                        "aimedArrivalTime": self.get_departure_time(
                            departure, DEPARTURE, time_type=AIMED_ARRIVAL_TIME
                        ),
                        "realtime": True,
                    }
                    if (
                        formatted_departure["departureTime"] is not None
                        and formatted_departure["aimedArrivalTime"] is not None
                    ):
                        formatted_data.append(formatted_departure)
                except KeyError as err:
                    _LOGGER.info("Incorrect response structure: %s", err)
                    continue
            return formatted_data
        except KeyError:
            return []

    def format_journeys(self, journeys, weekday):
        formatted_data = []

        if weekday == self._current_weekday_int:
            delta = timedelta(seconds=0)
        elif weekday > self._current_weekday_int:
            delta = timedelta(days=weekday - self._current_weekday_int)
        else:
            delta = timedelta(days=7 - self._current_weekday_int + weekday)

        try:
            for journey in journeys["body"]:
                for call in journey["calls"]:
                    try:
                        formatted_journey = {
                            "line": journey["lineUrl"].split("/")[7],
                            "stopCode": call["stopPoint"]["shortName"],
                            "destinationCode": journey["calls"][-1]["stopPoint"][
                                "shortName"
                            ],
                            "departureTime": self.get_departure_time(
                                call, JOURNEY, delta
                            ),
                            "realtime": False,
                        }
                        if formatted_journey["departureTime"] is not None:
                            formatted_data.append(formatted_journey)
                    except KeyError as err:
                        _LOGGER.info("Incorrect response structure: %s", err)
                        continue
        except KeyError as err:
            _LOGGER.info("Incorrect response structure: %s", err)
        return formatted_data

    def get_departure_time(
        self, item, item_type, delta=timedelta(seconds=0), time_type=""
    ):
        try:
            if item_type == DEPARTURE:
                if time_type != "":
                    parsed_time = parser.parse(item["call"][time_type])
                    return parsed_time
                try:
                    time_fields = [
                        item["call"][EXPECTED_ARRIVAL_TIME],
                        item["call"][EXPECTED_DEPARTURE_TIME],
                        item["call"][AIMED_ARRIVAL_TIME],
                        item["call"][AIMED_DEPARTURE_TIME],
                    ]
                    for field in time_fields:
                        parsed_time = parser.parse(field)
                        return parsed_time
                except (ValueError, KeyError):
                    pass
                return None

            if item_type == JOURNEY:
                parsed_time = parser.parse(
                    (self._last_update_time + delta).strftime("%Y-%m-%dT")
                    + item["arrivalTime"]
                    + self._last_update_time.strftime("%z")[:3]
                    + ":"
                    + self._last_update_time.strftime("%z")[3:]
                )
                return parsed_time
        except (ValueError, KeyError):
            return None

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        self._last_update_time = datetime.now().astimezone(self._time_zone)
        self._current_weekday_int = self._last_update_time.weekday()

        try:
            await self.fetch_stops()
            if len(self._stops) == 0:
                _LOGGER.error("%s: Failed to fetch stops", self.stop_code)
                return

            departures = await self.fetch_departures()
            departures, self._journeys = self.remove_unwanted_data(
                departures, self._journeys
            )

            if self._fetch_pause_counter == 0:
                if len(self._journeys) < self.max_items:
                    _LOGGER.debug(
                        "%s: Not enough timetable data remaining to reach max items. Trying to fetch new data",
                        self.stop_code,
                    )
                    journeys = await self.fetch_journeys()

                    departures, self._journeys = self.remove_unwanted_data(
                        departures, journeys
                    )

                    if len(self._journeys) == 0:
                        self._fetch_fail_counter += 1
                        _LOGGER.warning(
                            "%s: No valid timetable data received from API. This is likely not a problem with the integration. Failed %s time(s) already",
                            self.stop_code,
                            self._fetch_fail_counter,
                        )
                        if self._fetch_fail_counter == 10:
                            self._fetch_fail_counter = 0
                            self._fetch_pause_counter = 30
                            _LOGGER.warning(
                                "%s: Getting timetable data failed too many times. Next attempt in %s minutes. Reload integration to retry immediately",
                                self.stop_code,
                                self._fetch_pause_counter * SCAN_INTERVAL.seconds / 60,
                            )
            else:
                self._fetch_pause_counter -= 1

            _LOGGER.debug(
                "%s: Got %s valid departures and %s valid journeys",
                self.stop_code,
                len(departures),
                len(self._journeys),
            )
            _LOGGER.debug("%s: Data fetching complete", self.stop_code)
            self._all_data = self.combine_data(departures, self._journeys)
        except OSError as err:
            _LOGGER.error("%s: Failed to update sensor: %s", self.stop_code, err)

    def combine_data(self, departures, journeys):
        combined_data = departures[: self.max_items]
        i = 0
        while len(combined_data) < self.max_items:
            if i < len(journeys):
                combined_data.append(journeys[i])
                i += 1
            else:
                _LOGGER.info(
                    "%s: Not enough timetable data was found. Try decreasing the number of requested departures",
                    self.stop_code,
                )
                break
        return self.data_to_display_format(combined_data)

    def data_to_display_format(self, data):
        formatted_data = []
        for item in data:
            departure = {
                "destination": self._stops[item["destinationCode"]],
                "line": item["line"],
                "departure": item["departureTime"].strftime("%H:%M"),
                "time_to_station": self.time_to_station(item),
                "icon": self.get_line_icon(item["line"]),
                "realtime": item["realtime"],
            }
            formatted_data.append(departure)
        return formatted_data

    def get_line_icon(self, line_no):
        if line_no in (TRAM_LINES):
            return "mdi:tram"
        return "mdi:bus"

    def time_to_station(self, item):
        """Get time until departure"""
        next_departure_time = (item["departureTime"] - self._last_update_time).seconds
        return int(next_departure_time / 60)

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return "{0} ({1})".format(self._stops[self.stop_code], self.stop_code)

    @property
    def icon(self) -> str:
        """Icon of the sensor."""
        return DEFAULT_ICON

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        if len(self._all_data) > 0:
            return self._all_data[0]["departure"]
        return

    @property
    def extra_state_attributes(self):
        attributes = {
            "last_refresh": self._last_update_time,
            "departures": self._all_data,
            "station_name": self._stops[self.stop_code],
        }
        return attributes
