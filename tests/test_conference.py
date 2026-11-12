"""Run: python -m unittest tests.test_conference"""
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import unittest
import ctypes
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.conference as conference
from src.conference import ConferenceDetector, pipewire_signals, EXTENSION_FRESH

WEBHOOK = "https://ha.example.invalid/api/webhook/PLACEHOLDER-ID"


def node(state, **props):
    return {"id": 1, "type": "PipeWire:Interface:Node", "info": {"state": state, "props": props}}


# Shaped like real pw-dump output (GNOME 50, PipeWire 1.4).
CAMERA_IDLE = node("suspended", **{"media.class": "Video/Source", "node.name": "v4l2_input.pci-0000_00_14.0-usb-0_6_1.0",
                                   "device.api": "v4l2", "node.description": "Integrated Camera", "media.role": "Camera"})
CAMERA_ON = node("running", **{"media.class": "Video/Source", "node.name": "v4l2_input.pci-0000_00_14.0-usb-0_6_1.0",
                               "device.api": "v4l2", "node.description": "Integrated Camera"})
SCREENCAST = node("paused", **{"media.class": "Video/Source", "node.name": "meta-screen-cast-src",
                               "application.name": "gnome-shell", "application.process.binary": "gnome-shell"})
PLAYBACK = node("running", **{"media.class": "Stream/Output/Audio", "node.name": "Firefox", "application.name": "Firefox"})
MIC_FIREFOX = node("running", **{"media.class": "Stream/Input/Audio", "node.name": "Firefox",
                                 "application.name": "Firefox", "application.process.binary": "firefox"})
MIC_IDLE = node("idle", **{"media.class": "Stream/Input/Audio", "application.name": "Chromium"})
MIC_VIBEVOICE = node("running", **{"media.class": "Stream/Input/Audio", "application.name": "VibeVoice",
                                   "application.process.binary": "python3"})
MONITOR = node("running", **{"media.class": "Stream/Input/Audio", "application.name": "OBS",
                             "stream.capture.sink": "true"})
MONITOR_TARGET = node("running", **{"media.class": "Stream/Input/Audio", "application.name": "OBS",
                                    "target.object": "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"})
PEAK = node("running", **{"media.class": "Stream/Input/Audio", "application.name": "PulseAudio Volume Control",
                          "application.id": "org.PulseAudio.pavucontrol", "media.name": "Peak detect"})
SHELL_METER = node("running", **{"media.class": "Stream/Input/Audio", "application.name": "GNOME Shell",
                                 "application.process.binary": "gnome-shell"})
NOT_A_NODE = {"id": 2, "type": "PipeWire:Interface:Link", "info": {"state": "active"}}


class PipewireSignalsTest(unittest.TestCase):
    def test_idle_machine_shows_nothing(self):
        found = pipewire_signals([CAMERA_IDLE, PLAYBACK, MIC_IDLE, NOT_A_NODE])
        self.assertEqual(found, {"screen_share": [], "microphone": [], "camera": []})

    def test_each_signal(self):
        found = pipewire_signals([CAMERA_ON, SCREENCAST, MIC_FIREFOX])
        self.assertEqual(found, {"screen_share": ["gnome-shell"], "microphone": ["Firefox"],
                                 "camera": ["Integrated Camera"]})

    def test_monitors_meters_and_ignored_apps_are_no_microphone(self):
        nodes = [MIC_VIBEVOICE, MONITOR, MONITOR_TARGET, PEAK, SHELL_METER]
        self.assertEqual(pipewire_signals(nodes, ["vibevoice"])["microphone"], [])
        self.assertEqual(pipewire_signals(nodes, [])["microphone"], ["VibeVoice"])
        # The ignore list also matches the binary.
        self.assertEqual(pipewire_signals([MIC_FIREFOX], ["Firefox"])["microphone"], [])

    def test_camera_node_is_not_a_screen_share(self):
        self.assertEqual(pipewire_signals([CAMERA_ON])["screen_share"], [])

    def test_control_center_meter_is_not_microphone(self):
        cc_node = node("running", **{"media.class": "Stream/Input/Audio", "application.name": "gnome-control-center",
                                     "application.process.binary": "gnome-control-center"})
        self.assertEqual(pipewire_signals([cc_node])["microphone"], [])


class ProcTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def proc(self, pid, comm, fds=()):
        os.makedirs(os.path.join(self.root, pid, "fd"))
        with open(os.path.join(self.root, pid, "comm"), "w") as f:
            f.write(comm + "\n")
        for i, target in enumerate(fds):
            os.symlink(target, os.path.join(self.root, pid, "fd", str(i)))

    def test_video_users_skip_pipewire(self):
        self.proc("10", "pipewire", ["/dev/video0"])
        self.proc("11", "chrome", ["/dev/null", "/dev/video2"])
        self.proc("12", "bash", ["/dev/pts/1"])
        self.proc("13", "pipewire-media-", ["/dev/video1"])
        os.makedirs(os.path.join(self.root, "self"))
        self.assertEqual(conference.video_device_users(self.root), ["chrome"])

    def test_running_processes_case_insensitive_and_truncated(self):
        self.proc("20", "teams-for-linux")  # comm is cut at 15 characters
        self.proc("21", "Zoom")
        self.assertEqual(conference.running_processes(["teams", "teams-for-linux", "zoom"], self.root),
                         ["teams-for-linux", "zoom"])


class Probes:
    def __init__(self):
        self.now = 1000.0
        self.nodes = []
        self.video = []
        self.dnd = False
        self.apps = ["teams"]  # a conference app runs, so the microphone counts
        self.changes = []

    def detector(self, **settings):
        return ConferenceDetector(settings, clock=lambda: self.now, on_change=lambda a, r: self.changes.append((a, r)),
                                  read_pipewire=lambda: self.nodes, video_users=lambda: self.video,
                                  processes=lambda names: list(self.apps), dnd=lambda: self.dnd, windows=False)


