from dateutil import parser
import pytz
import logging
from .const import (
    TRAM_LINES,
)

_LOGGER = logging.getLogger(__name__)


class NysseData:
    def __init__(self):
        # Last update timestamp for the sensor
        self._last_update = None

        # Variable to store all fetched data
        self._json_data = []

        self._station_id = ""
        self._stops = []

    def populate(
        self,
        departures,
        journeys,
        station_id,
        stops,
        max_items,
        update_time,
    ):
        """Collect sensor data to corresponding variables."""
        self._station_id = station_id
        self._stops = stops
        self._last_update = update_time

        # Store realtime arrival data
        self._json_data = departures[:max_items]

        # Append static timetable data if not enough realtime data
        i = 0
        while len(self._json_data) < max_items:
            if i < len(journeys):
                self._json_data.append(journeys[i])
                i += 1
            else:
                _LOGGER.info(
                    "%s: Not enough timetable data was found. Try decreasing the number of requested departures",
                    station_id,
                )
                break

    def get_state(self):
        """Get next departure time as the sensor state."""
        if len(self._json_data) > 0:
            depart_time = self._json_data[0]["departureTime"].strftime("%H:%M")
            return depart_time

    def get_departures(self):
        """Format departure data to show in sensor attributes."""
        departures = []
        for item in self._json_data:
            departure = {
                "destination": self._stops[item["destinationCode"]],
                "line": item["line"],
                "departure": item["departureTime"].strftime("%H:%M"),
                "time_to_station": self.time_to_station(item, self._last_update),
                "icon": self.get_line_icon(item["line"]),
                "realtime": item["realtime"],
            }

            # Append only valid departures
            if departure["time_to_station"] != "unavailable":
                departures.append(departure)
            else:
                _LOGGER.debug(
                    "Discarding departure with unavailable time_to_station field: %s",
                    departure,
                )

        # Sort departures according to their departure times
        departures = sorted(departures, key=lambda d: d["time_to_station"])
        return departures

    def get_line_icon(self, line_no):
        if line_no in (TRAM_LINES):
            return "mdi:tram"
        return "mdi:bus"

    def get_station_name(self):
        return self._stops[self._station_id]

    def get_last_update(self):
        return self._last_update

    def time_to_station(self, item, current_time, seconds=False):
        """Get time until departure"""
        if item["departureTime"] != "unavailable":
            next_departure_time = (item["departureTime"] - current_time).seconds

            if seconds:
                return next_departure_time

            return int(next_departure_time / 60)

        return "unavailable"
