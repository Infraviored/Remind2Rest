"""Whether the desktop session is locked, read over D-Bus without a subprocess (about 3 ms).
Works from the systemd user service, which has no XDG_SESSION_ID: logind names the user's display
session. Returns None where it cannot tell (Windows, no D-Bus); the caller then treats it as unlocked."""
import logging

try:
    from gi.repository import Gio, GLib
except ImportError:
    Gio = None

_TIMEOUT_MS = 1000


def _get_property(bus, name, path, interface, prop):
    reply = bus.call_sync(name, path, "org.freedesktop.DBus.Properties", "Get",
                          GLib.Variant("(ss)", (interface, prop)), None, Gio.DBusCallFlags.NONE, _TIMEOUT_MS, None)
    return reply.unpack()[0]


def _logind_locked():
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    _, session_path = _get_property(bus, "org.freedesktop.login1", "/org/freedesktop/login1/user/self",
                                    "org.freedesktop.login1.User", "Display")
    if session_path == "/":
        raise RuntimeError("logind knows no display session")
    return _get_property(bus, "org.freedesktop.login1", session_path,
                         "org.freedesktop.login1.Session", "LockedHint")


def _screensaver_active():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    reply = bus.call_sync("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver",
                          "GetActive", None, None, Gio.DBusCallFlags.NONE, _TIMEOUT_MS, None)
    return reply.unpack()[0]


def is_locked():
    if Gio is None:
        return None
    for probe in (_logind_locked, _screensaver_active):
        try:
            return bool(probe())
        except Exception as e:
            logging.debug(f"Lock probe {probe.__name__} failed: {e}")
    return None
