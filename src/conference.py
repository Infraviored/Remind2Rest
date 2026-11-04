"""Whether a video conference is running, from what the machine itself shows: a screen share, an open
microphone or camera, a meeting app, GNOME's Do Not Disturb. Polled every POLL_INTERVAL seconds in its
own thread, so a slow pw-dump never holds up the scheduler tick; the gate only reads the result.

On Windows the signals come from elsewhere (see "Windows probes" below): the microphone from the audio
system's active capture sessions (WASAPI), the camera from Media Foundation's sensor activity monitor
(both plus the registry's CapabilityAccessManager consent store, which newer builds no longer update),
screen sharing from the indicator window a browser shows while it shares, processes from tasklist plus
visible window titles (Teams in a browser), Do Not Disturb (best effort) from the notification settings.
None of the Linux tools (pw-dump, gsettings, /proc) is run on Windows.

With microphone_needs_app (the default) the microphone and the camera count only as a call: both
together, or the microphone while a meeting app runs. Each signal can be switched off in
config["conference"]["signals"]. The conference is on while any enabled signal is, and off once none has been for end_grace_seconds (a call that drops for a moment
does not end it). Each change of state is logged and, if conference.webhook_url is set, POSTed there.
"""
import copy
import csv
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


POLL_INTERVAL = 3       # s between two polls
TOOL_TIMEOUT = 2        # s a pw-dump / gsettings call may take
EXTENSION_FRESH = 15    # s a SCREENSHARE report of the GNOME extension stays valid (it resends every 5 s)
WEBHOOK_TIMEOUT = 10    # s per webhook attempt
WEBHOOK_ATTEMPTS = 3

IS_WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000  # subprocess.CREATE_NO_WINDOW, which only exists on Windows builds

SIGNALS = ("screen_share", "microphone", "camera", "processes", "do_not_disturb")

DEFAULTS = {
    "signals": {"screen_share": True, "microphone": True, "camera": True, "processes": False,
                "do_not_disturb": True},
    "ignore_apps": ["VibeVoice"],
    # The microphone alone is no call (dictation, voice tools), the camera alone neither (a camera app,
    # face unlock). Both together are a video call; the microphone also counts while an app of
    # "processes" runs (whether or not the processes signal itself is on). Screen sharing always counts.
    "microphone_needs_app": True,
    # On Windows matched without ".exe": teams = classic Teams.exe, ms-teams = new Teams, zoom = Zoom.exe.
    "processes": ["teams", "teams-for-linux", "ms-teams", "zoom"],
    # Windows only: a visible window whose title contains one of these counts like a meeting app
    # (Teams or Meet in a browser has no process of its own).
    "window_titles": ["Microsoft Teams", "Zoom Meeting", "Google Meet"],
    # Windows only: the window a browser shows while it shares the screen or a window. Firefox:
    # "Firefox — Sharing Indicator" (only while sharing, not for microphone or camera); Chrome and
    # Edge: the bar "<site> is sharing your screen." / "... is sharing a window.".
    "share_indicators": ["Sharing Indicator", "is sharing your screen", "is sharing a window"],
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


# ---- Windows probes. The registry is read through a small reader, so the tests can fake it. ----

CONSENT_STORE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
NOTIFICATION_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
# Microphone or camera use that is no call: the Settings app's level meter and camera preview.
WINDOWS_METER_APPS = {"windows.immersivecontrolpanel", "systemsettings"}
AUDIO_SESSION_ACTIVE = 1   # AudioSessionStateActive
_com_ready = threading.local()


def _init_com():
    """COM once per thread (the detector polls in its own)."""
    import comtypes
    if not getattr(_com_ready, "done", False):
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except OSError:
            pass  # already set up in this thread (comtypes does it on import in the main thread)
        _com_ready.done = True


def _uninit_com():
    """Uninitialize COM for this thread if initialized by _init_com."""
    import comtypes
    if getattr(_com_ready, "done", False):
        try:
            comtypes.CoUninitialize()
        except Exception:
            pass
        _com_ready.done = False


def wasapi_capture_users(ignore_apps=()):
    """Processes recording from any active microphone right now: the audio system's capture sessions
    in state Active, by process. This is what the taskbar's microphone icon shows. Newer Windows 11
    builds no longer keep the consent store's LastUsedTime values current, so this is the main source.
    COM is set up once per thread (the detector polls in its own)."""
    import comtypes
    import psutil
    from pycaw.constants import CLSID_MMDeviceEnumerator
    from pycaw.pycaw import IAudioSessionControl2, IAudioSessionManager2, IMMDeviceEnumerator
    _init_com()
    ignore = {_strip_exe(name) for name in ignore_apps}
    enumerator = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator,
                                           comtypes.CLSCTX_INPROC_SERVER)
    devices = enumerator.EnumAudioEndpoints(1, 1)   # eCapture, DEVICE_STATE_ACTIVE
    users = set()
    for i in range(devices.GetCount()):
        try:
            device = devices.Item(i)
            manager = device.Activate(IAudioSessionManager2._iid_, comtypes.CLSCTX_ALL, None)
            sessions = manager.QueryInterface(IAudioSessionManager2).GetSessionEnumerator()
            count = sessions.GetCount()
        except Exception:
            continue
        for j in range(count):
            try:
                session = sessions.GetSession(j).QueryInterface(IAudioSessionControl2)
                pid = session.GetProcessId()
                if not pid or session.GetState() != AUDIO_SESSION_ACTIVE:
                    continue
            except Exception:
                continue
            try:
                name = psutil.Process(pid).name()
            except psutil.Error:
                continue
            if _strip_exe(name) not in ignore | WINDOWS_METER_APPS:
                users.add(name)
    return sorted(users)


