"""Whether a video conference is running, from what the machine itself shows: a screen share, an open
microphone or camera, a meeting app, GNOME's Do Not Disturb. Polled every POLL_INTERVAL seconds in its
own thread, so a slow pw-dump never holds up the scheduler tick; the gate only reads the result.

On Windows the signals come from elsewhere (see "Windows probes" below): camera and microphone from the
registry's CapabilityAccessManager consent store, processes from tasklist, Do Not Disturb (best effort)
from the notification settings. Screen sharing has no reliable source there and stays off. None of the
Linux tools (pw-dump, gsettings, /proc) is run on Windows.

Each signal can be switched off in config["conference"]["signals"]. The conference is on while any
enabled signal is, and off once none has been for end_grace_seconds (a call that drops for a moment
does not end it). Each change of state is logged and, if conference.webhook_url is set, POSTed there.
"""
import copy
import csv
import glob
import io
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

from src.config import IS_WINDOWS


POLL_INTERVAL = 3       # s between two polls
TOOL_TIMEOUT = 2        # s a pw-dump / gsettings call may take
EXTENSION_FRESH = 15    # s a SCREENSHARE report of the GNOME extension stays valid (it resends every 5 s)
WEBHOOK_TIMEOUT = 10    # s per webhook attempt
WEBHOOK_ATTEMPTS = 3

CREATE_NO_WINDOW = 0x08000000  # subprocess.CREATE_NO_WINDOW, which only exists on Windows builds

DEFAULTS = {
    "signals": {"screen_share": True, "microphone": True, "camera": True, "processes": False,
                "do_not_disturb": True},
    "ignore_apps": ["VibeVoice"],
    # The microphone alone is no call (dictation, voice tools); it counts only while an app of
    # "processes" runs, whether or not the processes signal itself is on.
    "microphone_needs_app": True,
    # On Windows matched without ".exe": teams = classic Teams.exe, ms-teams = new Teams, zoom = Zoom.exe.
    "processes": ["teams", "teams-for-linux", "ms-teams", "zoom"],
    "end_grace_seconds": 60,
    "webhook_url": "",
}
SIGNALS = tuple(DEFAULTS["signals"])

# Capture streams that only meter the level (volume sliders, pavucontrol) are not a microphone in use.
METER_BINARIES = {"gnome-shell", "pavucontrol", "pavucontrol-qt", "gnome-control-center"}
METER_APP_IDS = {"org.pulseaudio.pavucontrol", "org.gnome.Settings"}
# Processes that hold /dev/video* open for others; the PipeWire node state covers them.
VIDEO_BROKERS = {"pipewire", "wireplumber", "pipewire-media-", "pipewire-media-session"}


def normalize(conf):
    """conf (config["conference"]) with every key of DEFAULTS present and of its type, in place; a
    missing, empty or unusable value gets the default. Returns a new dict if conf is no dict."""
    if not isinstance(conf, dict):
        conf = {}
    signals = conf.get("signals")
    if not isinstance(signals, dict):
        signals = {}
    conf["signals"] = {**signals, **{name: bool(signals.get(name, on)) for name, on in DEFAULTS["signals"].items()}}
    for key in ("ignore_apps", "processes"):
        value = conf.get(key)
        conf[key] = [str(x) for x in value if x] if isinstance(value, list) else list(DEFAULTS[key])
    value = conf.get("webhook_url")
    conf["webhook_url"] = value if isinstance(value, str) else str(value or "")
    value = conf.get("microphone_needs_app")
    conf["microphone_needs_app"] = DEFAULTS["microphone_needs_app"] if value in (None, "") else bool(value)
    try:
        value = conf.get("end_grace_seconds")
        conf["end_grace_seconds"] = max(0, int(DEFAULTS["end_grace_seconds"] if value in (None, "") else value))
    except (ValueError, TypeError):
        conf["end_grace_seconds"] = DEFAULTS["end_grace_seconds"]
    return conf


def fill_defaults(config):
    """Add config["conference"] and its missing keys, for configs from before conference detection."""
    config["conference"] = normalize(config.get("conference"))
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


def proc_comms(proc_root="/proc"):
    """{pid: comm} of every process, from one pass over /proc; comm is cut at 15 characters."""
    comms = {}
    for pid in os.listdir(proc_root):
        if pid.isdigit():
            comm = _comm(proc_root, pid)
            if comm:
                comms[pid] = comm
    return comms


