"""Reading the posture and water logs. Shared by the reminder window (overlay.py) and the daemon's
STATUS (scheduler.py), so it must not import pywebview."""
import os
from datetime import datetime, timedelta

from src.config import RATINGS_FILE_PATH, WATER_LOG_PATH

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def read_ratings(days):
    """Posture ratings of the last `days` days, oldest first."""
    since = datetime.now() - timedelta(days=days)
    ratings = []
    if not os.path.exists(RATINGS_FILE_PATH):
        return ratings
    with open(RATINGS_FILE_PATH, "r") as file:
        for line in file:
            try:
                time_str, rating_str = line.strip().split(" - Rating: ")
                timestamp = datetime.strptime(time_str, TIME_FORMAT)
                rating = int(rating_str)
            except ValueError:
                continue
            if timestamp >= since:
                ratings.append((timestamp, rating))
    ratings.sort()
    return [{"time": t.strftime(TIME_FORMAT), "rating": r} for t, r in ratings]


# Lines before the switch to amounts hold only a timestamp; they count as one 250 ml glass.
LEGACY_GLASS_ML = 250
MAX_WATER_ML = 2000

DRINKS = ("water", "coffee")

_water_cache = {
    "mtime_ns": None,
    "size": None,
    "day": None,
    "totals": None,
}


def drinks_today_ml():
    """Today's logged drinks in ml, per kind: {"water": ..., "coffee": ...}."""
    empty = dict.fromkeys(DRINKS, 0)
    try:
        stat = os.stat(WATER_LOG_PATH)
    except OSError:
        _water_cache.update(mtime_ns=None, size=None, day=None, totals=None)
        return empty

    today = datetime.now().strftime("%Y-%m-%d")
    if (
        _water_cache["day"] == today
        and _water_cache["mtime_ns"] == stat.st_mtime_ns
        and _water_cache["size"] == stat.st_size
    ):
        return dict(_water_cache["totals"])

    totals = dict(empty)
    try:
        with open(WATER_LOG_PATH, "r") as file:
            for line in file:
                if not line.startswith(today):
                    continue
                # "YYYY-MM-DD HH:MM:SS <ml> [coffee]" or, in old logs, "YYYY-MM-DD HH:MM:SS"
                parts = line.split()
                if len(parts) == 2:
                    totals["water"] += LEGACY_GLASS_ML
                elif len(parts) in (3, 4) and parts[2].isdigit():
                    kind = parts[3] if len(parts) == 4 else "water"
                    if kind in totals:
                        totals[kind] += int(parts[2])
    except OSError:
        return empty

    _water_cache.update(mtime_ns=stat.st_mtime_ns, size=stat.st_size, day=today, totals=totals)
    return dict(totals)


def water_today_ml():
    """Everything drunk today in ml (water and coffee): what counts towards the daily goal."""
    return sum(drinks_today_ml().values())
