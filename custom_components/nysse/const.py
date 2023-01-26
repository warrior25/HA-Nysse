DOMAIN = "nysse"

PLATFORM_NAME = "Nysse"
CONF_STOPS = "stops"

CONF_STATION = "station"
CONF_MAX = "max"
DEFAULT_MAX = 3
DEFAULT_ICON = "mdi:bus-clock"
TRAM_LINES = ["1","3"]

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

NYSSE_STOP_URL = "https://data.itsfactory.fi/journeys/api/1/stop-monitoring?stops={0}"
NYSSE_STOP_POINTS_URL = "http://data.itsfactory.fi/journeys/api/1/stop-points/"
NYSSE_JOURNEYS_URL = "http://data.itsfactory.fi/journeys/api/1/journeys?stopPointId={0}&dayTypes={1}&startIndex={2}"
