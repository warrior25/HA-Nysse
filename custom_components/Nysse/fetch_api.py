from .network import get
from .const import NYSSE_STOP_POINTS_URL, NYSSE_LINES_URL
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
        result = await get(NYSSE_STOP_POINTS_URL)
        if not result:
            _LOGGER.error("Could not fetch stop points")
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

    except OSError as err:
        _LOGGER.error("Failed to fetch stops: %s", err)
        return


async def fetch_lines(stop):
    """Fetches stop point names"""
    lines = []
    try:
        lines_url = NYSSE_LINES_URL.format(stop)
        result = await get(lines_url)
        if not result:
            _LOGGER.error("Could not fetch lines points")
            return
        result = json.loads(result)
        for line in result["body"]:
            lines.append(line["name"])
        return lines

    except OSError as err:
        _LOGGER.error("Failed to fetch lines: %s", err)
        return
