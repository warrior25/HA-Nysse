import csv
from datetime import UTC, datetime
import logging
import os
import pathlib
import sqlite3
import zipfile

import aiohttp

from .const import DOMAIN, GTFS_URL

_LOGGER = logging.getLogger(__name__)


def _get_data_path():
    return os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )


def _get_dir_path():
    dir_path = os.path.join(_get_data_path(), f"www/{DOMAIN}/")
    pathlib.Path(dir_path).mkdir(parents=True, exist_ok=True)
    return dir_path


def _get_database():
    # Connect to the SQLite database (or create it if it doesn't exist)
    conn = sqlite3.connect(_get_dir_path() + "database.db")
    conn.row_factory = sqlite3.Row

    # Create a cursor object to execute SQL queries
    cursor = conn.cursor()
    return conn, cursor


async def _fetch_gtfs():
    try:
        path = _get_dir_path()
        filename = "extended_gtfs_tampere.zip"
        timestamp = _get_file_modified_time(path + filename)
        if timestamp != datetime(1970, 1, 1) or datetime.now().minute != 0:
            _LOGGER.debug("Skipped fetching GTFS data")
            return  # Skip fetching if the file exists or it's not the top of the hour

        _LOGGER.debug("Fetching GTFS data")
        timeout = aiohttp.ClientTimeout(total=30)
        async with (
            aiohttp.ClientSession(timeout=timeout) as session,
            session.get(GTFS_URL, headers={"If-Modified-Since": timestamp}) as response,
        ):
            if response.status == 200:
                _LOGGER.info("Response OK")
                with open(path + filename, "wb") as f:
                    f.write(await response.read())
                with zipfile.ZipFile(path + filename, "r") as zip_ref:
                    zip_ref.extractall(path)
                await _read_csv_to_db()
            elif response.status == 304:
                _LOGGER.debug(
                    "%s has not received updates: %s", filename, response.status
                )
            else:
                _LOGGER.error("Error fetching GTFS data: Status %s", response.status)
    except aiohttp.ClientError as err:
        _LOGGER.error("Error fetching GTFS data: %s", err)


async def _read_csv_to_db():
    conn, cursor = _get_database()

    # Stops
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS stops (stop_id TEXT PRIMARY KEY, stop_name TEXT, stop_lat TEXT, stop_lon TEXT)"
    )
    stops = _parse_csv_file(_get_dir_path() + "stops.txt")
    to_db = [
        (i["stop_id"], i["stop_name"], i["stop_lat"], i["stop_lon"]) for i in stops
    ]
    cursor.executemany(
        "INSERT OR REPLACE INTO stops (stop_id, stop_name, stop_lat, stop_lon) VALUES (?, ?, ?, ?)",
        to_db,
    )

    # Routes
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS trips (trip_id TEXT PRIMARY KEY, route_id TEXT, service_id TEXT, trip_headsign TEXT, direction_id TEXT)"
    )
    trips = _parse_csv_file(_get_dir_path() + "trips.txt")
    to_db = [
        (
            i["trip_id"],
            i["route_id"],
            i["service_id"],
            i["trip_headsign"],
            i["direction_id"],
        )
        for i in trips
    ]
    cursor.executemany(
        "INSERT OR REPLACE INTO trips (trip_id, route_id, service_id, trip_headsign, direction_id) VALUES (?, ?, ?, ?, ?)",
        to_db,
    )

    # Calendar
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS calendar (service_id TEXT PRIMARY KEY, monday TEXT, tuesday TEXT, wednesday TEXT, thursday TEXT, friday TEXT, saturday TEXT, sunday TEXT)"
    )
    calendar = _parse_csv_file(_get_dir_path() + "calendar.txt")
    to_db = [
        (
            i["service_id"],
            i["monday"],
            i["tuesday"],
            i["wednesday"],
            i["thursday"],
            i["friday"],
            i["saturday"],
            i["sunday"],
        )
        for i in calendar
    ]
    cursor.executemany(
        "INSERT OR REPLACE INTO calendar (service_id, monday, tuesday, wednesday, thursday, friday, saturday, sunday) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        to_db,
    )

    # Stop times
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS stop_times (trip_id TEXT, arrival_time TIME, departure_time TIME, stop_id TEXT, stop_sequence TEXT, PRIMARY KEY(trip_id, arrival_time))"
    )
    stop_times = _parse_csv_file(_get_dir_path() + "stop_times.txt")
    to_db = [
        (
            i["trip_id"],
            i["arrival_time"],
            i["departure_time"],
            i["stop_id"],
            i["stop_sequence"],
        )
        for i in stop_times
    ]
    to_db.sort(key=lambda x: x[2])  # Sort by departure_time
    cursor.executemany(
        "INSERT OR REPLACE INTO stop_times (trip_id, arrival_time, departure_time, stop_id, stop_sequence) VALUES (?, ?, ?, ?, ?)",
        to_db,
    )

    conn.commit()
    conn.close()


def _format_datetime(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def _get_file_modified_time(file_path):
    dt = datetime(1970, 1, 1)
    if os.path.isfile(file_path):
        dt = datetime.fromtimestamp(os.path.getmtime(file_path), tz=UTC)
    return _format_datetime(dt)


def _parse_csv_file(file_path):
    with open(file_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        data = [row.copy() for row in reader]
    return data


async def get_stops():
    """Get all the stops.

    Returns:
        list: A list of all stops.

    """
    await _fetch_gtfs()
    conn, cursor = _get_database()
    cursor.execute("SELECT * FROM stops")
    stops = cursor.fetchall()
    conn.close()
    return stops


async def get_route_ids(stop_id):
    """Get the route IDs for a given stop ID.

    Args:
        stop_id (str): The ID of the stop.

    Returns:
        list: A list of route IDs associated with the stop.

    """

    await _fetch_gtfs()
    conn, cursor = _get_database()
    cursor.execute(
        "SELECT DISTINCT route_id FROM trips WHERE trip_id IN (SELECT trip_id FROM stop_times WHERE stop_id = ?)",
        (stop_id,),
    )
    route_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return route_ids


async def get_stop_times(stop_id, route_ids, amount, from_time):
    """Get the stop times for a given stop ID, route IDs, and amount.

    Args:
        stop_id (str): The ID of the stop.
        route_ids (list): A list of route IDs.
        amount (int): The maximum number of stop times to retrieve.
        from_time (datetime): The starting time to filter the stop times.

    Returns:
        list: A list of stop times.

    """
    await _fetch_gtfs()
    conn, cursor = _get_database()
    today = datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.strptime(today, "%Y-%m-%d").strftime("%A").lower()
    if from_time:
        cursor.execute(
            f"SELECT route_id, trip_headsign, departure_time FROM stop_times JOIN trips ON stop_times.trip_id = trips.trip_id JOIN calendar ON trips.service_id = calendar.service_id WHERE stop_id = ? AND trips.route_id IN ({','.join(['?']*len(route_ids))}) AND calendar.{weekday} = '1' AND departure_time > ? LIMIT ?",
            [stop_id, *route_ids, from_time.strftime("%H:%M:%S"), amount],
        )
    else:
        cursor.execute(
            f"SELECT route_id, trip_headsign, departure_time FROM stop_times JOIN trips ON stop_times.trip_id = trips.trip_id JOIN calendar ON trips.service_id = calendar.service_id WHERE stop_id = ? AND trips.route_id IN ({','.join(['?']*len(route_ids))}) AND calendar.{weekday} = '1' LIMIT ?",
            [stop_id, *route_ids, amount],
        )
    stop_times = cursor.fetchall()
    conn.close()
    return stop_times
