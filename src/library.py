import copy

from src import conference

# One entry per reminder type; the page lives in reminders/<type>/reminder.html (see reminders/README.md).
# icon: Material Symbols name for the settings window, symbolic_icon: GNOME icon for the top bar.
# defaults["every"]: how often the type should fire (minutes). It is only the input of the settings window's
# Auto-arrange button (static/js/distribute.js); the daemon reads config[type]["reminders"], which the user
# can also edit by hand on the timeline.
# auto_close: seconds without input after which a page that waits for the user closes itself; 0 = stays open.
AUTO_CLOSE = {"key": "auto_close", "label": "Close after (s)", "line2": True,
              "title": "Closes the reminder after this many seconds without input; 0 keeps it open"}

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
        "defaults": {"enabled": True, "every": 20, "reminders": [10, 30, 50], "auto_close": 5},
        "fields": [AUTO_CLOSE],
    },
    "water": {
        "title": "Water",
        "icon": "water_drop",
        "symbolic_icon": "weather-showers-symbolic",
        "color": "#38bdf8",
        "defaults": {"enabled": False, "every": 40, "reminders": [], "daily_goal_ml": 2000,
                     "stop_at_goal": True, "auto_close": 0},
        # stop_at_goal: once today's water reaches the goal, no more water reminders until tomorrow.
        "fields": [{"key": "daily_goal_ml", "label": "Goal (ml/day)"}, AUTO_CLOSE,
                   {"key": "stop_at_goal", "label": "Stop at goal", "type": "check",
                    "title": "Once today's goal is reached, no more water reminders until tomorrow"}],
    },
    "stretch": {
        "title": "Stretch",
        "icon": "sports_gymnastics",
        "symbolic_icon": "emoji-body-symbolic",
        "color": "#fb923c",
        "defaults": {"enabled": False, "every": 60, "reminders": [], "move_duration": 20},
        "fields": [{"key": "move_duration", "label": "Per move (s)"}],
    },
    "breathing": {
        "title": "Breathing",
        "icon": "self_improvement",
        "symbolic_icon": "emoji-nature-symbolic",
        "color": "#c084fc",
        "defaults": {"enabled": False, "every": 90, "reminders": [], "cycles": 3},
        "fields": [{"key": "cycles", "label": "Cycles"}],
    },
    "airing": {
        "title": "Fresh Air",
        "icon": "air",
        "symbolic_icon": "weather-windy-symbolic",
        "color": "#4ade80",
        "defaults": {"enabled": False, "every": 120, "reminders": [], "auto_close": 0},
        "fields": [AUTO_CLOSE],
    },
}


# Settings that older versions wrote and that no page reads any more.
RETIRED = {"posture": ["wait_duration"], "water": ["snooze_minutes"], "airing": ["snooze_minutes"]}


def fill_defaults(config):
    """Add missing types and keys from the library, so configs from older versions keep working."""
    config.setdefault("global_interval", 60)
    for key, entry in LIBRARY.items():
        module = config.setdefault(key, {})
        for name in RETIRED.get(key, []):
            module.pop(name, None)
        for name, value in entry["defaults"].items():
            module.setdefault(name, copy.deepcopy(value))
    conference.fill_defaults(config)
    return config


def page_settings(module, config_entry):
    """The type's settings as the page sees them: defaults filled in, without the scheduling keys."""
    settings = {**LIBRARY[module]["defaults"], **(config_entry or {})}
    for key in ("enabled", "reminders", "every"):
        settings.pop(key, None)
    return settings
