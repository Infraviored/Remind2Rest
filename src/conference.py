"""Whether a video conference is running, from what the machine itself shows: a screen share, an open
microphone or camera, a meeting app, GNOME's Do Not Disturb. Polled every POLL_INTERVAL seconds in its
own thread, so a slow pw-dump never holds up the scheduler tick; the gate only reads the result.

Each signal can be switched off in config["conference"]["signals"]. The conference is on while any
enabled signal is, and off once none has been for end_grace_seconds (a call that drops for a moment
does not end it). Each change of state is logged and, if conference.webhook_url is set, POSTed there.
"""
import copy
import json
import logging
import os
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime


POLL_INTERVAL = 3       # s between two polls
TOOL_TIMEOUT = 2        # s a pw-dump / gsettings call may take
EXTENSION_FRESH = 15    # s a SCREENSHARE report of the GNOME extension stays valid (it resends every 5 s)
WEBHOOK_TIMEOUT = 10    # s per webhook attempt
WEBHOOK_ATTEMPTS = 3

SIGNALS = ("screen_share", "microphone", "camera", "processes", "do_not_disturb")

DEFAULTS = {
    "signals": {"screen_share": True, "microphone": True, "camera": True, "processes": False,
                "do_not_disturb": True},
    "ignore_apps": ["VibeVoice"],
    "processes": ["teams", "teams-for-linux", "zoom"],
    "end_grace_seconds": 60,
    "webhook_url": "",
}

# Capture streams that only meter the level (volume sliders, pavucontrol) are not a microphone in use.
METER_BINARIES = {"gnome-shell", "pavucontrol", "pavucontrol-qt", "gnome-control-center"}
METER_APP_IDS = {"org.pulseaudio.pavucontrol", "org.gnome.Settings"}
# Processes that hold /dev/video* open for others; the PipeWire node state covers them.
VIDEO_BROKERS = {"pipewire", "wireplumber", "pipewire-media-", "pipewire-media-session"}


def fill_defaults(config):
    """Add config["conference"] and its missing keys, for configs from before conference detection."""
    conference = config.get("conference")
    if not isinstance(conference, dict):
        conference = {}
        config["conference"] = conference
    for key, value in DEFAULTS.items():
        if key not in conference or conference[key] in (None, ""):
            conference[key] = copy.deepcopy(value)
    signals = conference.setdefault("signals", {})
    if not isinstance(signals, dict):
        signals = {}
        conference["signals"] = signals
    for name, on in DEFAULTS["signals"].items():
        signals.setdefault(name, on)
    try:
        val = conference.get("end_grace_seconds")
        conference["end_grace_seconds"] = max(0, int(val if val not in (None, "") else 60))
    except (ValueError, TypeError):
        conference["end_grace_seconds"] = 60
    return config


# ---- Signals. Each returns a list of what is active (app or node names); empty means off. ----

def _truthy(value):
    return value is True or str(value).lower() == "true"


def _app_names(props):
    return {str(props.get(k, "")).lower() for k in ("application.name", "application.process.binary")} - {""}


