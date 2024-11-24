"""Platform for sensor integration."""

from __future__ import annotations

from datetime import timedelta
import json
import logging

from dateutil import parser
import isodate

from homeassistant import config_entries, core
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.util.dt as dt_util

from .const import (
    DEFAULT_ICON,
    DEFAULT_MAX,
    DEFAULT_TIMELIMIT,
    DOMAIN,
    PLATFORM_NAME,
    SERVICE_ALERTS_URL,
    STOP_URL,
    TRAM_LINES,
)
from .fetch_api import get_stop_times, get_stops
from .network import get

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


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
        self._stop_code = stop_code
        self._max_items = int(maximum)
        self._timelimit = int(timelimit)
        self._lines = lines

        self._journeys = []
        self._stops = []
        self._all_data = []

        self._last_update_time = None

    def _remove_unwanted_departures(self, departures):
        try:
            removed_departures_count = 0

            # Remove unwanted departures based on departure time and line number
            for departure in departures[:]:
                departure_local = dt_util.as_local(
                    parser.parse(departure["departure_time"])
                )
                if (
                    departure_local
                    < self._last_update_time + timedelta(minutes=self._timelimit)
                    or departure["route_id"] not in self._lines
                ):
                    departures.remove(departure)
                    removed_departures_count += 1

            if removed_departures_count > 0:
                _LOGGER.debug(
                    "%s: Removed %s stale or unwanted departures",
                    self._stop_code,
                    removed_departures_count,
                )

            return departures[: self._max_items]
        except (KeyError, TypeError, OSError) as err:
            _LOGGER.info(
                "%s: Failed to process realtime departures: %s",
                self._stop_code,
                err,
            )
            return []

    async def _fetch_departures(self):
        try:
            url = STOP_URL.format(self._stop_code)
            _LOGGER.debug(
                "%s: Fectching departures from %s",
                self._stop_code,
                url + "&indent=yes",
            )
            data = await get(url)
            if not data:
                _LOGGER.warning(
                    "%s: Nysse API error: failed to fetch realtime data: no data received from %s",
                    self._stop_code,
                    url,
                )
                return
            unformatted_departures = json.loads(data)
            return self._format_departures(unformatted_departures)
        except OSError as err:
            _LOGGER.error("%s: Failed to fetch realtime data: %s", self._stop_code, err)
            return []

    def _format_departures(self, departures):
        try:
            body = departures["body"][self._stop_code]
            formatted_data = []
            for departure in body:
                try:
                    formatted_departure = {
                        "route_id": departure["lineRef"],
                        "trip_headsign": self._get_stop_name(
                            departure["destinationShortName"]
                        ),
                        "departure_time": departure["call"]["expectedDepartureTime"],
                        "aimed_departure_time": departure["call"]["aimedDepartureTime"],
                        "delay": departure["delay"],
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
                        self._stop_code,
                        err,
                    )
                    continue
            return formatted_data
        except KeyError as err:
            _LOGGER.info(
                "%s: Nysse API error: failed to process realtime data: %s",
                self._stop_code,
                err,
            )
            return []
        except OSError as err:
            _LOGGER.info(
                "%s: failed to process realtime data: %s",
                self._stop_code,
                err,
            )
            return []

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            self._last_update_time = dt_util.now()

            if len(self._stops) == 0:
                _LOGGER.debug("Getting stops")
                self._stops = await get_stops()

            departures = await self._fetch_departures()
            departures = self._remove_unwanted_departures(departures)
            if len(departures) < self._max_items:
                self._journeys = await get_stop_times(
                    self._stop_code,
                    self._lines,
                    self._max_items,
                    self._last_update_time + timedelta(minutes=self._timelimit),
                )
                for journey in self._journeys[:]:
                    for departure in departures:
                        departure_time = parser.parse(departure["aimed_departure_time"])
                        journey_time = dt_util.as_local(
                            parser.parse(journey["departure_time"])
                        )
                        if (
                            journey_time == departure_time
                            and journey["route_id"] == departure["route_id"]
                        ):
                            self._journeys.remove(journey)
            else:
                self._journeys.clear()

            self._all_data = self._data_to_display_format(departures + self._journeys)

            _LOGGER.debug(
                "%s: Got %s valid departures and %s valid journeys",
                self._stop_code,
                len(departures),
                len(self._journeys),
            )
        except (OSError, ValueError) as err:
            _LOGGER.error("%s: Failed to update sensor: %s", self._stop_code, err)

    def _data_to_display_format(self, data):
        try:
            formatted_data = []
            for item in data:
                departure = {
                    "destination": item["trip_headsign"],
                    "line": item["route_id"],
                    "departure": parser.parse(item["departure_time"]).strftime("%H:%M"),
                    "time_to_station": self._time_to_station(item),
                    "icon": self._get_line_icon(item["route_id"]),
                    "realtime": item["realtime"] if "realtime" in item else False,
                }
                if "aimed_departure_time" in item:
                    departure["aimed_departure"] = parser.parse(
                        item["aimed_departure_time"]
                    ).strftime("%H:%M")
                if "delay" in item:
                    departure["delay"] = self._delay_to_display_format(item["delay"])
                formatted_data.append(departure)
            return sorted(formatted_data, key=lambda x: x["time_to_station"])
        except (OSError, ValueError) as err:
            _LOGGER.debug("%s: Failed to format data:  %s", self._stop_code, err)
            return []

    def _get_line_icon(self, line_no):
        if line_no in TRAM_LINES:
            return "mdi:tram"
        return "mdi:bus"

    def _time_to_station(self, item):
        try:
            departure_local = dt_util.as_local(parser.parse(item["departure_time"]))
            if "delta_days" in item:
                departure_local += timedelta(days=item["delta_days"])
            next_departure_time = (departure_local - self._last_update_time).seconds
            return int(next_departure_time / 60)
        except OSError as err:
            _LOGGER.debug(
                "%s: Failed to calculate time to station: %s",
                self._stop_code,
                err,
            )
            return 0

    def _delay_to_display_format(self, item):
        try:
            delay = isodate.parse_duration(item)
            return int(delay.total_seconds())
        except (OSError, ValueError) as err:
            _LOGGER.debug(
                "%s: Failed to format delay: %s",
                self._stop_code,
                err,
            )
            return 0

    def _get_stop_name(self, stop_id):
        try:
            return next(
                (
                    stop["stop_name"]
                    for stop in self._stops
                    if stop["stop_id"] == stop_id
                ),
                "unknown stop",
            )
        except (OSError, KeyError) as err:
            _LOGGER.debug(
                "%s: Failed to get stop name: %s",
                self._stop_code,
                err,
            )
            return "unknown stop"

    @property
    def unique_id(self) -> str:
        """Unique id for the sensor."""
        return PLATFORM_NAME + "_" + self._stop_code

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        stop_name = self._get_stop_name(self._stop_code)
        return f"{stop_name} ({self._stop_code})"

    @property
    def icon(self) -> str:
        """Icon of the sensor."""
        return DEFAULT_ICON

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        if len(self._all_data) > 0:
            return self._all_data[0]["departure"]
        return "unknown"

    @property
    def extra_state_attributes(self):
        """Sensor attributes."""
        attributes = {
            "last_refresh": self._last_update_time,
            "departures": self._all_data,
            "station_name": self._get_stop_name(self._stop_code),
        }
        return attributes


