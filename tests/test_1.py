#!/usr/bin/env python3
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk

class FullscreenInfo(Gtk.Window):
    def __init__(self):
        super().__init__(title="Overlay Test 1")
        self.set_decorated(False)
        self.fullscreen()
        self.connect("destroy", Gtk.main_quit)
        self.connect("key-press-event", self.on_key)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)

        label = Gtk.Label()
        label.set_markup(
            "<span font='36' foreground='white'>TEST 1\nPlain fullscreen GTK window</span>"
        )

        box.pack_start(label, False, False, 0)
        self.add(box)

        css = b"""
        window {
            background: #000000;
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

win = FullscreenInfo()
win.show_all()
Gtk.main()