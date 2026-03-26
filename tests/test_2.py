#!/usr/bin/env python3
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk

class TransparentOverlay(Gtk.Window):
    def __init__(self):
        super().__init__(title="Overlay Test 2")
        self.set_decorated(False)
        self.fullscreen()
        self.set_app_paintable(True)
        self.connect("destroy", Gtk.main_quit)
        self.connect("key-press-event", self.on_key)

        outer = Gtk.Box()
        outer.set_halign(Gtk.Align.FILL)
        outer.set_valign(Gtk.Align.FILL)

        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        center.set_halign(Gtk.Align.CENTER)
        center.set_valign(Gtk.Align.CENTER)

        title = Gtk.Label()
        title.set_markup("<span font='34' foreground='white'><b>TEST 2</b></span>")

        msg = Gtk.Label()
        msg.set_markup(
            "<span font='22' foreground='white'>Semi-transparent fullscreen overlay\nPress Esc to close</span>"
        )

        center.pack_start(title, False, False, 0)
        center.pack_start(msg, False, False, 0)
        outer.add(center)
        self.add(outer)

        css = b"""
        window {
            background: rgba(0, 0, 0, 0.72);
        }
        label {
            text-shadow: 0 1px 2px rgba(0,0,0,0.8);
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()

win = TransparentOverlay()
win.show_all()
Gtk.main()