class ServiceAlertSensor(SensorEntity):
    """Representation of a service alert sensor."""

    def __init__(self) -> None:
        """Initialize the sensor."""
        self._last_update = ""
        self._alerts = []
        self._empty_response_counter = 0

    def _timestamp_to_local(self, timestamp):
        try:
            utc = dt_util.utc_from_timestamp(int(str(timestamp)[:10]))
            return dt_util.as_local(utc)
        except OSError as err:
            _LOGGER.error("Failed to convert timestamp to local time: %s", err)
            return ""

    def _conditionally_clear_alerts(self):
        # TODO: Individual alerts may never be removed
        if self._empty_response_counter >= 20:
            self._empty_response_counter = 0
            self._alerts.clear()

    async def _fetch_service_alerts(self):
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

            self._last_update = self._timestamp_to_local(
                json_data["header"]["timestamp"]
            )

            for item in json_data["entity"]:
                start_time = self._timestamp_to_local(
                    item["alert"]["active_period"][0]["start"]
                )
                end_time = self._timestamp_to_local(
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
            self._conditionally_clear_alerts()
            return self._alerts
        except OSError as err:
            _LOGGER.error("Failed to fetch service alerts: %s", err)
            return []

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        self._alerts = await self._fetch_service_alerts()

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
        try:
            return len(self._alerts)
        except TypeError:
            return 0

    @property
    def extra_state_attributes(self):
        """Sensor attributes."""
        attributes = {
            "last_refresh": self._last_update,
            "alerts": self._alerts,
        }
        return attributes
