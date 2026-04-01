"""Constants for the Nysse component."""

from typing import NamedTuple

DOMAIN = "nysse"

PLATFORM_NAME = "Nysse"


class ConfProperty(NamedTuple):
    name: str
    min: int
    max: int
    default: int


class ConfPropertyBool(NamedTuple):
    name: str
    default: bool


CONF_STATION = "station"
CONF_LINES = "lines"
TIMELIMIT = ConfProperty("timelimit", 0, 60, 0)
MAX = ConfProperty("max", 1, 30, 3)
REALTIME = ConfPropertyBool("realtime", True)
UPDATE_INTERVAL = ConfProperty("scan_interval", 30, 300, 30)
DEFAULT_ICON = "mdi:bus-clock"
TRAM_LINES = ["1", "3"]

STOP_URL = "https://data.itsfactory.fi/journeys/api/1/stop-monitoring?stops={0}"
SERVICE_ALERTS_URL = (
    "https://data.itsfactory.fi/journeys/api/1/gtfs-rt/service-alerts/json"
)
GTFS_URL = (
    "https://data.itsfactory.fi/journeys/files/gtfs/latest/extended_gtfs_tampere.zip"
)
