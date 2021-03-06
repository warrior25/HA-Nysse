from .network import request
from .const import NYSSE_STOP_POINTS_URL
import logging
import json

_LOGGER = logging.getLogger(__name__)


async def fetch_stop_points(has_id):
    stations = {}
    if len(stations) == 0:
        try:
            result = await request(NYSSE_STOP_POINTS_URL)

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
                "Can't fetch stop point data from %s", NYSSE_STOP_POINTS_URL
            )
            return
    return stations