class DetectorTest(unittest.TestCase):
    def setUp(self):
        self.p = Probes()
        self.d = self.p.detector()

    def test_microphone_without_app_is_no_conference(self):
        self.p.apps = []
        self.p.nodes = [MIC_FIREFOX]
        self.d.poll()
        self.assertFalse(self.d.active)
        self.assertEqual(self.d.state()["signals"]["microphone"]["sources"], [])

    def test_microphone_alone_counts_when_app_not_required(self):
        self.p.apps = []
        self.p.nodes = [MIC_FIREFOX]
        d = self.p.detector(microphone_needs_app=False)
        d.poll()
        self.assertEqual(d.state()["reasons"], ["microphone"])

    def test_camera_alone_is_no_conference(self):
        # A camera app or face unlock: video without sound is no call.
        self.p.apps = []
        self.p.video = ["firefox"]
        self.d.poll()
        self.assertFalse(self.d.active)
        self.assertEqual(self.d.state()["signals"]["camera"]["sources"], [])

    def test_camera_and_microphone_are_a_call_without_app(self):
        self.p.apps = []
        self.p.video = ["firefox"]
        self.p.nodes = [MIC_FIREFOX]
        self.d.poll()
        self.assertEqual(self.d.state()["reasons"], ["microphone", "camera"])

    def test_call_goes_on_when_the_camera_is_switched_off(self):
        self.p.apps = []
        self.p.video = ["firefox"]
        self.p.nodes = [MIC_FIREFOX]
        self.d.poll()
        self.p.video = []
        self.d.poll()
        self.assertEqual(self.d.state()["reasons"], ["microphone"])

    def test_camera_alone_counts_when_not_required_or_microphone_off(self):
        self.p.apps = []
        self.p.video = ["firefox"]
        for settings in ({"microphone_needs_app": False}, {"signals": {"microphone": False}}):
            d = self.p.detector(**settings)
            d.poll()
            self.assertEqual(d.state()["reasons"], ["camera"], settings)

    def test_disabled_microphone_does_not_probe_processes(self):
        self.p.apps = []
        self.p.nodes = [MIC_FIREFOX]
        self.p.video = ["firefox"]
        probed = []
        d = ConferenceDetector(
            {"signals": {"microphone": False, "camera": True, "processes": False}},
            clock=lambda: self.p.now, on_change=lambda a, r: self.p.changes.append((a, r)),
            read_pipewire=lambda: self.p.nodes, video_users=lambda: self.p.video,
            processes=lambda names: probed.append(names) or [], dnd=lambda: self.p.dnd, windows=False,
        )
        d.poll()
        self.assertEqual(probed, [])
        self.assertFalse(d.state()["signals"]["microphone"]["active"])

    def test_first_poll_reports_state_once(self):
        with self.assertLogs(level="INFO"):
            self.d.poll()
        self.d.poll()
        self.assertEqual(self.p.changes, [(False, [])])

    def test_on_at_once_off_after_grace(self):
        self.d.poll()
        self.p.nodes = [MIC_FIREFOX]
        with self.assertLogs(level="INFO") as logs:
            self.d.poll()
        self.assertIn("Conference started: microphone (Firefox)", "\n".join(logs.output))
        self.assertTrue(self.d.active)
        self.p.nodes = []
        self.p.now += 59
        self.d.poll()
        self.assertTrue(self.d.active)  # still within end_grace_seconds
        self.assertEqual(self.d.state()["reasons"], ["microphone"])
        self.p.now += 1
        with self.assertLogs(level="INFO") as logs:
            self.d.poll()
        self.assertIn("Conference ended", "\n".join(logs.output))
        self.assertEqual(self.p.changes, [(False, []), (True, ["microphone"]), (False, [])])

    def test_disabled_signal_is_ignored(self):
        d = self.p.detector(signals={"do_not_disturb": False})
        self.p.dnd = True
        d.poll()
        self.assertFalse(d.active)
        self.assertFalse(d.state()["signals"]["do_not_disturb"]["enabled"])
        self.d.poll()
        self.assertEqual(self.d.state()["reasons"], ["do_not_disturb"])

    def test_extension_and_pipewire_screen_share_combine_with_or(self):
        # Fresh extension report of False does not suppress PipeWire screencast detection
        self.p.nodes = [SCREENCAST]
        self.d.report_screenshare(False)
        self.d.poll()
        self.assertTrue(self.d.active)
        self.assertEqual(self.d.state()["reasons"], ["screen_share"])
        self.assertEqual(self.d.state()["signals"]["screen_share"]["sources"], ["gnome-shell"])

        # Extension report of True adds GNOME Shell
        self.p.nodes = []
        self.d.report_screenshare(True)
        self.d.poll()
        self.assertTrue(self.d.active)
        self.assertEqual(self.d.state()["signals"]["screen_share"]["sources"], ["GNOME Shell"])
        self.assertEqual(self.d.state()["screen_share_source"], "extension")

        # When extension report expires and grace elapses, it reverts to PipeWire
        self.p.now += EXTENSION_FRESH + 60
        self.d.poll()
        self.assertFalse(self.d.active)
        self.assertEqual(self.d.state()["screen_share_source"], "pipewire")

    def test_camera_from_proc_scan(self):
        self.p.video = ["chrome"]
        self.p.nodes = [MIC_FIREFOX]
        self.d.poll()
        self.assertEqual(self.d.state()["signals"]["camera"]["sources"], ["chrome"])

    def test_missing_pw_dump_logged_once(self):
        def missing():
            raise FileNotFoundError("pw-dump")
        d = ConferenceDetector({}, clock=lambda: self.p.now, on_change=lambda a, r: None, read_pipewire=missing,
                               video_users=lambda: [], dnd=lambda: False, windows=False)
        with self.assertLogs(level="WARNING") as logs:
            d.poll()
            d.poll()
        self.assertEqual(len([line for line in logs.output if "pw-dump" in line]), 1)
        self.assertFalse(d.active)

    def test_none_end_grace_does_not_crash_poll(self):
        d = self.p.detector(end_grace_seconds=None)
        self.p.nodes = [MIC_FIREFOX]
        d.poll()
        self.assertTrue(d.active)
        self.p.nodes = []
        self.p.now += 60
        d.poll()
        self.assertFalse(d.active)

    def test_dnd_active_synchronous_call(self):
        class FakeCompletedProcess:
            def __init__(self, stdout):
                self.stdout = stdout

        with patch("src.conference.subprocess.run", return_value=FakeCompletedProcess("false\n")) as mock_run:
            self.assertTrue(conference.dnd_active())
            mock_run.assert_called_once_with(
                ["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"],
                capture_output=True, text=True, timeout=conference.TOOL_TIMEOUT, check=True,
            )
        with patch("src.conference.subprocess.run", return_value=FakeCompletedProcess("true\n")):
            self.assertFalse(conference.dnd_active())


