"""Platform for sensor integration."""

from __future__ import annotations

from datetime import timedelta
import json
import logging

from dateutil import parser

from homeassistant import config_entries, core
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.util.dt as dt_util

from .const import (
    AIMED_ARRIVAL_TIME,
    AIMED_DEPARTURE_TIME,
    DEFAULT_ICON,
    DEFAULT_MAX,
    DEFAULT_TIMELIMIT,
    DEPARTURE,
    DOMAIN,
    EXPECTED_ARRIVAL_TIME,
    EXPECTED_DEPARTURE_TIME,
    JOURNEY,
    PLATFORM_NAME,
    SERVICE_ALERTS_URL,
    STOP_URL,
    TRAM_LINES,
)
from .fetch_api import get_stop_times, get_stops
from .network import get

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)
PAGE_SIZE = 100


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setups sensors from a config entry created in the integrations UI."""
    sensors = []
    configs = hass.data[DOMAIN]
    if len(configs) > 0:
        if config_entry.entry_id == next(iter(configs)):
            sensors.append(ServiceAlertSensor())

    if "station" in config_entry.options:
        sensors.append(
            NysseSensor(
                config_entry.options["station"],
                config_entry.options.get("max", DEFAULT_MAX),
                config_entry.options.get("timelimit", DEFAULT_TIMELIMIT),
                config_entry.options["lines"],
            )
        )
    else:
        sensors.append(
            NysseSensor(
                config_entry.data["station"],
                config_entry.data.get("max", DEFAULT_MAX),
                config_entry.data.get("timelimit", DEFAULT_TIMELIMIT),
                config_entry.data["lines"],
            )
        )

    async_add_entities(sensors, update_before_add=True)


class NysseSensor(SensorEntity):
    """Representation of a Sensor."""

    def __init__(self, stop_code, maximum, timelimit, lines) -> None:
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

    async def fetch_stops(self, force=False):
        """Fetch stops if not fetched already."""
        if len(self._stops) == 0 or force:
            _LOGGER.debug("Fetching stops")
            self._stops = await get_stops()

    def remove_unwanted_data(self, departures):
        """Remove stale and unwanted data."""
        removed_departures_count = 0

        # Remove unwanted departures based on departure time and line number
        for departure in departures[:]:
            departure_local = dt_util.as_local(
                parser.parse(departure["departure_time"])
            )
            if (
                departure_local
                < self._last_update_time + timedelta(minutes=self.timelimit)
                or departure["route_id"] not in self.lines
            ):
                departures.remove(departure)
                removed_departures_count += 1

        if removed_departures_count > 0:
            _LOGGER.debug(
                "%s: Removed %s stale or unwanted departures",
                self.stop_code,
                removed_departures_count,
            )

        return departures[: self.max_items]

    async def fetch_departures(self):
        """Fetch live stop monitoring data."""
        url = STOP_URL.format(self.stop_code)
        _LOGGER.debug(
            "%s: Fectching departures from %s",
            self.stop_code,
            url + "&indent=yes",
        )
        data = await get(url)
        if not data:
            _LOGGER.warning(
                "%s: Nysse API error: failed to fetch realtime data: no data received from %s",
                self.stop_code,
                url,
            )
            return
        unformatted_departures = json.loads(data)
        return self.format_departures(unformatted_departures)

    def format_departures(self, departures):
        """Format live stop monitoring data."""
        try:
            body = departures["body"][self.stop_code]
            formatted_data = []
            for departure in body:
                try:
                    formatted_departure = {
                        "route_id": departure["lineRef"],
                        "trip_headsign": self.get_stop_name(
                            departure["destinationShortName"]
                        ),
                        "departure_time": departure["call"][EXPECTED_DEPARTURE_TIME],
                        "aimed_departure_time": departure["call"][AIMED_DEPARTURE_TIME],
                        "realtime": True,
                    }
                    if (
                        formatted_departure["departure_time"] is not None
                        and formatted_departure["aimed_departure_time"] is not None
                    ):
                        formatted_data.append(formatted_departure)
                except KeyError as err:
                    _LOGGER.info(
                        "%s: Failed to process realtime departure: %s",
                        self.stop_code,
                        err,
                    )
                    continue
            return formatted_data
        except KeyError as err:
            _LOGGER.info(
                "%s: Nysse API error: failed to process realtime data: %s",
                self.stop_code,
                err,
            )
            return []

    def format_journeys(self, journeys, weekday):
        """Format static timetable data."""
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
                        _LOGGER.info(
                            "%s: Failed to process timetable departure: %s",
                            self.stop_code,
                            err,
                        )
                        continue
        except KeyError as err:
            _LOGGER.info(
                "%s: Nysse API error: failed to fetch timetable data: %s",
                self.stop_code,
                err,
            )
        return formatted_data

    def get_departure_time(
        self, item, item_type, delta=timedelta(seconds=0), time_type=""
    ):
        """Calculate departure time."""
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
        except (ValueError, KeyError):
            return None

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        self._last_update_time = dt_util.now()
        self._current_weekday_int = self._last_update_time.weekday()

        try:
            await self.fetch_stops()
            if len(self._stops) == 0:
                return

            departures = await self.fetch_departures()
            departures = self.remove_unwanted_data(departures)
            if len(departures) < self.max_items:
                self._journeys = await get_stop_times(
                    self.stop_code,
                    self.lines,
                    self.max_items - len(departures),
                    self._last_update_time,
                )
                for journey in self._journeys[:]:
                    print(
                        journey["route_id"]
                        + " - "
                        + journey["trip_headsign"]
                        + " - "
                        + journey["departure_time"]
                    )
                    for departure in departures:
                        departure_time = parser.parse(departure["aimed_departure_time"])
                        journey_time = parser.parse(journey["departure_time"])
                        if (
                            journey_time == departure_time
                            and journey["route_id"] == departure["route_id"]
                        ):
                            self._journeys.remove(journey)
            else:
                self._journeys.clear()

            self._all_data = self.data_to_display_format(departures + self._journeys)

            _LOGGER.debug(
                "%s: Got %s valid departures and %s valid journeys",
                self.stop_code,
                len(departures),
                len(self._journeys),
            )
            _LOGGER.debug("%s: Data fetching complete", self.stop_code)
        except OSError as err:
            _LOGGER.error("%s: Failed to update sensor: %s", self.stop_code, err)

    def data_to_display_format(self, data):
        """Format data to be displayed in sensor attributes."""
        formatted_data = []
        for item in data:
            departure = {
                "destination": item["trip_headsign"],
                "line": item["route_id"],
                "departure": parser.parse(item["departure_time"]).strftime("%H:%M"),
                "time_to_station": self.time_to_station(item),
                "icon": self.get_line_icon(item["route_id"]),
                "realtime": item["realtime"] if "realtime" in item else False,
            }
            formatted_data.append(departure)
        return formatted_data

    def get_line_icon(self, line_no):
        """Get line icon based on operating vehicle type."""
        if line_no in TRAM_LINES:
            return "mdi:tram"
        return "mdi:bus"

    def time_to_station(self, item):
        """Get time until departure."""
        departure_local = dt_util.as_local(parser.parse(item["departure_time"]))
        next_departure_time = (departure_local - self._last_update_time).seconds
        return int(next_departure_time / 60)

    def get_stop_name(self, stop_id):
        """Get the name of the stop."""
        return next(
            (stop["stop_name"] for stop in self._stops if stop["stop_id"] == stop_id),
            "unknown stop",
        )

    @property
    def unique_id(self) -> str:
        """Unique id for the sensor."""
        return PLATFORM_NAME + "_" + self.stop_code

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        stop_name = self.get_stop_name(self.stop_code)
        return f"{stop_name} ({self.stop_code})"

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
        """Sensor attributes."""
        attributes = {
            "last_refresh": self._last_update_time,
            "departures": self._all_data,
            "station_name": self.get_stop_name(self.stop_code),
        }
        return attributes


class ServiceAlertSensor(SensorEntity):
    """Representation of a service alert sensor."""

    def __init__(self) -> None:
        """Initialize the sensor."""
        self._last_update = ""
        self._alerts = []
        self._empty_response_counter = 0

    def timestamp_to_local(self, timestamp):
        """Convert timestamp to local datetime."""
        utc = dt_util.utc_from_timestamp(int(str(timestamp)[:10]))
        return dt_util.as_local(utc)

    def conditionally_clear_alerts(self):
        """Clear alerts if none received in 20 tries."""
        # TODO: Individual alerts may never be removed
        if self._empty_response_counter >= 20:
            self._empty_response_counter = 0
            self._alerts.clear()

    async def fetch_service_alerts(self):
        """Fetch service alerts."""
        try:
            alerts = []
            data = await get(SERVICE_ALERTS_URL)
            if not data:
                _LOGGER.warning(
                    "Nysse API error: failed to fetch service alerts: no data received from %s",
                    SERVICE_ALERTS_URL,
                )
                return
            json_data = json.loads(data)

            self._last_update = self.timestamp_to_local(
                json_data["header"]["timestamp"]
            )

            for item in json_data["entity"]:
                start_time = self.timestamp_to_local(
                    item["alert"]["active_period"][0]["start"]
                )
                end_time = self.timestamp_to_local(
                    item["alert"]["active_period"][0]["end"]
                )
                description = item["alert"]["description_text"]["translation"][0][
                    "text"
                ]

                formatted_alert = {
                    "description": description,
                    "start": start_time,
                    "end": end_time,
                }
                alerts.append(formatted_alert)

            return alerts

        except KeyError:
            self._empty_response_counter += 1
            self.conditionally_clear_alerts()
            return self._alerts
        except OSError as err:
            _LOGGER.error("Failed to fetch service alerts: %s", err)
            return []

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        self._alerts = await self.fetch_service_alerts()

    @property
    def unique_id(self) -> str:
        """Unique id for the sensor."""
        return "service_alerts"

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return "Nysse Service Alerts"

    @property
    def icon(self) -> str:
        """Icon of the sensor."""
        return "mdi:bus-alert"

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        if len(self._alerts) > 0:
            return len(self._alerts)
        return 0

    @property
    def extra_state_attributes(self):
        """Sensor attributes."""
        attributes = {
            "last_refresh": self._last_update,
            "alerts": self._alerts,
        }
        return attributes
