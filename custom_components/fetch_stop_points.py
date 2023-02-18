from .network import request
from .const import NYSSE_STOP_POINTS_URL
import logging
import json

_LOGGER = logging.getLogger(__name__)


async def fetch_stop_points(has_id):
    """Fetches stop point names"""
    if not has_id:
        stations = {}
    else:
        stations = []
    try:
        result = await request(NYSSE_STOP_POINTS_URL)
        if not result:
            _LOGGER.warning("Could not fetch stop points")
            return
        result = json.loads(result)
        for stop in result["body"]:
            if has_id:
                temp_dict = {}
                temp_dict["label"] = stop["name"] + " (" + stop["shortName"] + ")"
                temp_dict["value"] = stop["shortName"]
                stations.append(temp_dict)
            else:
                stations[stop["shortName"]] = stop["name"]

        if not has_id:
            stations = dict(sorted(stations.items(), key=lambda item: item[1]))
        else:
            stations = sorted(stations, key=lambda item: item["label"])
        return stations

    except OSError:
        _LOGGER.warning("Unknown exception. Check your internet connection")
        return