def pipewire_signals(nodes, ignore_apps=()):
    """Screen share, microphone and camera from pw-dump's JSON (a list of objects)."""
    ignore = {name.lower() for name in ignore_apps}
    found = {"screen_share": [], "microphone": [], "camera": []}
    for obj in nodes:
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        info = obj.get("info") or {}
        props = info.get("props") or {}
        state = info.get("state")
        media_class = props.get("media.class", "")
        node_name = props.get("node.name", "")
        app = props.get("application.name") or props.get("application.process.binary") or node_name

        if node_name.startswith("v4l2_input.") or props.get("device.api") in ("v4l2", "libcamera"):
            # A real camera. Suspended while nobody watches it, running while an app (or the portal) does.
            if media_class == "Video/Source" and state == "running":
                found["camera"].append(props.get("node.description") or node_name)
        elif media_class == "Video/Source" or (media_class.startswith("Stream/") and "Video" in media_class):
            # Mutter names its screencast streams meta-screen-cast-src (screen share via the portal,
            # and GNOME's own screen recorder). The portal or gnome-shell may also show up as the app.
            names = _app_names(props) | {node_name.lower()}
            if (node_name.startswith("meta-screen-cast") or "gnome-shell" in names
                    or any("xdg-desktop-portal" in n for n in names)):
                if state != "error":
                    found["screen_share"].append(app)
        elif media_class == "Stream/Input/Audio" and state == "running":
            target = str(props.get("target.object", "") or props.get("node.target", ""))
            if _truthy(props.get("stream.capture.sink")) or target.endswith(".monitor"):
                continue  # records what the speakers play, not the microphone
            if (str(props.get("application.process.binary", "")).lower() in METER_BINARIES
                    or str(props.get("application.id", "")).lower() in METER_APP_IDS
                    or str(props.get("media.name", "")).lower().startswith("peak detect")):
                continue
            if _app_names(props) & ignore:
                continue
            found["microphone"].append(app)
    return {key: sorted(set(names)) for key, names in found.items()}


def _comm(proc_root, pid):
    try:
        with open(os.path.join(proc_root, pid, "comm")) as f:
            return f.read().strip()
    except OSError:
        return None


def video_device_users(proc_root="/proc"):
    """Names of processes (other than PipeWire) with a /dev/video* open. Chrome and Teams open the
    camera directly, past PipeWire. Processes of other users are not readable and are skipped."""
    users = set()
    for pid in os.listdir(proc_root):
        if not pid.isdigit():
            continue
        fd_dir = os.path.join(proc_root, pid, "fd")
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(os.path.join(fd_dir, fd))
            except OSError:
                continue
            if target.startswith("/dev/video"):
                comm = _comm(proc_root, pid)
                if comm and comm not in VIDEO_BROKERS:
                    users.add(comm)
                break
    return sorted(users)


def running_processes(names, proc_root="/proc"):
    """Which of `names` run, matched case-insensitively against /proc/<pid>/comm (15 characters)."""
    wanted = {name.lower()[:15]: name for name in names if name}
    found = set()
    for pid in os.listdir(proc_root):
        if pid.isdigit():
            comm = _comm(proc_root, pid)
            if comm and comm.lower() in wanted:
                found.add(wanted[comm.lower()])
    return sorted(found)


def dnd_active():
    """GNOME's Do Not Disturb: notification banners switched off."""
    out = subprocess.run(["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"],
                         capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=True)
    return out.stdout.strip() == "false"


def read_pipewire():
    out = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=True)
    return json.loads(out.stdout)


# ---- Webhook ----

def redact(url):
    """scheme://host/… of a webhook URL: its path holds the secret (a Home Assistant webhook id)."""
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}/…"


def format_error(e):
    """Exception class plus HTTP status/reason only, never arbitrary exception strings that could contain the URL."""
    if isinstance(e, urllib.error.HTTPError):
        return f"{type(e).__name__} {e.code} {e.reason}"
    if isinstance(e, urllib.error.URLError):
        if hasattr(e, "reason") and isinstance(e.reason, Exception):
            return f"{type(e).__name__} ({type(e.reason).__name__})"
        return f"{type(e).__name__}"
    return f"{type(e).__name__}"


def post_webhook(url, state, reasons):
    """POST one state change; raises on failure. Used directly by the settings window's test button."""
    body = json.dumps({"state": state, "reasons": list(reasons), "host": socket.gethostname(),
                       "time": datetime.now().astimezone().isoformat(timespec="seconds")}).encode()
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=WEBHOOK_TIMEOUT) as response:
        return response.status


class WebhookTask:
    def __init__(self):
        self._done = threading.Event()

    def set_done(self):
        self._done.set()

    def join(self, timeout=None):
        return self._done.wait(timeout)


