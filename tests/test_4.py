#!/usr/bin/env python3
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GtkLayerShell

class LayerShellOrFallback(Gtk.Window):
    def __init__(self):
        super().__init__(title="Overlay Test 4")
        self.set_decorated(False)
        self.connect("destroy", Gtk.main_quit)
        self.connect("key-press-event", self.on_key)

        label = Gtk.Label()
        label.set_markup(
            "<span font='30' foreground='white'>TEST 4\nLayer Shell if supported,\notherwise fullscreen fallback</span>"
        )
        label.set_halign(Gtk.Align.CENTER)
        label.set_valign(Gtk.Align.CENTER)
        self.add(label)

        css = b"window { background: rgba(80, 0, 0, 0.88); }"
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        if GtkLayerShell.is_supported():
            print("Layer Shell supported")
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
            GtkLayerShell.set_namespace(self, "overlay-test")
        else:
            print("Layer Shell NOT supported, using normal fullscreen fallback")
            self.fullscreen()
            self.set_keep_above(True)

    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()

win = LayerShellOrFallback()
win.show_all()
Gtk.main()