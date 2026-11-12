"""Two small helpers for the daemon's webhook events, free of GTK and D-Bus so the tests inject the clock:
ActivityTracker (minutes today with the screen unlocked and the machine awake) and SnapshotSender
(the periodic and change-driven "snapshot" event, rate limited)."""
import json
import logging
import os
import time
from datetime import date, datetime, timedelta

WAKE_JUMP = 60  # s between two ticks that count as a suspend (same as the gate's)
SAVE_EVERY = 60  # s between two writes of the count to `path`


class ActivityTracker:
    """Counts the seconds of today during which the screen was unlocked and the machine awake.
    tick() is called about once a second; set_locked() on lock and unlock. A gap between two ticks of
    more than WAKE_JUMP seconds is a suspend and is not counted. The count starts again at local midnight;
    time before midnight is not carried over. clock() returns a naive local datetime.
    With a `path`, today's count is saved there about once a minute and read back by reset(), so a
    restart of the daemon (or a reboot) keeps the day's minutes."""

    def __init__(self, clock=datetime.now, locked=False, path=None):
        self._clock = clock
        self._path = path
        self._locked = bool(locked)
        self._last = clock()
        self._day = self._last.date()
        self._seconds = 0.0
        self._saved_at = self._last

    def reset(self, locked=False):
        """Daemon start: count from now on, continuing today's saved count if there is one."""
        self._locked = bool(locked)
        self._last = self._clock()
        self._day = self._last.date()
        self._seconds = self._load()
        self._saved_at = self._last

    def _load(self):
        if not self._path:
            return 0.0
        try:
            with open(self._path) as f:
                data = json.load(f)
            if date.fromisoformat(data["day"]) == self._day:
                return max(0.0, float(data["seconds"]))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError) as e:
            logging.warning(f"Could not read the activity count ({e}); starting at 0")
        return 0.0

    def save(self):
        if not self._path:
            return
        self._saved_at = self._last
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"day": self._day.isoformat(), "seconds": round(self._seconds, 1)}, f)
            os.replace(tmp, self._path)
        except OSError as e:
            logging.warning(f"Could not save the activity count ({e})")

    def tick(self):
        now = self._clock()
        last, self._last = self._last, now
        if now <= last:
            return
        is_suspend = (now - last) > timedelta(seconds=WAKE_JUMP)
        if now.date() != self._day:
            self._day = now.date()
            self._seconds = 0.0
            last = max(last, datetime.combine(now.date(), datetime.min.time()))
        if not self._locked and not is_suspend:
            self._seconds += (now - last).total_seconds()
        if (now - self._saved_at).total_seconds() >= SAVE_EVERY:
            self.save()

    def set_locked(self, locked):
        self.tick()  # time up to now still belongs to the old state
        self._locked = bool(locked)

    @property
    def minutes(self):
        self.tick()
        return int(self._seconds // 60)


class SnapshotSender:
    """send(snapshot) when none went out yet, every `interval` s, or when `watched` fields of the
    snapshot changed since the last one sent, but never more often than every `min_gap` s. tick() is
    cheap and may be called every second; it builds the snapshot only every `check_every` s.
    build() returns the dict, send(dict) delivers it (failures are swallowed)."""

    def __init__(self, build, send, clock=time.monotonic, interval=900, min_gap=60, check_every=5,
                 watched=("paused_until", "conference", "today_ml", "coffee_ml")):
        self._build, self._send, self._clock = build, send, clock
        self._interval, self._min_gap, self._check_every = interval, min_gap, check_every
        self._watched = watched
        self._sent_at = None
        self._checked_at = None
        self._sent = None

    def tick(self):
        now = self._clock()
        if self._checked_at is not None and now - self._checked_at < self._check_every:
            return False
        self._checked_at = now
        due = self._sent_at is None or now - self._sent_at >= self._interval
        if not due and now - self._sent_at < self._min_gap:
            return False
        snapshot = self._build()
        key = {k: snapshot.get(k) for k in self._watched}
        if not due and key == self._sent:
            return False
        try:
            self._send(snapshot)
        except Exception:
            return False
        self._sent_at, self._sent = now, key
        return True