class WebhookDispatcher:
    """Serializes webhook dispatches through a single worker thread. If a newer state arrives while
    an older state is waiting to retry, the pending retries of the older state are superseded."""

    def __init__(self, post=post_webhook, attempts=WEBHOOK_ATTEMPTS, sleep=time.sleep):
        self._post = post
        self._attempts = attempts
        self._sleep = sleep
        self._cond = threading.Condition()
        self._queue = []
        self._latest_generation = 0
        self._thread = None
        self._stop = False

    def send(self, url, state, reasons, attempts=None, sleep=None):
        task = WebhookTask()
        attempts = self._attempts if attempts is None else attempts
        sleep = self._sleep if sleep is None else sleep
        with self._cond:
            self._latest_generation += 1
            gen = self._latest_generation
            self._queue.append((url, state, reasons, gen, attempts, sleep, task))
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="conference-webhook", daemon=True)
                self._thread.start()
            self._cond.notify_all()
        return task

    def stop(self):
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join()

    def _run(self):
        while True:
            with self._cond:
                while not self._queue and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                url, state, reasons, gen, attempts, sleep, task = self._queue.pop(0)

            try:
                for attempt in range(1, attempts + 1):
                    with self._cond:
                        if self._latest_generation > gen:
                            break
                    try:
                        self._post(url, state, reasons)
                        logging.info(f"Conference webhook {redact(url)} sent: {state}")
                        break
                    except Exception as e:
                        logging.warning(f"Conference webhook {redact(url)} attempt {attempt}/{attempts} failed: "
                                        f"{format_error(e)}")
                        if attempt < attempts:
                            delay = 2 ** attempt
                            with self._cond:
                                if self._latest_generation > gen:
                                    break
                                if sleep != time.sleep:
                                    sleep(delay)
                                else:
                                    self._cond.wait(timeout=delay)
                                if self._latest_generation > gen:
                                    break
            finally:
                task.set_done()


_webhook_dispatcher = WebhookDispatcher()


def send_webhook(url, state, reasons, attempts=WEBHOOK_ATTEMPTS, sleep=time.sleep):
    """post_webhook in a serialized background worker thread, retried with backoff (2 s, 4 s).
    A newer state supersedes pending retries of an older one; failures are only logged."""
    return _webhook_dispatcher.send(url, state, reasons, attempts=attempts, sleep=sleep)


# ---- Detector ----

