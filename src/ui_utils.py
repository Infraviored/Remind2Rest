import os
import logging

def update_env_from_systemd():
    if os.name == 'nt':
        return
    try:
        import subprocess
        result = subprocess.run(
            ['systemctl', '--user', 'show-environment'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1.0
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if '=' in line:
                    key, val = line.split('=', 1)
                    if key in ['DISPLAY', 'WAYLAND_DISPLAY', 'XDG_SESSION_TYPE', 'XAUTHORITY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS']:
                        os.environ[key] = val
    except Exception:
        pass

# Initialize environment at module import time
update_env_from_systemd()

IS_WINDOWS = os.name == 'nt'
XDG_SESSION = os.environ.get('XDG_SESSION_TYPE', '').lower()

HAS_GTK = False
if not IS_WINDOWS:
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, Gdk, GLib
        HAS_GTK = True
    except (ImportError, ValueError):
        pass

HAS_TK = False
try:
    import tkinter as tk
    from PIL import ImageTk
    HAS_TK = True
except ImportError:
    pass

# Selection logic
USE_GTK = HAS_GTK and XDG_SESSION == 'wayland'

def setup_tk_fullscreen(root):
    if IS_WINDOWS:
        root.wm_attributes("-topmost", 1)
        root.overrideredirect(True)
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        root.geometry(f"{screen_width}x{screen_height}+0+0")
    else:
        root.attributes('-fullscreen', True)
        root.attributes('-topmost', True)
    root.focus_set()

if HAS_GTK:
    def apply_aggressive_fullscreen(window):
        window.set_decorated(False)
        window.set_keep_above(True)
        window.stick()
        window.fullscreen()
        def bring_forward():
            window.present()
            return False
        GLib.idle_add(bring_forward)

    def apply_css(widget, css):
        screen = Gdk.Screen.get_default()
        if not screen:
            return
        style_provider = Gtk.CssProvider()
        try:
            style_provider.load_from_data(css.encode())
            Gtk.StyleContext.add_provider_for_screen(
                screen, style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        except Exception as e:
            logging.error(f"Error applying CSS: {e}")
else:
    apply_aggressive_fullscreen = None
    apply_css = None