MF_VERSION = 0x20070   # MF_SDK_VERSION << 16 | MF_API_VERSION


class CameraActivity:
    """Who streams from a camera right now, from Media Foundation's sensor activity monitor (Windows 10
    1809 and later, no admin rights needed). Windows calls back on every change with the full picture;
    the monitor runs from the first call on and the latest picture is kept. The consent store, which
    the camera signal read before, is no longer kept current by newer Windows 11 builds."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pids = set()
        self._monitor = None
        self._callback = None
        self._failed = False

    def _start(self):
        import ctypes
        from ctypes import HRESULT, POINTER, byref, c_int, c_ulong, c_wchar_p, wintypes
        import comtypes
        from comtypes import COMMETHOD, GUID, COMObject, IUnknown

        class IMFSensorProcessActivity(IUnknown):
            _iid_ = GUID("{39DC7F4A-B141-4719-813C-A7F46162A2B8}")
            _methods_ = [
                COMMETHOD([], HRESULT, "GetProcessId", (["out"], POINTER(c_ulong), "pid")),
                COMMETHOD([], HRESULT, "GetStreamingState", (["out"], POINTER(wintypes.BOOL), "streaming")),
                COMMETHOD([], HRESULT, "GetStreamingMode", (["out"], POINTER(c_int), "mode")),
                COMMETHOD([], HRESULT, "GetReportTime", (["out"], POINTER(wintypes.FILETIME), "time")),
            ]

        class IMFSensorActivityReport(IUnknown):
            _iid_ = GUID("{3E8C4BE1-A8C2-4528-90DE-2851BDE5FEAD}")
            _methods_ = [
                COMMETHOD([], HRESULT, "GetFriendlyName", (["in"], c_wchar_p), (["in"], c_ulong),
                          (["out"], POINTER(c_ulong))),
                COMMETHOD([], HRESULT, "GetSymbolicLink", (["in"], c_wchar_p), (["in"], c_ulong),
                          (["out"], POINTER(c_ulong))),
                COMMETHOD([], HRESULT, "GetProcessCount", (["out"], POINTER(c_ulong), "count")),
                COMMETHOD([], HRESULT, "GetProcessActivity", (["in"], c_ulong, "index"),
                          (["out"], POINTER(POINTER(IMFSensorProcessActivity)), "activity")),
            ]

        class IMFSensorActivitiesReport(IUnknown):
            _iid_ = GUID("{683F7A5E-4A19-43CD-B1A9-DBF4AB3F7777}")
            _methods_ = [
                COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_ulong), "count")),
                COMMETHOD([], HRESULT, "GetActivityReport", (["in"], c_ulong, "index"),
                          (["out"], POINTER(POINTER(IMFSensorActivityReport)), "report")),
                COMMETHOD([], HRESULT, "GetActivityReportByDeviceName", (["in"], c_wchar_p),
                          (["out"], POINTER(POINTER(IMFSensorActivityReport)))),
            ]

        class IMFSensorActivitiesReportCallback(IUnknown):
            _iid_ = GUID("{DE5072EE-DBE3-46DC-8A87-B6F631194751}")
            _methods_ = [COMMETHOD([], HRESULT, "OnActivitiesReport",
                                   (["in"], POINTER(IMFSensorActivitiesReport), "report"))]

        class IMFSensorActivityMonitor(IUnknown):
            _iid_ = GUID("{D0CEF145-B3F4-4340-A2E5-7A5080CA05CB}")
            _methods_ = [COMMETHOD([], HRESULT, "Start"), COMMETHOD([], HRESULT, "Stop")]

        owner = self

        class Callback(COMObject):
            _com_interfaces_ = [IMFSensorActivitiesReportCallback]

            def OnActivitiesReport(self, report):
                try:
                    pids = set()
                    for i in range(report.GetCount()):
                        device = report.GetActivityReport(i)
                        for j in range(device.GetProcessCount()):
                            activity = device.GetProcessActivity(j)
                            if activity.GetStreamingState():
                                pids.add(activity.GetProcessId())
                    with owner._lock:
                        owner._pids = pids
                except Exception as e:  # never let an exception escape into Windows' thread
                    logging.warning(f"Camera activity report unreadable: {e}")
                return 0

        _init_com()
        startup = ctypes.WinDLL("mfplat").MFStartup
        startup.restype = HRESULT
        startup(MF_VERSION, 0)
        create = ctypes.WinDLL("mfsensorgroup").MFCreateSensorActivityMonitor
        create.restype = HRESULT
        callback = Callback()
        monitor = POINTER(IMFSensorActivityMonitor)()
        create(callback.QueryInterface(IMFSensorActivitiesReportCallback), byref(monitor))
        monitor.Start()
        self._callback, self._monitor = callback, monitor

    def users(self, ignore_apps=()):
        import psutil
        if self._monitor is None and not self._failed:
            with self._lock:
                if self._monitor is None and not self._failed:
                    try:
                        self._start()
                    except Exception:
                        self._failed = True
                        raise
        with self._lock:
            pids = set(self._pids)
        ignore = {_strip_exe(name) for name in ignore_apps}
        users = set()
        for pid in pids:
            try:
                name = psutil.Process(pid).name()
            except psutil.Error:
                continue
            if _strip_exe(name) not in ignore | WINDOWS_METER_APPS:
                users.add(name)
        return sorted(users)

    def stop(self):
        with self._lock:
            if self._monitor is not None:
                try:
                    self._monitor.Stop()
                except Exception:
                    pass
                self._monitor = None
            self._callback = None


_camera_activity = None


def windows_camera_users(ignore_apps=()):
    """Processes streaming from a camera right now (see CameraActivity)."""
    global _camera_activity
    if _camera_activity is None:
        _camera_activity = CameraActivity()
    return _camera_activity.users(ignore_apps)


def windows_title_matches(patterns):
    """Which of `patterns` occur (case-insensitively) in the title of a visible window. Only the
    pattern is returned, never the title: that may hold a meeting or contact name."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    wanted = [(p, p.lower()) for p in patterns if p]
    found = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.lower()
                found.update(p for p, low in wanted if low in title)
        return True

    user32.EnumWindows(visit, 0)
    return sorted(found)


