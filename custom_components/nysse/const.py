DOMAIN = "nysse"

PLATFORM_NAME = "Nysse"

CONF_STATION = "station"
CONF_TIMELIMIT = "timelimit"
DEFAULT_TIMELIMIT = 0
CONF_MAX = "max"
DEFAULT_MAX = 3
CONF_LINES = "lines"
DEFAULT_ICON = "mdi:bus-clock"
TRAM_LINES = ["1", "3"]

WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

DEFAULT_TIME_ZONE = "Europe/Helsinki"

JOURNEY = "journey"
DEPARTURE = "departure"
AIMED_ARRIVAL_TIME = "aimedArrivalTime"
AIMED_DEPARTURE_TIME = "aimedDepartureTime"
EXPECTED_ARRIVAL_TIME = "expectedArrivalTime"
EXPECTED_DEPARTURE_TIME = "expectedDepartureTime"

STOP_URL = "https://data.itsfactory.fi/journeys/api/1/stop-monitoring?stops={0}"
STOP_POINTS_URL = "http://data.itsfactory.fi/journeys/api/1/stop-points/"
JOURNEYS_URL = "http://data.itsfactory.fi/journeys/api/1/journeys?stopPointId={0}&dayTypes={1}&startIndex={2}"
LINES_URL = "https://data.itsfactory.fi/journeys/api/1/lines?stopPointId={0}"
SERVICE_ALERTS_URL = (
    "https://data.itsfactory.fi/journeys/api/1/gtfs-rt/service-alerts/json"
)
GTFS_URL = (
    "https://data.itsfactory.fi/journeys/files/gtfs/latest/extended_gtfs_tampere.zip"
)
