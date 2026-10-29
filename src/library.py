import copy

# One entry per reminder type; the page lives in reminders/<type>/reminder.html (see reminders/README.md).
# icon: Material Symbols name for the settings window, symbolic_icon: GNOME icon for the top bar.
LIBRARY = {
    "eye_relax": {
        "title": "Eye Relax",
        "icon": "visibility",
        "symbolic_icon": "view-reveal-symbolic",
        "color": "#818cf8",
        "defaults": {"enabled": True, "reminders": [20, 40], "relax_duration": 20, "flash_frequency": 2.0},
        "fields": [
            {"key": "relax_duration", "label": "Duration (s)"},
            {"key": "flash_frequency", "label": "Flash (Hz)"},
        ],
    },
    "posture": {
        "title": "Posture",
        "icon": "accessibility_new",
        "symbolic_icon": "preferences-desktop-accessibility-symbolic",
        "color": "#2dd4bf",
        "defaults": {"enabled": True, "reminders": [0, 30], "wait_duration": 3.0},
        "fields": [{"key": "wait_duration", "label": "Wait (s)"}],
    },
    "water": {
        "title": "Water",
        "icon": "water_drop",
        "symbolic_icon": "weather-showers-symbolic",
        "color": "#38bdf8",
        "defaults": {"enabled": False, "reminders": [], "daily_goal": 8},
        "fields": [{"key": "daily_goal", "label": "Glasses / day"}],
    },
}


def fill_defaults(config):
    """Add missing types and keys from the library, so configs from older versions keep working."""
    config.setdefault("global_interval", 60)
    for key, entry in LIBRARY.items():
        module = config.setdefault(key, {})
        for name, value in entry["defaults"].items():
            module.setdefault(name, copy.deepcopy(value))
    return config


def page_settings(module, config_entry):
    """The type's settings as the page sees them: defaults filled in, without enabled/reminders."""
    settings = {**LIBRARY[module]["defaults"], **(config_entry or {})}
    settings.pop("enabled", None)
    settings.pop("reminders", None)
    return settings