def video_device_users(proc_root="/proc", comms=None, dev_root="/dev"):
    """Names of processes (other than PipeWire) with a /dev/video* open. Chrome and Teams open the
    camera directly, past PipeWire. Processes of other users are not readable and are skipped.
    comms is proc_comms() if the caller has it already; without a /dev/video* nothing is scanned."""
    if not glob.glob(os.path.join(dev_root, "video*")):
        return []
    users = set()
    for pid, comm in (proc_comms(proc_root) if comms is None else comms).items():
        if comm in VIDEO_BROKERS:
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
                users.add(comm)
                break
    return sorted(users)


def running_processes(names, proc_root="/proc", comms=None):
    """Which of `names` run, matched case-insensitively against /proc/<pid>/comm (15 characters).
    comms is proc_comms() if the caller has it already."""
    wanted = {name.lower()[:15]: name for name in names if name}
    running = {comm.lower() for comm in (proc_comms(proc_root) if comms is None else comms).values()}
    return sorted(wanted[comm] for comm in wanted.keys() & running)


def dnd_active():
    """GNOME's Do Not Disturb: notification banners switched off."""
    out = subprocess.run(["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"],
                         capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=True)
    return out.stdout.strip() == "false"


def read_pipewire():
    out = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=True)
    return json.loads(out.stdout)


# ---- Windows probes. The registry is read through a small reader, so the tests can fake it. ----

CONSENT_STORE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
NOTIFICATION_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
# Microphone or camera use that is no call: the Settings app's level meter and camera preview.
WINDOWS_METER_APPS = {"windows.immersivecontrolpanel"}


class WindowsRegistry:
    """Read-only HKEY_CURRENT_USER access: subkeys(path) -> names ([] if the key is missing),
    values(path, *names) -> data of each (None if missing), value(path, name) -> the data of one.
    winreg is imported here, so only on Windows."""

    def __init__(self):
        import winreg
        self._winreg = winreg

    def subkeys(self, path):
        winreg = self._winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return []
        names = []
        with key:
            while True:
                try:
                    names.append(winreg.EnumKey(key, len(names)))
                except OSError:  # no more subkeys
                    return names

    def values(self, path, *names):
        winreg = self._winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return (None,) * len(names)
        found = []
        with key:
            for name in names:
                try:
                    found.append(winreg.QueryValueEx(key, name)[0])
                except OSError:
                    found.append(None)
        return tuple(found)

    def value(self, path, name):
        return self.values(path, name)[0]


def _strip_exe(name):
    name = name.lower()
    return name[:-4] if name.endswith(".exe") else name


def windows_app_name(key, packaged):
    """A consent store subkey as a readable name: "C:#Program Files#Google#Chrome#Application#chrome.exe"
    (desktop app, its path with # for \\) -> "chrome.exe"; package family "MSTeams_8wekyb3d8bbwe" -> "MSTeams"."""
    if packaged:
        return key.rpartition("_")[0] or key
    return key.rpartition("#")[2] or key


def consent_store_users(device, ignore_apps=(), registry=None):
    """Apps using the camera (device "webcam") or the microphone ("microphone") right now, from
    HKCU\\...\\ConsentStore\\<device>: a subkey per packaged app, and a subkey per desktop app under
    NonPackaged. An app uses the device while its LastUsedTimeStop is 0 and LastUsedTimeStart is set.
    HKCU is enough: it records every app the logged-in user runs. HKLM holds the machine-wide
    allow/deny switch and use by services or other accounts, which is no call of this user."""
    registry = registry or WindowsRegistry()
    ignore = {_strip_exe(name) for name in ignore_apps}
    base = f"{CONSENT_STORE}\\{device}"
    entries = [(f"{base}\\{key}", key, True) for key in registry.subkeys(base) if key != "NonPackaged"]
    entries += [(f"{base}\\NonPackaged\\{key}", key, False) for key in registry.subkeys(f"{base}\\NonPackaged")]
    users = set()
    for path, key, packaged in entries:
        try:
            start, stop = registry.values(path, "LastUsedTimeStart", "LastUsedTimeStop")
        except OSError:
            continue
        if not (isinstance(start, int) and start > 0 and stop == 0):
            continue
        name = windows_app_name(key, packaged)
        if {_strip_exe(name), key.lower()} & (ignore | WINDOWS_METER_APPS):
            continue
        users.add(name)
    return sorted(users)


def windows_dnd_active(registry=None):
    """Best effort: Windows has no stable API for Focus Assist / Do Not Disturb. Windows 11 writes
    NOC_GLOBAL_SETTING_TOASTS_ENABLED = 0 while notifications are switched off; missing counts as off."""
    registry = registry or WindowsRegistry()
    return registry.value(NOTIFICATION_SETTINGS, "NOC_GLOBAL_SETTING_TOASTS_ENABLED") == 0


