#!/usr/bin/env python3
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

class AggressiveFullscreen(Gtk.Window):
    def __init__(self):
        super().__init__(title="Overlay Test 3")
        self.set_decorated(False)
        self.set_keep_above(True)
        self.stick()
        self.fullscreen()

        self.connect("destroy", Gtk.main_quit)
        self.connect("key-press-event", self.on_key)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)

        label = Gtk.Label()
        label.set_markup(
            "<span font='34' foreground='white'><b>TEST 3</b>\nKeep-above + present + fullscreen</span>"
        )

        hint = Gtk.Label()
        hint.set_markup(
            "<span font='18' foreground='white'>If another app can still cover this,\nthat is Wayland compositor policy.</span>"
        )

        box.pack_start(label, False, False, 0)
        box.pack_start(hint, False, False, 0)
        self.add(box)

        css = b"window { background: #203040; }"
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        GLib.idle_add(self.bring_forward)

    def bring_forward(self):
        self.present()
        return False

    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()

win = AggressiveFullscreen()
win.show_all()
Gtk.main()