class WindowsRegistry:
    """Read-only HKEY_CURRENT_USER access: subkeys(path) -> names ([] if the key is missing),
    value(path, name) -> data (None if missing). winreg is imported here, so only on Windows."""

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

    def value(self, path, name):
        winreg = self._winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                return winreg.QueryValueEx(key, name)[0]
        except OSError:
            return None


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
            start, stop = registry.value(path, "LastUsedTimeStart"), registry.value(path, "LastUsedTimeStop")
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
    names, processes(names) -> running names, dnd() -> bool, registry -> a WindowsRegistry stand-in.
    windows (default: os.name == "nt") picks the Windows probes; the Linux ones are then never called.
    """

    def __init__(self, settings=None, clock=time.monotonic, on_change=None, read_pipewire=read_pipewire,
                 video_users=video_device_users, processes=None, dnd=None, windows=None, registry=None,
                 capture_users=wasapi_capture_users, window_titles=windows_title_matches,
                 camera_users=windows_camera_users):
        self._settings = fill_defaults({"conference": copy.deepcopy(settings or {})})["conference"]
        self._clock = clock
        self._on_change = on_change or self._notify
        self._windows = IS_WINDOWS if windows is None else bool(windows)
        self._registry = registry  # created on first use, so winreg is only imported on Windows
        self._read_pipewire = read_pipewire
        self._video_users = video_users
        self._capture_users = capture_users
        self._window_titles = window_titles
        self._camera_users = camera_users
        if self._windows:
            self._processes = processes or windows_running_processes
            self._dnd = dnd or (lambda: windows_dnd_active(self._hkcu()))
        else:
            self._processes = processes or running_processes
            self._dnd = dnd or dnd_active
        self._mutex = threading.Lock()
        self._signals = {name: [] for name in SIGNALS}
        self._active = False
        self._reasons = []
        self._polled = False
        self._last_signal_at = None
        self._extension = None  # (screen sharing?, monotonic time of the report)
        self._failed = set()   # probes whose failure was logged already
        self._call_mics = set()  # microphone users seen together with a meeting app (poll thread only)
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
        if self._windows:
            return
        with self._mutex:
            self._extension = (bool(sharing), self._clock())

    def state(self):
        """Everything for the CONFERENCE command and STATUS."""
        with self._mutex:
            enabled = self._settings["signals"]
            ext_active = self._extension_fresh() and self._extension[0]
            if self._windows:
                source = "indicator window"
            elif ext_active or (self._extension_fresh() and not self._signals["screen_share"]):
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

    def _read_windows_devices(self, settings, signals):
        """Microphone and camera live (audio capture sessions, camera activity monitor) plus the consent
        store; screen sharing from a browser's sharing indicator window."""
        live_probes = {"microphone": ("audio capture sessions", self._capture_users),
                       "camera": ("camera activity", self._camera_users)}
        for name, device in (("microphone", "microphone"), ("camera", "webcam")):
            if settings["signals"].get(name):
                stored = self._probe(f"{device} registry", lambda d=device: consent_store_users(
                    d, settings["ignore_apps"], self._hkcu())) or []
                probe_name, probe = live_probes[name]
                live = self._probe(probe_name, probe, settings["ignore_apps"]) or []
                signals[name] = sorted(set(stored) | set(live))
        if settings["signals"].get("screen_share") and settings.get("share_indicators"):
            shown = self._probe("sharing indicator", self._window_titles, settings["share_indicators"]) or []
            signals["screen_share"] = [f"{t} window" for t in shown]

    def _running_apps(self, settings):
        """Meeting apps that run: processes, and on Windows windows titled like one (in a browser)."""
        apps = self._probe("processes", self._processes, settings["processes"]) or []
        if self._windows and settings.get("window_titles"):
            titles = self._probe("window titles", self._window_titles, settings["window_titles"]) or []
            apps = sorted(set(apps) | {f"{t} window" for t in titles})
        return apps

    def _read_signals(self, settings):
        enabled = settings["signals"]
        signals = {name: [] for name in SIGNALS}
        if self._windows:
            self._read_windows_devices(settings, signals)
        elif enabled.get("microphone") or enabled.get("camera") or enabled.get("screen_share"):
            nodes = self._probe("pw-dump", self._read_pipewire)
            if nodes is not None:
                signals.update(pipewire_signals(nodes, settings["ignore_apps"]))
        with self._mutex:
            extension = self._extension if self._extension_fresh() else None
        if not self._windows and extension is not None and extension[0]:
            signals["screen_share"] = sorted(set(signals["screen_share"]) | {"GNOME Shell"})
        if enabled.get("camera") and not self._windows:
            users = self._probe("/proc fd scan", self._video_users) or []
            signals["camera"] = sorted(set(signals["camera"]) | set(users))
        apps = None
        if enabled.get("processes"):
            apps = self._running_apps(settings)
            signals["processes"] = apps
        mics, cameras = set(signals["microphone"]), set(signals["camera"])
        if settings.get("microphone_needs_app", True) and enabled.get("microphone"):
            # A call: microphone and camera together, or the microphone with a meeting app.
            if mics and not cameras and apps is None:
                apps = self._running_apps(settings)
            if mics and (cameras or apps):
                self._call_mics = mics
            elif mics and self._call_mics:
                # The sign can go while the call goes on (camera switched off, another browser tab in
                # front so the title no longer says Teams): who recorded for the call counts as long
                # as it records.
                self._call_mics &= mics
            elif "audio capture sessions" in self._failed and self._call_mics:
                # Keep active call mics during a transient capture probe failure
                signals["microphone"] = sorted(self._call_mics)
            else:
                self._call_mics = set()
            signals["microphone"] = sorted(self._call_mics)
            if not mics:
                signals["camera"] = []  # the camera alone is no call
        else:
            self._call_mics = set()
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
            try:
                while not self._stop.is_set():
                    try:
                        self.poll()
                    except Exception as e:
                        logging.error(f"Conference poll failed: {e}")
                    self._stop.wait(POLL_INTERVAL)
            finally:
                if self._windows:
                    _uninit_com()

        self._thread = threading.Thread(target=run, name="conference-detector", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if hasattr(self._camera_users, "stop"):
            try:
                self._camera_users.stop()
            except Exception:
                pass
        global _camera_activity
        if _camera_activity is not None:
            _camera_activity.stop()


detector = ConferenceDetector()