def run_tasklist():
    """tasklist's CSV, without a console window flashing up."""
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, errors="replace",
                         timeout=TOOL_TIMEOUT, check=True, creationflags=CREATE_NO_WINDOW)
    return out.stdout


def parse_tasklist(text):
    """Image names from `tasklist /FO CSV /NH` lines like "Teams.exe","1234","Console","1","200,000 K"."""
    return {row[0] for row in csv.reader(io.StringIO(text)) if len(row) >= 2 and row[0]}


def windows_running_processes(names, tasklist=run_tasklist):
    """Which of `names` run, matched case-insensitively and with or without ".exe"."""
    wanted = {_strip_exe(name): name for name in names if name}
    running = {_strip_exe(image) for image in parse_tasklist(tasklist())}
    return sorted(wanted[name] for name in wanted.keys() & running)


# ---- Webhook ----

def redact(url):
    """scheme://host/… of a webhook URL: its path holds the secret (a Home Assistant webhook id)."""
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}/…"


def format_error(e):
    """Exception class plus HTTP status/reason only, never arbitrary exception strings that could contain the URL."""
    if isinstance(e, urllib.error.HTTPError):
        return f"{type(e).__name__} {e.code} {e.reason}"
    if isinstance(e, urllib.error.URLError) and isinstance(e.reason, Exception):
        return f"{type(e).__name__} ({type(e.reason).__name__})"
    return type(e).__name__


def post_webhook(url, state, reasons):
    """POST one state change; raises on failure. Used directly by the settings window's test button."""
    body = json.dumps({"state": state, "reasons": list(reasons), "host": socket.gethostname(),
                       "time": datetime.now().astimezone().isoformat(timespec="seconds")}).encode()
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=WEBHOOK_TIMEOUT) as response:
        return response.status


class WebhookDispatcher:
    """post_webhook in one background worker thread, retried with backoff (backoff, 2 * backoff, ...
    seconds). Only the latest state counts: a newer one replaces a state not sent yet and cuts the
    retries of the one being sent short. Failures are only logged."""

    def __init__(self, post=post_webhook, attempts=WEBHOOK_ATTEMPTS, backoff=2):
        self._post = post
        self._attempts = attempts
        self._backoff = backoff
        self._cond = threading.Condition()
        self._pending = None  # (url, state, reasons, done) the worker has not taken yet
        self._thread = None
        self._stop = False

    def send(self, url, state, reasons):
        """Returns a threading.Event, set once this state was sent, given up or superseded."""
        done = threading.Event()
        with self._cond:
            if self._pending is not None:
                self._pending[3].set()
            self._pending = (url, state, list(reasons), done)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="conference-webhook", daemon=True)
                self._thread.start()
            self._cond.notify()
        return done

    def stop(self):
        with self._cond:
            self._stop = True
            self._cond.notify()
        if self._thread is not None:
            self._thread.join()

    def _superseded(self):
        return self._pending is not None or self._stop

    def _run(self):
        while True:
            with self._cond:
                self._cond.wait_for(self._superseded)
                if self._stop:
                    return
                url, state, reasons, done = self._pending
                self._pending = None
            try:
                self._deliver(url, state, reasons)
            finally:
                done.set()

    def _deliver(self, url, state, reasons):
        for attempt in range(1, self._attempts + 1):
            try:
                self._post(url, state, reasons)
                logging.info(f"Conference webhook {redact(url)} sent: {state}")
                return
            except Exception as e:
                logging.warning(f"Conference webhook {redact(url)} attempt {attempt}/{self._attempts} failed: "
                                f"{format_error(e)}")
            if attempt < self._attempts:
                with self._cond:
                    if self._cond.wait_for(self._superseded, self._backoff * 2 ** (attempt - 1)):
                        return


webhook_dispatcher = WebhookDispatcher()


# ---- Detector ----