STORE = conference.CONSENT_STORE
CHROME = "C:#Program Files#Google#Chrome#Application#chrome.exe"
VIBEVOICE = "C:#Users#me#VibeVoice#VibeVoice.exe"


class FakeRegistry:
    """Stands in for WindowsRegistry: keys maps a path to its values; subkeys are derived from paths."""

    def __init__(self, keys):
        self.keys = keys

    def subkeys(self, path):
        prefix = path + "\\"
        return sorted({p[len(prefix):].split("\\")[0] for p in self.keys if p.startswith(prefix)})

    def value(self, path, name):
        return self.keys.get(path, {}).get(name)


def in_use(start=133000000000000000):
    return {"LastUsedTimeStart": start, "LastUsedTimeStop": 0}


def used_before():
    return {"LastUsedTimeStart": 133000000000000000, "LastUsedTimeStop": 133000000100000000}


class WindowsProbesTest(unittest.TestCase):
    def test_consent_store_in_use_vs_not(self):
        reg = FakeRegistry({
            f"{STORE}\\webcam\\MSTeams_8wekyb3d8bbwe": in_use(),
            f"{STORE}\\webcam\\Microsoft.WindowsCamera_8wekyb3d8bbwe": used_before(),
            f"{STORE}\\webcam\\NonPackaged\\{CHROME}": in_use(),
            f"{STORE}\\webcam\\NonPackaged\\C:#Tools#never.exe": {"LastUsedTimeStart": 0, "LastUsedTimeStop": 0},
            f"{STORE}\\webcam\\NonPackaged\\C:#Tools#nostop.exe": {"LastUsedTimeStart": 5},
            f"{STORE}\\microphone\\NonPackaged\\C:#Zoom#Zoom.exe": in_use(),
        })
        self.assertEqual(conference.consent_store_users("webcam", [], reg), ["MSTeams", "chrome.exe"])
        self.assertEqual(conference.consent_store_users("microphone", [], reg), ["Zoom.exe"])

    def test_missing_store_means_nobody(self):
        self.assertEqual(conference.consent_store_users("webcam", [], FakeRegistry({})), [])

    def test_broken_subkey_value_is_skipped(self):
        class BrokenEntryRegistry(FakeRegistry):
            def value(self, path, name):
                if "broken.exe" in path:
                    raise PermissionError("access denied")
                return super().value(path, name)

        reg = BrokenEntryRegistry({
            f"{STORE}\\webcam\\NonPackaged\\C:#Tools#broken.exe": in_use(),
            f"{STORE}\\webcam\\NonPackaged\\{CHROME}": in_use(),
        })
        self.assertEqual(conference.consent_store_users("webcam", [], reg), ["chrome.exe"])

    def test_app_names(self):
        self.assertEqual(conference.windows_app_name(CHROME, packaged=False), "chrome.exe")
        self.assertEqual(conference.windows_app_name("MSTeams_8wekyb3d8bbwe", packaged=True), "MSTeams")
        self.assertEqual(conference.windows_app_name("NoPublisherHash", packaged=True), "NoPublisherHash")

    def test_ignore_apps_and_settings_meter(self):
        reg = FakeRegistry({
            f"{STORE}\\microphone\\NonPackaged\\{VIBEVOICE}": in_use(),
            f"{STORE}\\microphone\\windows.immersivecontrolpanel_cw5n1h2txyewy": in_use(),
            f"{STORE}\\microphone\\MSTeams_8wekyb3d8bbwe": in_use(),
        })
        # "VibeVoice" matches VibeVoice.exe, case-insensitively and without ".exe".
        self.assertEqual(conference.consent_store_users("microphone", ["vibevoice"], reg), ["MSTeams"])
        self.assertEqual(conference.consent_store_users("microphone", ["VibeVoice", "msteams"], reg), [])
        self.assertEqual(conference.consent_store_users("microphone", [], reg), ["MSTeams", "VibeVoice.exe"])

    def test_dnd_value(self):
        path = conference.NOTIFICATION_SETTINGS
        self.assertTrue(conference.windows_dnd_active(
            FakeRegistry({path: {"NOC_GLOBAL_SETTING_TOASTS_ENABLED": 0}})))
        self.assertFalse(conference.windows_dnd_active(
            FakeRegistry({path: {"NOC_GLOBAL_SETTING_TOASTS_ENABLED": 1}})))
        self.assertFalse(conference.windows_dnd_active(FakeRegistry({})))

    def test_tasklist_parsing_and_matching(self):
        csv_text = ('"System Idle Process","0","Services","0","8 K"\n'
                    '"ms-teams.exe","4242","Console","1","200.000 K"\n'
                    '"Zoom.exe","77","Console","1","1,024 K"\n'
                    '"explorer.exe","100","Console","1","90,000 K"\n'
                    '\n')
        self.assertEqual(conference.parse_tasklist(csv_text),
                         {"System Idle Process", "ms-teams.exe", "Zoom.exe", "explorer.exe"})
        found = conference.windows_running_processes(["teams", "ms-teams", "ZOOM.EXE", "Teams.exe"],
                                                     tasklist=lambda: csv_text)
        self.assertEqual(found, ["ZOOM.EXE", "ms-teams"])
        # tasklist's localized "no tasks" line is not CSV and matches nothing.
        self.assertEqual(conference.windows_running_processes(["teams"], tasklist=lambda: "INFO: none.\n"), [])

    def test_tasklist_runs_without_console_window(self):
        class Done:
            stdout = '"Zoom.exe","1","Console","1","1 K"\n'
        with patch("src.conference.subprocess.run", return_value=Done()) as run:
            self.assertEqual(conference.run_tasklist(), Done.stdout)
        kwargs = run.call_args.kwargs
        self.assertEqual(run.call_args.args[0], ["tasklist", "/FO", "CSV", "/NH"])
        self.assertEqual(kwargs["creationflags"], 0x08000000)
        self.assertEqual(kwargs["timeout"], conference.TOOL_TIMEOUT)

    def test_wasapi_capture_users(self):
        class FakeSession:
            def __init__(self, pid, state):
                self._pid = pid
                self._state = state

            def GetProcessId(self):
                return self._pid

            def GetState(self):
                return self._state

            def QueryInterface(self, iface):
                return self

        class FakeEnumerator:
            def __init__(self, sessions):
                self._sessions = sessions

            def GetCount(self):
                return len(self._sessions)

            def GetSession(self, idx):
                return self._sessions[idx]

        class FakeManager:
            def __init__(self, enumerator):
                self._enumerator = enumerator

            def QueryInterface(self, iface):
                return self

            def GetSessionEnumerator(self):
                return self._enumerator

        class FakeDevice:
            def __init__(self, manager):
                self._manager = manager

            def Activate(self, iid, ctx, params):
                return self._manager

        class FakeDevices:
            def __init__(self, devices):
                self._devices = devices

            def GetCount(self):
                return len(self._devices)

            def Item(self, idx):
                return self._devices[idx]

        class FakeMMDeviceEnumerator:
            def __init__(self, devices):
                self._devices = devices

            def EnumAudioEndpoints(self, flow, state):
                return self._devices

        s1 = FakeSession(101, conference.AUDIO_SESSION_ACTIVE)
        s2 = FakeSession(102, conference.AUDIO_SESSION_ACTIVE)
        s3 = FakeSession(103, 0)  # inactive
        s4 = FakeSession(104, conference.AUDIO_SESSION_ACTIVE)  # ignored app
        s5 = FakeSession(105, conference.AUDIO_SESSION_ACTIVE)  # meter app
        mgr = FakeManager(FakeEnumerator([s1, s2, s3, s4, s5]))
        devs = FakeDevices([FakeDevice(mgr)])
        fake_enum = FakeMMDeviceEnumerator(devs)

        names = {
            101: "firefox.exe",
            102: "teams.exe",
            104: "VibeVoice.exe",
            105: "SystemSettings.exe",
        }

        class FakeProc:
            def __init__(self, pid):
                if pid not in names:
                    raise KeyError(pid)
                self._name = names[pid]

            def name(self):
                return self._name

        fake_comtypes = MagicMock()
        fake_comtypes.CoCreateInstance.return_value = fake_enum

        with patch.dict(sys.modules, {
            "comtypes": fake_comtypes,
            "pycaw.constants": MagicMock(),
            "pycaw.pycaw": MagicMock(),
            "psutil": MagicMock(Process=FakeProc, Error=Exception),
        }):
            users = conference.wasapi_capture_users(["VibeVoice"])
            self.assertEqual(users, ["firefox.exe", "teams.exe"])

    def test_wasapi_capture_users_error_handling(self):
        class BrokenDevice:
            def Activate(self, iid, ctx, params):
                raise OSError("device disconnected")

        class BrokenSession:
            def QueryInterface(self, iface):
                raise OSError("session died")

        class GoodSession:
            def QueryInterface(self, iface):
                return self

            def GetProcessId(self):
                return 201

            def GetState(self):
                return conference.AUDIO_SESSION_ACTIVE

        class FakeDevices:
            def __init__(self, items):
                self._items = items

            def GetCount(self):
                return len(self._items)

            def Item(self, i):
                return self._items[i]

        class FakeEnumerator:
            def __init__(self, sessions):
                self._sessions = sessions

            def GetCount(self):
                return len(self._sessions)

            def GetSession(self, i):
                return self._sessions[i]

        class FakeManager:
            def QueryInterface(self, iface):
                return self

            def GetSessionEnumerator(self):
                return FakeEnumerator([BrokenSession(), GoodSession()])

        class GoodDevice:
            def Activate(self, iid, ctx, params):
                return FakeManager()

        class GoodProc:
            def __init__(self, pid):
                pass

            def name(self):
                return "good.exe"

        devs = FakeDevices([BrokenDevice(), GoodDevice()])
        fake_comtypes = MagicMock()
        fake_comtypes.CoCreateInstance.return_value = MagicMock(EnumAudioEndpoints=lambda f, s: devs)
        fake_psutil = MagicMock(Process=GoodProc, Error=Exception)

        with patch.dict(sys.modules, {
            "comtypes": fake_comtypes,
            "pycaw.constants": MagicMock(),
            "pycaw.pycaw": MagicMock(),
            "psutil": fake_psutil,
        }):
            users = conference.wasapi_capture_users([])
            self.assertEqual(users, ["good.exe"])

    def test_windows_title_matches_enumeration(self):
        windows = [
            (1, True, "Chat | Microsoft Teams"),
            (2, False, "Hidden | Microsoft Teams"),
            (3, True, "Mozilla Firefox — Sharing Indicator"),
            (4, True, ""),
            (5, True, "Google Meet: Project Sync"),
        ]

        class FakeUser32:
            def EnumWindows(self, callback, lparam):
                for hwnd, visible, title in windows:
                    callback(hwnd, lparam)
                return 1

            def IsWindowVisible(self, hwnd):
                for h, vis, _ in windows:
                    if h == hwnd:
                        return vis
                return False

            def GetWindowTextLengthW(self, hwnd):
                for h, _, title in windows:
                    if h == hwnd:
                        return len(title)
                return 0

            def GetWindowTextW(self, hwnd, buf, max_len):
                for h, _, title in windows:
                    if h == hwnd:
                        buf.value = title
                        return len(title)
                return 0

        with patch.object(ctypes, "windll", MagicMock(user32=FakeUser32()), create=True):
            res = conference.windows_title_matches(["Microsoft Teams", "Sharing Indicator", "zoom"])
            self.assertEqual(res, ["Microsoft Teams", "Sharing Indicator"])

    def test_camera_activity_lifecycle_and_users(self):
        activity = conference.CameraActivity()
        self.assertFalse(activity._failed)

        class DictProc:
            def __init__(self, pid):
                self._pid = pid

            def name(self):
                return names[self._pid]

        activity._monitor = MagicMock()
        activity._pids = {301, 302, 303}
        names = {301: "firefox.exe", 302: "VibeVoice.exe", 303: "windows.immersivecontrolpanel.exe"}
        fake_psutil = MagicMock(Process=DictProc, Error=Exception)
        with patch.dict(sys.modules, {"psutil": fake_psutil}):
            users = activity.users(["VibeVoice"])
            self.assertEqual(users, ["firefox.exe"])

        activity.stop()
        self.assertIsNone(activity._monitor)

        fail_activity = conference.CameraActivity()
        with patch.object(fail_activity, "_start", side_effect=OSError("media foundation missing")):
            with patch.dict(sys.modules, {"psutil": MagicMock()}):
                with self.assertRaises(OSError):
                    fail_activity.users()
                self.assertTrue(fail_activity._failed)
                self.assertEqual(fail_activity.users(), [])

    def test_com_init_and_uninit(self):
        fake_comtypes = MagicMock()
        with patch.dict(sys.modules, {"comtypes": fake_comtypes}):
            conference._com_ready.done = False
            conference._init_com()
            self.assertTrue(conference._com_ready.done)
            fake_comtypes.CoInitializeEx.assert_called_once_with(fake_comtypes.COINIT_MULTITHREADED)

            conference._uninit_com()
            self.assertFalse(conference._com_ready.done)
            fake_comtypes.CoUninitialize.assert_called_once()


