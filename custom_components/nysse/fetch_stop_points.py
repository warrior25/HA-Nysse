from .network import request
from .const import NYSSE_STOP_POINTS_URL
import logging
import json

_LOGGER = logging.getLogger(__name__)


async def fetch_stop_points(has_id):
    """Fetches stop point names """
    stations = {}
    if len(stations) == 0:
        try:
            result = await request(NYSSE_STOP_POINTS_URL)
            if not result:
                _LOGGER.warning("Could not fetch stop points")
                return
            result = json.loads(result)
            for stop in result["body"]:
                if has_id:
                    stations[stop["shortName"]] = (
                        stop["name"] + " (" + stop["shortName"] + ")"
                    )
                else:
                    stations[stop["shortName"]] = stop["name"]

            stations = dict(sorted(stations.items(), key=lambda item: item[1]))
            return stations

        except OSError:
            _LOGGER.warning(
                "Unknown exception. Check your internet connection"
            )
            return
    return stations