class ConferenceDetector:
    """Polls the signals and keeps the conference state. poll() does the work; start() runs it in a
    thread. on_change(active, reasons) is called on each change, and once after the first poll so a
    webhook receiver learns the state after a reboot.

    The probes are injectable for the tests: read_pipewire() -> pw-dump JSON, video_users() -> process
    names, processes(names) -> running names, dnd() -> bool.
    """

    def __init__(self, settings=None, clock=time.monotonic, on_change=None, read_pipewire=read_pipewire,
                 video_users=video_device_users, processes=running_processes, dnd=dnd_active):
        self._settings = fill_defaults({"conference": copy.deepcopy(settings or {})})["conference"]
        self._clock = clock
        self._on_change = on_change or self._notify
        self._read_pipewire = read_pipewire
        self._video_users = video_users
        self._processes = processes
        self._dnd = dnd
        self._mutex = threading.Lock()
        self._signals = {name: [] for name in SIGNALS}
        self._active = False
        self._reasons = []
        self._polled = False
        self._last_signal_at = None
        self._extension = None  # (screen sharing?, monotonic time of the report)
        self._failed = set()   # probes whose failure was logged already
        self._thread = None
        self._stop = threading.Event()

    def configure(self, settings):
        with self._mutex:
            self._settings = fill_defaults({"conference": copy.deepcopy(settings or {})})["conference"]

    @property
    def active(self):
        with self._mutex:
            return self._active

    def report_screenshare(self, sharing):
        """The GNOME extension's view of screen sharing (SCREENSHARE on|off); combined with pw-dump."""
        with self._mutex:
            self._extension = (bool(sharing), self._clock())

    def state(self):
        """Everything for the CONFERENCE command and STATUS."""
        with self._mutex:
            enabled = self._settings["signals"]
            ext_active = self._extension_fresh() and self._extension[0]
            return {
                "active": self._active,
                "reasons": list(self._reasons),
                "signals": {name: {"enabled": bool(enabled.get(name)), "active": bool(self._signals[name]),
                                   "sources": list(self._signals[name])} for name in SIGNALS},
                "screen_share_source": "extension" if ext_active or (self._extension_fresh() and not self._signals["screen_share"]) else "pipewire",
                "end_grace_seconds": self._settings["end_grace_seconds"],
            }

    def _extension_fresh(self):
        return self._extension is not None and self._clock() - self._extension[1] < EXTENSION_FRESH

    def _probe(self, name, probe, *args):
        """Runs one probe; a failure makes the signal inactive and is logged once until it works again."""
        try:
            result = probe(*args)
            if name in self._failed:
                self._failed.discard(name)
                logging.info(f"Conference probe {name} works again")
            return result
        except Exception as e:
            if name not in self._failed:
                self._failed.add(name)
                hint = " (not installed?)" if isinstance(e, FileNotFoundError) else ""
                logging.warning(f"Conference probe {name} failed{hint}: {e}; that signal counts as off")
            return None

    def _read_signals(self, settings):
        enabled = settings["signals"]
        signals = {name: [] for name in SIGNALS}
        if enabled.get("microphone") or enabled.get("camera") or enabled.get("screen_share"):
            nodes = self._probe("pw-dump", self._read_pipewire)
            if nodes is not None:
                signals.update(pipewire_signals(nodes, settings["ignore_apps"]))
        with self._mutex:
            extension = self._extension if self._extension_fresh() else None
        if extension is not None and extension[0]:
            signals["screen_share"] = sorted(set(signals["screen_share"]) | {"GNOME Shell"})
        if enabled.get("camera"):
            users = self._probe("/proc fd scan", self._video_users) or []
            signals["camera"] = sorted(set(signals["camera"]) | set(users))
        if enabled.get("processes"):
            signals["processes"] = self._probe("processes", self._processes, settings["processes"]) or []
        if enabled.get("do_not_disturb"):
            signals["do_not_disturb"] = ["Do Not Disturb"] if self._probe("do not disturb", self._dnd) else []
        return {name: (found if enabled.get(name) else []) for name, found in signals.items()}

    def poll(self):
        with self._mutex:
            settings = copy.deepcopy(self._settings)
        signals = self._read_signals(settings)
        now = self._clock()
        reasons = [name for name in SIGNALS if signals[name]]
        try:
            val = settings.get("end_grace_seconds")
            end_grace = max(0, int(val if val not in (None, "") else 60))
        except (ValueError, TypeError):
            end_grace = 60

        with self._mutex:
            self._signals = signals
            first = not self._polled
            self._polled = True
            was_active = self._active
            if reasons:
                self._last_signal_at = now
                self._active = True
                self._reasons = reasons
            elif self._active and now - self._last_signal_at >= end_grace:
                self._active = False
                self._reasons = []
            active, current = self._active, list(self._reasons)

        if active and not was_active:
            details = ", ".join(f"{name} ({', '.join(signals[name])})" for name in reasons)
            logging.info(f"Conference started: {details}")
        elif was_active and not active:
            logging.info(f"Conference ended: no signal for {end_grace} s")
        elif first:
            logging.info("Conference detection started: no conference")
        if first or active != was_active:
            self._on_change(active, current)

    def _notify(self, active, reasons):
        with self._mutex:
            url = self._settings.get("webhook_url", "").strip()
        if url:
            send_webhook(url, "on" if active else "off", reasons)

    def start(self):
        if self._thread is not None:
            return

        def run():
            while not self._stop.is_set():
                try:
                    self.poll()
                except Exception as e:
                    logging.error(f"Conference poll failed: {e}")
                self._stop.wait(POLL_INTERVAL)

        self._thread = threading.Thread(target=run, name="conference-detector", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()


detector = ConferenceDetector()
