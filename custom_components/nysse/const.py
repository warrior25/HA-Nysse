"""Constants for the Nysse component."""

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

STOP_URL = "https://data.itsfactory.fi/journeys/api/1/stop-monitoring?stops={0}"
SERVICE_ALERTS_URL = (
    "https://data.itsfactory.fi/journeys/api/1/gtfs-rt/service-alerts/json"
)
GTFS_URL = (
    "https://data.itsfactory.fi/journeys/files/gtfs/latest/extended_gtfs_tampere.zip"
)
