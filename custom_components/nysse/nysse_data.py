from datetime import datetime
from dateutil import parser
import pytz
import logging

LOCAL = pytz.timezone("Europe/Helsinki")

_LOGGER = logging.getLogger(__name__)

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

    def is_data_stale(self):
        for item in self._api_json:
            if self.get_departure_time(item, True) == "unavailable":
                #_LOGGER.log("Removing unavailable data")
                self._api_json.remove(item)
                break
            if (self.get_departure_time(item, False)) < datetime.now().astimezone(LOCAL):
                #_LOGGER.log("Removing stale data")
                self._api_json.remove(item)
                break
        return True

    def sort_data(self, max_items):
        self._api_json = self._arrival_data[:max_items]
        #_LOGGER.warning("self._journey_data:\n %s", self._journey_data)
        if len(self._api_json) < max_items:
            for i in range(len(self._api_json), max_items):
                self._api_json.append(self._journey_data[i])
        #_LOGGER.info("self._api_json:\n %s", self._api_json)

    def get_state(self):
        if len(self._api_json) > 0:
            depart_time = self.get_departure_time(self._api_json[0], True)
            if depart_time != "unavailable":
                return parser.parse(depart_time).strftime("%H:%M")

    def is_empty(self):
        return len(self._api_json) == 0

    def get_departures(self):
        departures = []
        for item in self._api_json:
            departure = {
                "destination": self.get_destination(item),
                "line": item["lineRef"],
                "departure": self.get_departure_time(item, True),
                "time_to_station": self.time_to_station(item, False, "{0}"),
                "icon": self.get_line_icon(item["lineRef"]),
                "realtime": self.is_realtime(item),
            }
            if departure["time_to_station"] != "unavailable":
                departures.append(departure)

        departures = sorted(departures, key=lambda d: d['time_to_station'])
        return departures

    def is_realtime(self, item):
        if "non-realtime" in item:
            return False
        return True

    def get_departure_time(self, item, stringify):
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
        time = self.get_departure_time(entry, True)
        if time != "unavailable":
            naive = parser.parse(self.get_departure_time(entry, True)).replace(tzinfo=None)
            local_dt = LOCAL.localize(naive, is_dst=None)
            utc_dt = local_dt.astimezone(pytz.utc)
            next_departure_time = (utc_dt - datetime.now().astimezone(pytz.utc)).seconds
            next_departure_dest = self.get_destination(entry)
            return int(style.format(
                int(next_departure_time / 60), int(next_departure_time % 60)
            ) + (" to " + next_departure_dest if with_destination else ""))
        return "unavailable"
