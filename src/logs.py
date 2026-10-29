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


def water_today_ml():
    """Sum of the water logged today, in ml."""
    if not os.path.exists(WATER_LOG_PATH):
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    total = 0
    with open(WATER_LOG_PATH, "r") as file:
        for line in file:
            if not line.startswith(today):
                continue
            # "YYYY-MM-DD HH:MM:SS <ml>" or, in old logs, "YYYY-MM-DD HH:MM:SS"
            parts = line.split()
            if len(parts) == 2:
                total += LEGACY_GLASS_ML
            elif len(parts) == 3 and parts[2].isdigit():
                total += int(parts[2])
    return total
