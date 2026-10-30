"""Run: python -m unittest tests.test_conference"""
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

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
                                  processes=lambda names: list(self.apps), dnd=lambda: self.dnd)


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

    def test_camera_counts_without_app(self):
        self.p.apps = []
        self.p.video = ["firefox"]
        self.d.poll()
        self.assertEqual(self.d.state()["reasons"], ["camera"])

    def test_disabled_microphone_does_not_probe_processes(self):
        self.p.apps = []
        self.p.nodes = [MIC_FIREFOX]
        self.p.video = ["firefox"]
        probed = []
        d = ConferenceDetector(
            {"signals": {"microphone": False, "camera": True, "processes": False}},
            clock=lambda: self.p.now, on_change=lambda a, r: self.p.changes.append((a, r)),
            read_pipewire=lambda: self.p.nodes, video_users=lambda: self.p.video,
            processes=lambda names: probed.append(names) or [], dnd=lambda: self.p.dnd
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
        self.d.poll()
        self.assertEqual(self.d.state()["signals"]["camera"]["sources"], ["chrome"])

    def test_missing_pw_dump_logged_once(self):
        def missing():
            raise FileNotFoundError("pw-dump")
        d = ConferenceDetector({}, clock=lambda: self.p.now, on_change=lambda a, r: None, read_pipewire=missing,
                               video_users=lambda: [], dnd=lambda: False)
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
        self.assertEqual(state["screen_share_source"], "unavailable")
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
        d = ConferenceDetector({}, on_change=lambda a, r: None, windows=True, processes=lambda names: [])
        with self.assertLogs(level="WARNING"):
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