def shown(*titles):
    """A fake window_titles probe for these visible window titles (matches like the real one)."""
    return lambda patterns: sorted(p for p in patterns if any(p.lower() in t.lower() for t in titles))


class WindowsDetectorTest(unittest.TestCase):
    def linux_probe(self, name):
        def probe(*args):
            self.linux_calls.append(name)
            return []
        return probe

    def setUp(self):
        self.linux_calls = []
        self.changes = []

    def detector(self, registry, settings=None, **kw):
        kw.setdefault("capture_users", lambda ignore: [])
        kw.setdefault("window_titles", lambda patterns: [])
        kw.setdefault("camera_users", lambda ignore: [])
        return ConferenceDetector(settings or {}, clock=lambda: 1000.0, on_change=lambda a, r: self.changes.append((a, r)),
                                  read_pipewire=self.linux_probe("pw-dump"), video_users=self.linux_probe("proc"),
                                  windows=True, registry=registry, **kw)

    def test_idle_windows_is_all_off_without_linux_tools(self):
        settings = {"signals": {name: True for name in conference.SIGNALS}}
        with patch("src.conference.subprocess.run",
                   side_effect=AssertionError("no subprocess on simulated Windows")) as run, \
             patch("src.conference.os.listdir", side_effect=AssertionError("no /proc on Windows")):
            d = self.detector(FakeRegistry({}), settings, processes=lambda names: [])
            d.poll()
        run.assert_not_called()
        self.assertEqual(self.linux_calls, [])
        self.assertFalse(d.active)
        self.assertEqual(self.changes, [(False, [])])
        self.assertTrue(all(not s["active"] for s in d.state()["signals"].values()))

    def test_os_name_nt_picks_windows_probes(self):
        with patch.object(conference, "IS_WINDOWS", True):
            d = ConferenceDetector({}, read_pipewire=self.linux_probe("pw-dump"), registry=FakeRegistry({}))
        self.assertIs(d._processes, conference.windows_running_processes)
        d._on_change = lambda a, r: None
        d.poll()
        self.assertEqual(self.linux_calls, [])
        with patch.object(conference, "IS_WINDOWS", False):
            self.assertIs(ConferenceDetector({})._processes, conference.running_processes)

    def test_windows_signals_from_registry(self):
        reg = FakeRegistry({
            f"{STORE}\\microphone\\MSTeams_8wekyb3d8bbwe": in_use(),
            f"{STORE}\\webcam\\NonPackaged\\{CHROME}": in_use(),
            conference.NOTIFICATION_SETTINGS: {"NOC_GLOBAL_SETTING_TOASTS_ENABLED": 0},
        })
        d = self.detector(reg, {"signals": {"processes": True}}, processes=lambda names: ["teams"])
        d.report_screenshare(True)  # a stray SCREENSHARE stays harmless
        d.poll()
        state = d.state()
        self.assertTrue(state["active"])
        self.assertEqual(state["signals"]["microphone"]["sources"], ["MSTeams"])
        self.assertEqual(state["signals"]["camera"]["sources"], ["chrome.exe"])
        self.assertEqual(state["signals"]["do_not_disturb"]["sources"], ["Do Not Disturb"])
        self.assertEqual(state["signals"]["processes"]["sources"], ["teams"])
        self.assertEqual(state["signals"]["screen_share"]["sources"], [])
        self.assertFalse(state["signals"]["screen_share"]["active"])
        self.assertEqual(state["screen_share_source"], "indicator window")
        self.assertEqual(self.linux_calls, [])

    def test_broken_registry_never_crashes(self):
        class Broken:
            def subkeys(self, path):
                raise PermissionError("access denied")

            def value(self, path, name):
                raise OSError("boom")
        d = self.detector(Broken())
        with self.assertLogs(level="WARNING") as logs:
            d.poll()
            d.poll()
        self.assertFalse(d.active)
        self.assertEqual(len([line for line in logs.output if "webcam registry" in line]), 1)

    def test_missing_winreg_never_crashes(self):
        # On Linux there is no winreg: the import error is logged once per probe and the signals stay off.
        d = ConferenceDetector({}, on_change=lambda a, r: None, windows=True, processes=lambda names: [],
                               capture_users=lambda ignore: [], window_titles=lambda patterns: [],
                               camera_users=lambda ignore: [])
        with patch.dict(sys.modules, {"winreg": None}), self.assertLogs(level="WARNING"):
            d.poll()
        self.assertFalse(d.active)

    def test_windows_microphone_without_app_is_no_conference(self):
        reg = FakeRegistry({
            f"{STORE}\\microphone\\MSTeams_8wekyb3d8bbwe": in_use(),
        })
        d = self.detector(reg, processes=lambda names: [])
        d.poll()
        self.assertFalse(d.active)
        self.assertEqual(d.state()["signals"]["microphone"]["sources"], [])

    def test_windows_microphone_from_capture_sessions(self):
        # Newer Windows 11 no longer updates the consent store; the live capture sessions still show the call.
        seen = []
        d = self.detector(FakeRegistry({}), capture_users=lambda ignore: seen.append(ignore) or ["ms-teams.exe"],
                          processes=lambda names: ["ms-teams"])
        d.poll()
        self.assertTrue(d.active)
        self.assertEqual(d.state()["signals"]["microphone"]["sources"], ["ms-teams.exe"])
        self.assertEqual(seen, [["VibeVoice"]])

    def test_windows_teams_in_a_browser_counts(self):
        titles = []
        d = self.detector(FakeRegistry({}), capture_users=lambda ignore: ["firefox.exe"],
                          processes=lambda names: [],
                          window_titles=lambda patterns: titles.append(patterns) or shown("Chat | Microsoft Teams")(patterns))
        d.poll()
        self.assertTrue(d.active)
        self.assertEqual(d.state()["reasons"], ["microphone"])
        self.assertIn(conference.DEFAULTS["window_titles"], titles)

    def test_windows_call_goes_on_when_the_teams_tab_goes_to_the_back(self):
        mics, titles = [["firefox.exe"]], [["Chat | Microsoft Teams"]]
        d = self.detector(FakeRegistry({}), capture_users=lambda ignore: mics[0],
                          processes=lambda names: [], window_titles=lambda patterns: shown(*titles[0])(patterns))
        d.poll()
        self.assertTrue(d.active)
        titles[0] = []                 # another tab in front: the title no longer says Teams
        d.poll()
        self.assertEqual(d.state()["signals"]["microphone"]["sources"], ["firefox.exe"])
        mics[0] = []                   # call over, microphone closed
        d.poll()
        self.assertEqual(d.state()["signals"]["microphone"]["sources"], [])
        mics[0] = ["firefox.exe"]      # later dictation in the browser, no Teams: no call
        d.poll()
        self.assertEqual(d.state()["signals"]["microphone"]["sources"], [])

    def test_windows_call_retains_call_mics_during_transient_capture_failure(self):
        mics, titles = [["firefox.exe"]], [["Chat | Microsoft Teams"]]
        fail_capture = [False]

        def capture(ignore):
            if fail_capture[0]:
                raise OSError("transient audio service failure")
            return mics[0]

        d = self.detector(FakeRegistry({}), capture_users=capture,
                          processes=lambda names: [], window_titles=lambda patterns: shown(*titles[0])(patterns))
        d.poll()
        self.assertTrue(d.active)
        self.assertEqual(d.state()["signals"]["microphone"]["sources"], ["firefox.exe"])

        # Tab goes to background, then capture probe transiently fails
        titles[0] = []
        fail_capture[0] = True
        with self.assertLogs(level="WARNING") as logs:
            d.poll()
        self.assertEqual(len([line for line in logs.output if "audio capture sessions" in line]), 1)
        self.assertEqual(d.state()["signals"]["microphone"]["sources"], ["firefox.exe"])

        # Probe recovers while still in background tab
        fail_capture[0] = False
        d.poll()
        self.assertEqual(d.state()["signals"]["microphone"]["sources"], ["firefox.exe"])
        self.assertTrue(d.active)

    def test_windows_browser_microphone_without_meeting_window_is_no_conference(self):
        d = self.detector(FakeRegistry({}), capture_users=lambda ignore: ["firefox.exe"],
                          processes=lambda names: [], window_titles=lambda patterns: [])
        d.poll()
        self.assertFalse(d.active)

    def test_windows_meeting_window_shows_in_processes_signal(self):
        d = self.detector(FakeRegistry({}), {"signals": {"processes": True}}, processes=lambda names: [],
                          window_titles=shown("Chat | Microsoft Teams"))
        d.poll()
        self.assertEqual(d.state()["signals"]["processes"]["sources"], ["Microsoft Teams window"])

    def test_windows_broken_capture_probe_counts_as_off(self):
        def broken(ignore):
            raise OSError("no audio service")
        d = self.detector(FakeRegistry({}), capture_users=broken, processes=lambda names: ["ms-teams"])
        with self.assertLogs(level="WARNING") as logs:
            d.poll()
            d.poll()
        self.assertFalse(d.active)
        self.assertEqual(len([line for line in logs.output if "audio capture sessions" in line]), 1)

    def test_windows_firefox_screen_share_counts(self):
        titles = []
        d = self.detector(FakeRegistry({}), processes=lambda names: [],
                          window_titles=lambda patterns: titles.append(patterns) or
                          shown("Firefox — Sharing Indicator", "Some page — Mozilla Firefox")(patterns))
        d.poll()
        self.assertTrue(d.active)
        self.assertEqual(d.state()["reasons"], ["screen_share"])
        self.assertEqual(d.state()["signals"]["screen_share"]["sources"], ["Sharing Indicator window"])
        self.assertIn(conference.DEFAULTS["share_indicators"], titles)

    def test_windows_chrome_screen_share_counts(self):
        d = self.detector(FakeRegistry({}), processes=lambda names: [],
                          window_titles=shown("meet.google.com is sharing your screen."))
        d.poll()
        self.assertEqual(d.state()["reasons"], ["screen_share"])

    def test_windows_screen_share_off_is_not_probed(self):
        titles = []
        d = self.detector(FakeRegistry({}), {"signals": {"screen_share": False}}, processes=lambda names: [],
                          window_titles=lambda patterns: titles.append(patterns) or [])
        d.poll()
        self.assertNotIn(conference.DEFAULTS["share_indicators"], titles)

    def test_windows_video_call_in_any_app_counts(self):
        # Camera and microphone together are a call, whatever the app: no meeting app needed.
        seen = []
        d = self.detector(FakeRegistry({}), capture_users=lambda ignore: ["firefox.exe"],
                          camera_users=lambda ignore: seen.append(ignore) or ["firefox.exe"],
                          processes=lambda names: [])
        d.poll()
        self.assertTrue(d.active)
        self.assertEqual(d.state()["reasons"], ["microphone", "camera"])
        self.assertEqual(seen, [["VibeVoice"]])

    def test_windows_camera_alone_is_no_conference(self):
        d = self.detector(FakeRegistry({}), camera_users=lambda ignore: ["WindowsCamera.exe"],
                          processes=lambda names: [])
        d.poll()
        self.assertFalse(d.active)

    def test_windows_broken_camera_probe_counts_as_off(self):
        def broken(ignore):
            raise OSError("no media foundation")
        d = self.detector(FakeRegistry({}), capture_users=lambda ignore: ["firefox.exe"], camera_users=broken,
                          processes=lambda names: [])
        with self.assertLogs(level="WARNING") as logs:
            d.poll()
            d.poll()
        self.assertFalse(d.active)
        self.assertEqual(len([line for line in logs.output if "camera activity" in line]), 1)

    def test_windows_microphone_alone_counts_when_app_not_required(self):
        reg = FakeRegistry({
            f"{STORE}\\microphone\\MSTeams_8wekyb3d8bbwe": in_use(),
        })
        d = self.detector(reg, {"microphone_needs_app": False}, processes=lambda names: [])
        d.poll()
        self.assertTrue(d.active)
        self.assertEqual(d.state()["reasons"], ["microphone"])
        self.assertEqual(d.state()["signals"]["microphone"]["sources"], ["MSTeams"])


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class WebhookTest(unittest.TestCase):
    def test_payload(self):
        sent = []
        with patch.object(conference.urllib.request, "urlopen",
                          side_effect=lambda req, timeout: sent.append((req, timeout)) or FakeResponse()):
            self.assertEqual(conference.post_webhook(WEBHOOK, "on", ["camera"]), 200)
        req, timeout = sent[0]
        body = json.loads(req.data)
        self.assertEqual((req.get_method(), req.get_header("Content-type"), timeout), ("POST", "application/json", 10))
        self.assertEqual((body["state"], body["reasons"]), ("on", ["camera"]))
        self.assertIn("host", body)
        self.assertIn("T", body["time"])

    def test_retries_and_never_logs_the_secret(self):
        calls = []

        def fail(req, timeout):
            calls.append(1)
            raise OSError(f"refused: {WEBHOOK}")
        with patch.object(conference.urllib.request, "urlopen", side_effect=fail), \
             self.assertLogs(level="WARNING") as logs:
            conference.send_webhook(WEBHOOK, "off", [], sleep=lambda s: None).join(5)
        self.assertEqual(len(calls), 3)
        text = "\n".join(logs.output)
        self.assertNotIn("PLACEHOLDER-ID", text)
        self.assertIn("https://ha.example.invalid/…", text)

    def test_newer_state_supersedes_pending_retries(self):
        posted = []
        started_first_post = threading.Event()
        release_first_post = threading.Event()

        def mock_post(url, state, reasons):
            posted.append(state)
            if state == "on":
                started_first_post.set()
                release_first_post.wait(5)
                raise OSError("failed to send on")

        dispatcher = conference.WebhookDispatcher(post=mock_post, attempts=3, sleep=lambda s: None)
        task1 = dispatcher.send(WEBHOOK, "on", ["camera"])
        started_first_post.wait(5)
        # While "on" is in progress / failing, queue a newer "off" state
        task2 = dispatcher.send(WEBHOOK, "off", [])
        release_first_post.set()

        task1.join(5)
        task2.join(5)
        dispatcher.stop()

        # "on" was attempted once; its pending retries were superseded by "off"
        self.assertEqual(posted, ["on", "off"])

    def test_conference_payload_carries_type(self):
        sent = []
        with patch.object(conference.urllib.request, "urlopen",
                          side_effect=lambda req, timeout: sent.append(req) or FakeResponse()):
            conference.post_webhook(WEBHOOK, "off", [])
        self.assertEqual(json.loads(sent[0].data)["type"], "conference")

    def test_event_body_is_flat(self):
        body = conference.event_body("drink", kind="coffee", ml=200)
        self.assertEqual((body["type"], body["kind"], body["ml"]), ("drink", "coffee", 200))
        self.assertIn("host", body)
        self.assertIn("T", body["time"])

    def test_events_are_not_superseded_by_states(self):
        posted = []
        started_first_post = threading.Event()
        release_first_post = threading.Event()

        def post_state(url, state, reasons):
            posted.append(state)

        def post_event(url, body):
            if not started_first_post.is_set():
                started_first_post.set()
                release_first_post.wait(5)
                raise OSError("down")
            posted.append(body["type"])

        dispatcher = conference.WebhookDispatcher(post=post_state, attempts=3, sleep=lambda s: None,
                                                  post_event=post_event)
        task1 = dispatcher.send_event(WEBHOOK, {"type": "drink"})
        started_first_post.wait(5)
        # While "drink" is in progress / failing, queue a newer conference state
        task2 = dispatcher.send(WEBHOOK, "on", [])
        release_first_post.set()

        task1.join(5)
        task2.join(5)
        dispatcher.stop()
        self.assertEqual(posted, ["drink", "on"])

    def test_backoff_deadline_loop_rewait_when_not_superseded(self):
        timeline = [100.0, 100.0, 100.5, 102.5]

        def fake_monotonic():
            return timeline.pop(0) if timeline else 103.0

        wait_timeouts = []
        failed = []

        def post_event(url, body):
            if not failed:
                failed.append(1)
                raise OSError("down")

        dispatcher = conference.WebhookDispatcher(post_event=post_event, attempts=2)
        real_cond = dispatcher._cond
        orig_wait = real_cond.wait

        def mock_wait(timeout=None):
            wait_timeouts.append(timeout)
            return orig_wait(timeout=0.001)

        with patch.object(conference.time, "monotonic", side_effect=fake_monotonic), \
             patch.object(real_cond, "wait", side_effect=mock_wait):
            task = dispatcher.send_event(WEBHOOK, {"type": "drink"})
            task.join(5)
            dispatcher.stop()

        backoff_timeouts = [t for t in wait_timeouts if t is not None]
        self.assertEqual(len(backoff_timeouts), 2)
        self.assertAlmostEqual(backoff_timeouts[0], 2.0)
        self.assertAlmostEqual(backoff_timeouts[1], 1.5)

    def test_detector_send_event_needs_a_url(self):
        detector = conference.ConferenceDetector()
        detector.configure({"webhook_url": ""})
        with patch.object(conference, "send_event") as send:
            self.assertIsNone(detector.send_event("drink", ml=1))
            detector.configure({"webhook_url": WEBHOOK})
            detector.send_event("drink", ml=1)
        send.assert_called_once_with(WEBHOOK, "drink", ml=1)

    def test_redact_drops_credentials_and_path(self):
        self.assertEqual(conference.redact("https://user:pw@ha.example.invalid:8123/api/webhook/x"),
                         "https://ha.example.invalid:8123/…")

    def test_format_error_never_includes_url(self):
        secret_url = "https://ha.example.invalid/api/webhook/SUPER_SECRET"
        err_http = conference.urllib.error.HTTPError(secret_url, 404, "Not Found", {}, None)
        self.assertEqual(conference.format_error(err_http), "HTTPError 404 Not Found")
        self.assertNotIn("SUPER_SECRET", conference.format_error(err_http))
        err_http.close()

        err_url = conference.urllib.error.URLError(ConnectionRefusedError(f"connection refused to {secret_url}"))
        self.assertEqual(conference.format_error(err_url), "URLError (ConnectionRefusedError)")
        self.assertNotIn("SUPER_SECRET", conference.format_error(err_url))

        err_os = OSError(f"Failed to connect to {secret_url}")
        self.assertEqual(conference.format_error(err_os), "OSError")
        self.assertNotIn("SUPER_SECRET", conference.format_error(err_os))


