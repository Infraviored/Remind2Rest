#!/usr/bin/env python3

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")
from gi.repository import Gtk, AppIndicator3
import os
import json
import subprocess
import webbrowser


class Remind2RestIndicator:
    def __init__(self):
        self.indicator = AppIndicator3.Indicator.new(
            "Remind2Rest",
            "appointment-soon",  # Default system icon
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.create_menu()

    def create_menu(self):
        menu = Gtk.Menu()

        # Status item
        self.status_item = Gtk.MenuItem(label="Status: Checking...")
        self.status_item.set_sensitive(False)
        menu.append(self.status_item)

        # Separator
        menu.append(Gtk.SeparatorMenuItem())

        # Start/Stop toggle
        self.toggle_item = Gtk.MenuItem(label="Start/Stop Service")
        self.toggle_item.connect("activate", self.toggle_service)
        menu.append(self.toggle_item)

        # Open Web Interface
        item_web = Gtk.MenuItem(label="Open Web Interface")
        item_web.connect("activate", self.open_web_interface)
        menu.append(item_web)

        # Separator
        menu.append(Gtk.SeparatorMenuItem())

        # Quit
        item_quit = Gtk.MenuItem(label="Quit")
        item_quit.connect("activate", self.quit)
        menu.append(item_quit)

        menu.show_all()
        self.indicator.set_menu(menu)

        # Update status initially and every 5 seconds
        self.update_status()
        GLib.timeout_add_seconds(5, self.update_status)

    def update_status(self):
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", "Remind2Rest"],
                capture_output=True,
                text=True,
            )
            status = "Running" if result.stdout.strip() == "active" else "Stopped"
            self.status_item.set_label(f"Status: {status}")
        except Exception as e:
            self.status_item.set_label("Status: Unknown")
        return True

    def toggle_service(self, _):
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", "Remind2Rest"],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip() == "active":
                subprocess.run(["systemctl", "--user", "stop", "Remind2Rest"])
            else:
                subprocess.run(["systemctl", "--user", "start", "Remind2Rest"])
            self.update_status()
        except Exception as e:
            dialog = Gtk.MessageDialog(
                None,
                0,
                Gtk.MessageType.ERROR,
                Gtk.ButtonsType.OK,
                "Failed to toggle service",
            )
            dialog.format_secondary_text(str(e))
            dialog.run()
            dialog.destroy()

    def open_web_interface(self, _):
        webbrowser.open("http://localhost:5000")

    def quit(self, _):
        Gtk.main_quit()


def main():
    Remind2RestIndicator()
    Gtk.main()


if __name__ == "__main__":
    main()
