import json
import logging

from .const import LINES_URL, STOP_POINTS_URL
from .network import get

_LOGGER = logging.getLogger(__name__)


async def fetch_stop_points(has_id):
    """Fetch stop point names."""
    if not has_id:
        stations = {}
    else:
        stations = []
    try:
        result = await get(STOP_POINTS_URL)
        if not result:
            _LOGGER.error("Nysse API error: failed to fetch stops: no data received")
            return stations
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
            return dict(sorted(stations.items(), key=lambda item: item[1]))

        return sorted(stations, key=lambda item: item["label"])

    except KeyError as err:
        _LOGGER.error("Nysse API error: failed to fetch stops: %s", err)
        return stations
    except OSError as err:
        _LOGGER.error("Failed to fetch stops: %s", err)
        return stations


async def fetch_lines(stop):
    """Fetch line point names."""
    lines = []
    try:
        lines_url = LINES_URL.format(stop)
        result = await get(lines_url)
        if not result:
            _LOGGER.error("Nysse API error: failed to fetch lines: no data received")
            return
        result = json.loads(result)
        for line in result["body"]:
            lines.append(line["name"])
        return lines

    except KeyError as err:
        _LOGGER.error("Nysse API error: failed to fetch lines: %s", err)
        return []
    except OSError as err:
        _LOGGER.error("Failed to fetch lines: %s", err)
        return []