class ConferenceDetector:
    """Polls the signals and keeps the conference state. poll() does the work; start() runs it in a
    thread. on_change(active, reasons) is called on each change, and once after the first poll so a
    webhook receiver learns the state after a reboot.

    The probes are injectable for the tests: read_pipewire() -> pw-dump JSON, video_users() -> process
    names, processes(names) -> running names, dnd() -> bool, registry -> a WindowsRegistry stand-in.
    windows (default: os.name == "nt") picks the Windows probes; the Linux ones are then never called.
    """

    def __init__(self, settings=None, clock=time.monotonic, on_change=None, read_pipewire=read_pipewire,
                 video_users=None, processes=None, dnd=None, windows=None, registry=None):
        self._mutex = threading.Lock()
        self.configure(settings)
        self._clock = clock
        self._on_change = on_change or self._notify
        self._windows = IS_WINDOWS if windows is None else bool(windows)
        self._registry = registry  # created on first use, so winreg is only imported on Windows
        self._read_pipewire = read_pipewire
        self._video_users = video_users or self._linux_video_users
        if self._windows:
            self._processes = processes or windows_running_processes
            self._dnd = dnd or (lambda: windows_dnd_active(self._hkcu()))
        else:
            self._processes = processes or self._linux_processes
            self._dnd = dnd or dnd_active
        self._comms = None  # proc_comms() of the running poll, read once by whichever probe needs it first
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
            self._settings = normalize(copy.deepcopy(settings or {}))

    @property
    def active(self):
        with self._mutex:
            return self._active

    def report_screenshare(self, sharing):
        """The GNOME extension's view of screen sharing (SCREENSHARE on|off); combined with pw-dump."""
        if self._windows:
            return
        with self._mutex:
            self._extension = (bool(sharing), self._clock())

    def state(self):
        """Everything for the CONFERENCE command and STATUS."""
        with self._mutex:
            enabled = self._settings["signals"]
            fresh = self._extension_fresh()
            if self._windows:
                source = "unavailable"
            elif fresh and (self._extension[0] or not self._signals["screen_share"]):
                source = "extension"
            else:
                source = "pipewire"
            return {
                "active": self._active,
                "reasons": list(self._reasons),
                "signals": {name: {"enabled": bool(enabled.get(name)), "active": bool(self._signals[name]),
                                   "sources": list(self._signals[name])} for name in SIGNALS},
                "screen_share_source": source,
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

    def _hkcu(self):
        if self._registry is None:
            self._registry = WindowsRegistry()
        return self._registry

    def _proc_comms(self):
        if self._comms is None:
            self._comms = proc_comms()
        return self._comms

    def _linux_processes(self, names):
        return running_processes(names, comms=self._proc_comms())

    def _linux_video_users(self):
        return video_device_users(comms=self._proc_comms())

    def _read_windows(self, settings, enabled):
        """Camera and microphone from the consent store. Windows offers no screen share source."""
        signals = {}
        for name, device in (("microphone", "microphone"), ("camera", "webcam")):
            if enabled.get(name):
                signals[name] = self._probe(f"{device} registry", lambda d=device: consent_store_users(
                    d, settings["ignore_apps"], self._hkcu())) or []
        return signals

    def _read_linux(self, settings, enabled):
        """Screen share, microphone and camera from pw-dump and the GNOME extension; camera also from /proc."""
        signals = {}
        if enabled.get("microphone") or enabled.get("camera") or enabled.get("screen_share"):
            nodes = self._probe("pw-dump", self._read_pipewire)
            if nodes is not None:
                signals.update(pipewire_signals(nodes, settings["ignore_apps"]))
        with self._mutex:
            extension = self._extension if self._extension_fresh() else None
        if extension is not None and extension[0]:
            signals["screen_share"] = sorted(set(signals.get("screen_share", [])) | {"GNOME Shell"})
        if enabled.get("camera"):
            users = self._probe("/proc fd scan", self._video_users) or []
            signals["camera"] = sorted(set(signals.get("camera", [])) | set(users))
        return signals

    def _read_signals(self, settings):
        enabled = settings["signals"]
        self._comms = None
        signals = {name: [] for name in SIGNALS}
        signals.update((self._read_windows if self._windows else self._read_linux)(settings, enabled))
        # The meeting apps that run, read once: the processes signal, and what an open microphone needs
        # to count. Not read for an idle microphone, so tasklist does not run every poll on Windows.
        apps = []
        if enabled.get("processes") or (enabled.get("microphone") and signals["microphone"]
                                        and settings["microphone_needs_app"]):
            apps = self._probe("processes", self._processes, settings["processes"]) or []
        signals["processes"] = apps
        if settings["microphone_needs_app"] and not apps:
            signals["microphone"] = []
        if enabled.get("do_not_disturb"):
            signals["do_not_disturb"] = ["Do Not Disturb"] if self._probe("do not disturb", self._dnd) else []
        return {name: (found if enabled.get(name) else []) for name, found in signals.items()}

    def poll(self):
        with self._mutex:
            settings = self._settings  # configure() replaces it, never changes it
        signals = self._read_signals(settings)
        now = self._clock()
        reasons = [name for name in SIGNALS if signals[name]]
        end_grace = settings["end_grace_seconds"]

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
            url = self._settings["webhook_url"].strip()
        if url:
            webhook_dispatcher.send(url, "on" if active else "off", reasons)

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