class ConfigTest(unittest.TestCase):
    def test_defaults_filled_without_overwriting(self):
        from src.library import fill_defaults
        config = fill_defaults({"global_interval": 60, "conference": {"signals": {"camera": False}, "ignore_apps": []}})
        conf = config["conference"]
        self.assertEqual(conf["signals"], {"screen_share": True, "microphone": True, "camera": False,
                                           "processes": False, "do_not_disturb": True})
        self.assertEqual(conf["ignore_apps"], [])
        self.assertEqual(conf["webhook_url"], "")
        self.assertEqual(conf["end_grace_seconds"], 60)
        self.assertTrue(conf["microphone_needs_app"])

    def test_conference_config_coercion_and_validation(self):
        from src.config import validate_config
        config = {
            "global_interval": 60,
            "conference": {
                "end_grace_seconds": None,
                "signals": {"camera": "true", "microphone": 0},
                "ignore_apps": "not-a-list",
                "webhook_url": 12345,
                "microphone_needs_app": None,
            }
        }
        validate_config(config)
        conf = config["conference"]
        self.assertEqual(conf["end_grace_seconds"], 60)
        self.assertTrue(conf["signals"]["camera"])
        self.assertFalse(conf["signals"]["microphone"])
        self.assertEqual(conf["ignore_apps"], ["VibeVoice"])
        self.assertEqual(conf["webhook_url"], "12345")
        self.assertTrue(conf["microphone_needs_app"])

        for val, expected in [("", True), (False, False), (0, False), (True, True), ("true", True)]:
            c = {"global_interval": 60, "conference": {"microphone_needs_app": val}}
            validate_config(c)
            self.assertIs(c["conference"]["microphone_needs_app"], expected)
        c_missing = {"global_interval": 60, "conference": {}}
        validate_config(c_missing)
        self.assertTrue(c_missing["conference"]["microphone_needs_app"])

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_config_file_is_owner_only(self):
        import src.config as config
        tmp_dir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp_dir, "reminder_config.json")
            with open(path, "w") as f:
                f.write("{}")
            os.chmod(path, 0o644)  # from an older version
            with patch.object(config, "CONFIG_PATH", path):
                config.save_config({"global_interval": 60})
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            os.chmod(path, 0o644)
            with patch.object(config, "CONFIG_PATH", path):
                self.assertIsNotNone(config.load_config())
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
