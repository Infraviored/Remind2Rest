"""Run: python -m unittest tests.test_conference"""
import json
import os
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


class ProcTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

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
        self.changes = []

    def detector(self, **settings):
        return ConferenceDetector(settings, clock=lambda: self.now, on_change=lambda a, r: self.changes.append((a, r)),
                                  read_pipewire=lambda: self.nodes, video_users=lambda: self.video,
                                  processes=lambda names: [], dnd=lambda: self.dnd)


class DetectorTest(unittest.TestCase):
    def setUp(self):
        self.p = Probes()
        self.d = self.p.detector()

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

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_config_file_is_owner_only(self):
        import src.config as config
        path = os.path.join(tempfile.mkdtemp(), "reminder_config.json")
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


if __name__ == "__main__":
    unittest.main()
