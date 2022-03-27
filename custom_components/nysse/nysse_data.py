from datetime import datetime
from dateutil import parser
import logging
import pytz

_LOGGER = logging.getLogger(__name__)

LOCAL = pytz.timezone("Europe/Helsinki")


class NysseData:
    def __init__(self):
        self._arrival_data = []
        self._journey_data = []
        self._last_update = None
        self._api_json = []
        self._station_name = ""
        self._station = ""
        self._stops = []

    def populate(self, arrival_data, journey_data, station_no, stop_points):
        self._station = station_no
        self._stops = stop_points
        self._last_update = datetime.now().astimezone(LOCAL)

        if self._station in arrival_data["body"]:
            self._arrival_data = arrival_data["body"][self._station]

        self._journey_data = journey_data

    def is_data_stale(self, max_items):
        if len(self._arrival_data) > 0:
            # check if there are enough already stored to skip a request
            now = datetime.now().astimezone(LOCAL)
            after_now = [
                item
                for item in self._arrival_data
                if self.get_departure_time(item) != "unavailable"
                and parser.parse(self.get_departure_time(item)) > now
            ]
            if len(after_now) >= max_items:
                self._arrival_data = after_now
                return False
        return True

    def sort_data(self, max_items):
        self._api_json = self._arrival_data[:max_items]
        if len(self._api_json) < max_items:
            for i in range(len(self._api_json), max_items):
                self._api_json.append(self._journey_data[i])

    def get_state(self):
        if len(self._api_json) > 0:
            depart_time = self.get_departure_time(self._api_json[0])
            if depart_time != "unavailable":
                return parser.parse(depart_time).strftime("%H:%M")

    def is_empty(self):
        return len(self._api_json) == 0

    def get_departures(self):
        departures = []
        for item in self._api_json:
            departure = {
                "time_to_station": self.time_to_station(item, False),
                "time": self.time_to_station(item, False, "{0}"),
                "line": item["lineRef"],
                "destination": self.get_destination(item),
                "departure": self.get_departure_time(item),
                "icon": self.get_line_icon(item["lineRef"]),
                "realtime": self.is_realtime(item),
            }

            departures.append(departure)

        return departures

    def is_realtime(self, item):
        if "non-realtime" in item:
            return False
        return True

    def get_departure_time(self, item):
        if "expectedArrivalTime" in item["call"]:
            return parser.parse(item["call"]["expectedArrivalTime"]).strftime("%H:%M")
        if "aimedArrivalTime" in item["call"]:
            return parser.parse(item["call"]["aimedArrivalTime"]).strftime("%H:%M")
        return "unavailable"

    def get_line_icon(self, line_no):
        if line_no in ("1", "3"):
            return "mdi:tram"
        return "mdi:bus"

    def get_station_name(self):
        if len(self._station_name) == 0:
            self._station_name = self._stops[self._station]
        return self._station_name

    def get_last_update(self):
        return self._last_update

    def get_destination(self, entry):
        if "destinationShortName" in entry:
            return self._stops[entry["destinationShortName"]]
        return ""

    def time_to_station(self, entry, with_destination=True, style="{0}m {1}s"):
        time = self.get_departure_time(entry)
        if time != "unavailable":
            naive = parser.parse(self.get_departure_time(entry)).replace(tzinfo=None)
            local_dt = LOCAL.localize(naive, is_dst=None)
            utc_dt = local_dt.astimezone(pytz.utc)
            next_departure_time = (utc_dt - datetime.now().astimezone(pytz.utc)).seconds
            next_departure_dest = self.get_destination(entry)
            return style.format(
                int(next_departure_time / 60), int(next_departure_time % 60)
            ) + (" to " + next_departure_dest if with_destination else "")
        return "unavailable"
