"""Whether the desktop session is locked.

Linux: read over D-Bus without a subprocess (about 3 ms). Works from the systemd user service, which
has no XDG_SESSION_ID: logind names the user's display session.
Windows: the input desktop is the Winlogon desktop while the screen is locked, and a user process
cannot open it then.
Returns None where it cannot tell; the caller then treats it as unlocked."""
import logging
import os

try:
    from gi.repository import Gio, GLib
except ImportError:
    Gio = None

_WINDOWS = os.name == "nt"
_TIMEOUT_MS = 1000
_DESKTOP_SWITCHDESKTOP = 0x0100


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


def _windows_locked():
    """True while the lock screen (or another secure desktop, e.g. a UAC prompt) has the input."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.OpenInputDesktop.restype = wintypes.HANDLE
        user32.OpenInputDesktop.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        user32.CloseDesktop.argtypes = (wintypes.HANDLE,)
        desktop = user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
        if not desktop:
            return True
        user32.CloseDesktop(desktop)
        return False
    except Exception as e:
        logging.debug(f"Windows lock probe failed: {e}")
        return None


def is_locked():
    if Gio is None:
        return _windows_locked() if _WINDOWS else None
    any_success = False
    for probe in (_logind_locked, _screensaver_active):
        try:
            if probe():
                return True
            any_success = True
        except Exception as e:
            name = getattr(probe, "__name__", str(probe))
            logging.debug(f"Lock probe {name} failed: {e}")
    return False if any_success else None
