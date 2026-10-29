import copy

# One entry per reminder type; the page lives in reminders/<type>/reminder.html (see reminders/README.md).
# icon: Material Symbols name for the settings window, symbolic_icon: GNOME icon for the top bar.
# defaults["every"]: how often the type fires (minutes). The settings window spreads the types over the
# cycle (static/js/distribute.js) and writes the result to config[type]["reminders"], which the daemon reads.
LIBRARY = {
    "eye_relax": {
        "title": "Eye Relax",
        "icon": "visibility",
        "symbolic_icon": "view-reveal-symbolic",
        "color": "#818cf8",
        "defaults": {"enabled": True, "every": 20, "reminders": [0, 20, 40], "relax_duration": 20, "flash_frequency": 2.0},
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
        "defaults": {"enabled": True, "every": 20, "reminders": [10, 30, 50], "wait_duration": 3.0},
        "fields": [{"key": "wait_duration", "label": "Wait (s)"}],
    },
    "water": {
        "title": "Water",
        "icon": "water_drop",
        "symbolic_icon": "weather-showers-symbolic",
        "color": "#38bdf8",
        "defaults": {"enabled": False, "every": 40, "reminders": [], "daily_goal_ml": 2000},
        "fields": [{"key": "daily_goal_ml", "label": "Goal (ml/day)"}],
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
    """The type's settings as the page sees them: defaults filled in, without the scheduling keys."""
    settings = {**LIBRARY[module]["defaults"], **(config_entry or {})}
    for key in ("enabled", "reminders", "every"):
        settings.pop(key, None)
    return settings
