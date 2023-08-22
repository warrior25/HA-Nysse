from datetime import datetime
from dateutil import parser
import pytz
import logging
from .const import TRAM_LINES

_LOGGER = logging.getLogger(__name__)
LOCAL_TZ = pytz.timezone("Europe/Helsinki")


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
        departures2 = []
        self._station_id = station_id
        self._stops = stops
        self._last_update = update_time

        if self._station_id in departures["body"]:
            departures2 = departures["body"][self._station_id]

        # Store realtime arrival data
        self._json_data = departures2[:max_items]

        # Append static timetable data if not enough realtime data
        i = 0
        while len(self._json_data) < max_items:
            if i < len(journeys):
                self._json_data.append(journeys[i])
                i += 1
            else:
                _LOGGER.warning(
                    "%s: Not enough timetable data was found. Try decreasing the number of requested departures",
                    station_id,
                )
                break

    def get_state(self):
        """Get next departure time as the sensor state."""
        if len(self._json_data) > 0:
            depart_time = self.get_departure_time(self._json_data[0], True)
            if depart_time != "unavailable":
                return parser.parse(depart_time).strftime("%H:%M")

    def get_departures(self):
        """Format departure data to show in sensor attributes."""
        departures = []
        for item in self._json_data:
            departure = {
                "destination": self.get_destination_name(item),
                "line": item["lineRef"],
                "departure": self.get_departure_time(item, True),
                "time_to_station": self.time_to_station(item, self._last_update),
                "icon": self.get_line_icon(item["lineRef"]),
                "realtime": self.is_realtime(item),
            }

            # Append only valid departures
            if departure["time_to_station"] != "unavailable":
                departures.append(departure)
            else:
                _LOGGER.debug("Discarding departure with unavailable time_to_station")
                _LOGGER.debug(departure)

        # Sort departures according to their departure times
        departures = sorted(departures, key=lambda d: d["time_to_station"])
        return departures

    def is_realtime(self, item):
        """Check if departure data is from realtime data source"""
        if "non-realtime" in item:
            return False
        return True

    def get_departure_time(self, item, stringify=False, time_type="any"):
        """Get departure time from json data"""
        if "expectedArrivalTime" in item["call"] and time_type == "any":
            parsed = parser.parse(item["call"]["expectedArrivalTime"])
        elif "expectedDepartureTime" in item["call"] and time_type == "any":
            parsed = parser.parse(item["call"]["expectedDepartureTime"])
        elif "aimedArrivalTime" in item["call"] and (
            time_type in ("any", "aimedArrival")
        ):
            parsed = parser.parse(item["call"]["aimedArrivalTime"])
        elif "aimedDepartureTime" in item["call"] and time_type == "any":
            parsed = parser.parse(item["call"]["aimedDepartureTime"])

        try:
            parsed
        except NameError:
            return "unavailable"
        else:
            if stringify:
                return parsed.strftime("%H:%M")
            return parsed

    def get_line_icon(self, line_no):
        if line_no in (TRAM_LINES):
            return "mdi:tram"
        return "mdi:bus"

    def get_station_name(self):
        return self._stops[self._station_id]

    def get_last_update(self):
        return self._last_update

    def get_destination_name(self, entry):
        if "destinationShortName" in entry:
            return self._stops[entry["destinationShortName"]]
        return "unavailable"

    def time_to_station(self, entry, current_time, seconds=False):
        """Get time until departure in minutes"""
        time = self.get_departure_time(entry, False)
        if time != "unavailable":
            next_departure_time = (time - current_time).seconds

            if seconds:
                return next_departure_time

            return int(next_departure_time / 60)

        return "unavailable"
