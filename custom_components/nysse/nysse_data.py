from datetime import datetime
from dateutil import parser
import pytz
import logging

LOCAL = pytz.timezone("Europe/Helsinki")

_LOGGER = logging.getLogger(__name__)

class NysseData:
    def __init__(self):
        # Last update timestamp for the sensor
        self._last_update = None

        # Variable to store all fetched data
        self._json_data = []

        self._station_id = ""
        self._stops = []

    def populate(self, departures, journeys, station_id, stops, max_items):
        """Collect sensor data to corresponding variables."""
        departures2 = []
        self._station_id = station_id
        self._stops = stops
        self._last_update = datetime.now().astimezone(LOCAL)

        if self._station_id in departures["body"]:
            departures2 = departures["body"][self._station_id]

        # Store realtime arrival data
        self._json_data = departures2[:max_items]

        # Append static timetable data if not enough realtime data
        if len(self._json_data) < max_items:
            for i in range(len(self._json_data), max_items):
                if len(journeys) > i:
                    self._json_data.append(journeys[i])

    def remove_stale_data(self):
        """Remove old or unavailable departures."""
        for item in self._json_data:
            if self.get_departure_time(item, True) == "unavailable":
                _LOGGER.info("Removing unavailable departures")
                self._json_data.remove(item)

            elif (self.get_departure_time(item, False)) < datetime.now().astimezone(LOCAL):
                _LOGGER.info("Removing stale departures")
                self._json_data.remove(item)

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
                "time_to_station": self.time_to_station(item),
                "icon": self.get_line_icon(item["lineRef"]),
                "realtime": self.is_realtime(item),
            }

            # Append only valid departures
            if departure["time_to_station"] != "unavailable":
                departures.append(departure)

        # Sort departures according to their departure times
        departures = sorted(departures, key=lambda d: d['time_to_station'])
        return departures

    def is_realtime(self, item):
        """Check if departure data is from realtime data source"""
        if "non-realtime" in item:
            return False
        return True

    def get_departure_time(self, item, stringify):
        """Get departure time from json data"""
        if "expectedArrivalTime" in item["call"]:
            parsed = parser.parse(item["call"]["expectedArrivalTime"])
            if stringify:
                return parsed.strftime("%H:%M")
            else:
                return parsed
        if "aimedArrivalTime" in item["call"]:
            parsed = parser.parse(item["call"]["aimedArrivalTime"]).strftime("%H:%M")
            if stringify:
                return parsed.strftime("%H:%M")
            else:
                return parsed
        else:
            return "unavailable"

    def get_line_icon(self, line_no):
        if line_no in ("1", "3"):
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

    def time_to_station(self, entry):
        """Get time until departure in minutes"""
        time = self.get_departure_time(entry, True)
        if time != "unavailable":
            # Convert departure time to UTC
            naive = parser.parse(self.get_departure_time(entry, True)).replace(tzinfo=None)
            local_dt = LOCAL.localize(naive, is_dst=None)
            utc_dt = local_dt.astimezone(pytz.utc)
            next_departure_time = (utc_dt - datetime.now().astimezone(pytz.utc)).seconds
            return int(next_departure_time / 60)
        return "unavailable"
