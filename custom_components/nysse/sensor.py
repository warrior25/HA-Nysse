"""Platform for sensor integration."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging

from dateutil import parser
from dateutil.parser import ParserError
import isodate

from homeassistant import config_entries, core
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import CALLBACK_TYPE
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
import homeassistant.util.dt as dt_util

from .const import (
    CONF_LINES,
    CONF_STATION,
    DEFAULT_ICON,
    DOMAIN,
    MAX,
    PLATFORM_NAME,
    REALTIME,
    SERVICE_ALERTS_URL,
    STOP_URL,
    TIMELIMIT,
    TRAM_LINES,
    UPDATE_INTERVAL,
)
from .fetch_api import StopTime, get_stop_times, get_stops
from .network import get

_LOGGER = logging.getLogger(__name__)

# Applies to alerts sensor
SCAN_INTERVAL = timedelta(minutes=5)


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setups sensors from a config entry created in the integrations UI."""
    sensors = []
    config_data = {**config_entry.data, **config_entry.options}

    configs = hass.data[DOMAIN]
    if len(configs) > 0:
        if config_entry.entry_id == next(iter(configs)):
            sensors.append(ServiceAlertSensor())

    sensors.append(
        NysseSensor(
            config_data[CONF_STATION],
            config_data.get(MAX.name, MAX.default),
            config_data.get(TIMELIMIT.name, TIMELIMIT.default),
            config_data[CONF_LINES],
            config_data.get(REALTIME.name, REALTIME.default),
            config_data.get(UPDATE_INTERVAL.name, UPDATE_INTERVAL.default),
        )
    )

    async_add_entities(sensors, update_before_add=True)


class NysseSensor(SensorEntity):
    """Representation of a Sensor."""

    _attr_should_poll = False

    def __init__(
        self, stop_code, maximum, timelimit, lines, use_realtime, scan_interval
    ) -> None:
        """Initialize the sensor."""
        self._stop_code = stop_code
        self._max_items = int(maximum)
        self._timelimit = int(timelimit)
        self._lines = lines
        self._use_realtime = bool(use_realtime)
        self._scan_interval = timedelta(seconds=int(scan_interval))

        self._journeys = []
        self._stops = []
        self._all_data = []
        self._unsub_refresh: CALLBACK_TYPE | None = None

        self._last_update_time = None

    async def async_added_to_hass(self) -> None:
        """Set up the periodic update callback for this sensor."""
        self._unsub_refresh = async_track_time_interval(
            self.hass,
            self._async_handle_interval,
            self._scan_interval,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cancel periodic updates when the sensor is removed."""
        if self._unsub_refresh is not None:
            self._unsub_refresh()
            self._unsub_refresh = None

    async def _async_handle_interval(self, now: datetime) -> None:
        """Handle scheduled updates."""
        await self.async_update_ha_state(True)

    def _remove_unwanted_departures(self, departures: list[StopTime]):
        try:
            removed_departures_count = 0

            # Remove unwanted departures based on departure time and line number
            for departure in departures[:]:
                departure_local = dt_util.as_local(departure.departure_time)
                if (
                    departure_local
                    < self._last_update_time + timedelta(minutes=self._timelimit)
                    or departure.route_id not in self._lines
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
                return None
            unformatted_departures = json.loads(data)
            return self._format_departures(unformatted_departures)
        except OSError as err:
            _LOGGER.error("%s: Failed to fetch realtime data: %s", self._stop_code, err)
            return []

    def _format_departures(self, departures):
        try:
            body = departures.get("body", {}).get(self._stop_code, [])
            formatted_data: list[StopTime] = []
            for departure in body:
                try:
                    formatted_departure = StopTime(
                        departure["lineRef"],
                        self._get_stop_name(departure["destinationShortName"]),
                        parser.parse(departure["call"]["expectedDepartureTime"]),
                        parser.parse(departure["call"]["aimedDepartureTime"]),
                        self._delay_to_display_format(departure["delay"]),
                        0,
                        True,
                    )
                    formatted_data.append(formatted_departure)
                except (KeyError, ParserError) as err:
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

            departures: list[StopTime] = []
            if self._use_realtime:
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
                        if (
                            journey.departure_time == departure.aimed_departure_time
                            and journey.route_id == departure.route_id
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
        except OSError as err:
            _LOGGER.error("%s: Failed to update sensor: %s", self._stop_code, err)

    def _data_to_display_format(self, data: list[StopTime]):
        try:
            formatted_data = []
            for item in data:
                departure = {
                    "destination": item.trip_headsign,
                    "line": item.route_id,
                    "departure": item.departure_time.strftime("%H:%M"),
                    "time_to_station": self._time_to_station(item),
                    "icon": self._get_line_icon(item.route_id),
                    "realtime": item.realtime,
                }
                if item.aimed_departure_time is not None:
                    departure["aimed_departure"] = item.aimed_departure_time.strftime(
                        "%H:%M"
                    )
                if item.delay is not None:
                    departure["delay"] = item.delay
                formatted_data.append(departure)
            return sorted(formatted_data, key=lambda x: x["time_to_station"])
        except (OSError, ValueError) as err:
            _LOGGER.debug("%s: Failed to format data:  %s", self._stop_code, err)
            return []

    def _get_line_icon(self, line_no):
        if line_no in TRAM_LINES:
            return "mdi:tram"
        return "mdi:bus"

    def _time_to_station(self, item: StopTime):
        try:
            departure_local = dt_util.as_local(item.departure_time)
            if item.delta_days > 0:
                departure_local += timedelta(days=item.delta_days)
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
        return {
            "last_refresh": self._last_update_time,
            "departures": self._all_data,
            "station_name": self._get_stop_name(self._stop_code),
            "station_id": self._stop_code,
        }


class ServiceAlertSensor(SensorEntity):
    """Representation of a service alert sensor."""

    def __init__(self) -> None:
        """Initialize the sensor."""
        self._last_update = ""
        self._alerts = []

    def _timestamp_to_local(self, timestamp):
        try:
            utc = dt_util.utc_from_timestamp(int(str(timestamp)[:10]))
            return dt_util.as_local(utc)
        except OSError as err:
            _LOGGER.error("Failed to convert timestamp to local time: %s", err)
            return ""

    async def _fetch_service_alerts(self):
        try:
            alerts = []
            _LOGGER.debug("Fetching service alerts from %s", SERVICE_ALERTS_URL)
            data = await get(SERVICE_ALERTS_URL)
            if not data:
                _LOGGER.warning(
                    "Nysse API error: failed to fetch service alerts: no data received from %s",
                    SERVICE_ALERTS_URL,
                )
                return None
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
            return []
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
        return {
            "last_refresh": self._last_update,
            "alerts": self._alerts,
        }
