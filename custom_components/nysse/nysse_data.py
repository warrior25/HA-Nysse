from datetime import datetime
from dateutil import parser
import logging
import pytz

from .const import STOPS

_LOGGER = logging.getLogger(__name__)

LOCAL = pytz.timezone("Europe/Helsinki")


class NysseData:
    def __init__(self):
        self._raw_result = []
        self._last_update = None
        self._api_json = []
        self._station_name = ""
        self._station = ""

    def populate(self, json_data, station_no):
        self._station = station_no
        if self._station in json_data["body"]:
            self._raw_result = json_data["body"][self._station]
            self._last_update = LOCAL.localize(datetime.now(), is_dst=None)
            return True
        return False

    def is_data_stale(self, max_items):
        if len(self._raw_result) > 0:
            # check if there are enough already stored to skip a request
            now = datetime.now().timestamp()
            after_now = [
                item
                for item in self._raw_result
                if parser.parse(self.get_departure_time(item)).timestamp() > now
            ]

            if len(after_now) >= max_items:
                self._raw_result = after_now
                return False
        return True

    def sort_data(self, max_items):
        self._api_json = self._raw_result

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
                "line": item["lineRef"],
                "direction": item["directionRef"],
                "departure": self.get_departure_time(item),
                "destination": self.get_destination(item),
                "time": self.time_to_station(item, False, "{0}"),
                "expected": self.get_departure_time(item),
                "icon": self.get_line_icon(item["lineRef"]),
            }

            departures.append(departure)

            if len(self._station_name) == 0:
                self._station_name = STOPS[self._station]

        return departures

    def get_departure_time(self, item):
        if "expectedArrivalTime" in item["call"]:
            return item["call"]["expectedArrivalTime"]
        if "aimedArrivalTime" in item["call"]:
            return item["call"]["aimedArrivalTime"]
        return "unavailable"

    def get_line_icon(self, line_no):
        if line_no in ("1", "3"):
            return "mdi:tram"
        return "mdi:bus"

    def get_station_name(self):
        return self._station_name

    def get_last_update(self):
        return self._last_update

    def get_destination(self, entry):
        if "destinationShortName" in entry:
            return STOPS[entry["destinationShortName"]]
        return ""

    def time_to_station(self, entry, with_destination=True, style="{0}m {1}s"):
        naive = parser.parse(self.get_departure_time(entry)).replace(tzinfo=None)
        local_dt = LOCAL.localize(naive, is_dst=None)
        utc_dt = local_dt.astimezone(pytz.utc)
        next_departure_time = (utc_dt - datetime.now().astimezone(pytz.utc)).seconds
        next_departure_dest = self.get_destination(entry)
        return style.format(
            int(next_departure_time / 60), int(next_departure_time % 60)
        ) + (" to " + next_departure_dest if with_destination else "")
