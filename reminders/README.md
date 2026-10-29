# Reminder library

Every reminder type is one directory here: `reminders/<type>/reminder.html` plus any assets it
needs (CSS, JS, SVG). `src/library.py` lists the types with their metadata. When a reminder is due,
the daemon starts `notifications.py show <type> --settings '<json>'`, which opens the page in a
pywebview window (`src/overlay.py`).

## Window

Every reminder opens as a frameless, fullscreen, focused window (tested on GNOME Wayland: started
from the systemd service, it comes to the front with focus). The page decides how intrusive it is:
eye relax flashes, water shows a calm dark backdrop with three glasses (200, 300, 500 ml): drag one to the "Drink here" circle (it sloshes while carried) or press 1/2/3 to log it.

`Escape` must always close the page (call `api.close()`).

## JavaScript API

The page waits for pywebview, then uses `window.pywebview.api`:

```js
const api = await new Promise(resolve => {
    if (window.pywebview && window.pywebview.api) resolve(window.pywebview.api);
    else window.addEventListener('pywebviewready', () => resolve(window.pywebview.api));
});
```

All methods return promises.

| Method | Returns / does |
|---|---|
| `get_context()` | `{type, settings, now}`. `settings` = this type's config entry (e.g. `{relax_duration: 20, flash_frequency: 2}` for eye relax), `now` = ISO local time |
| `close()` | closes the window and ends the process |
| `snooze(minutes)` | hides the window and shows it again after `minutes` |
| `save_rating(rating)` | posture: appends `YYYY-MM-DD HH:MM:SS - Rating: <1-5>` to the ratings file |
| `get_ratings(days)` | posture: `[{time: "YYYY-MM-DD HH:MM:SS", rating: 1-5}, ...]` of the last `days` days, oldest first |
| `log_water(ml)` | water: appends `YYYY-MM-DD HH:MM:SS <ml>` to the water log (`ml` a whole number, 1-2000), returns `{today_ml, goal_ml}` |
| `get_water_today()` | water: `{today_ml: <ml logged today>, goal_ml: <settings.daily_goal_ml>}`. Old log lines with only a timestamp count as 250 ml |

## Types and settings

| Type | Settings (config key → meaning) |
|---|---|
| `eye_relax` | `relax_duration` s, `flash_frequency` Hz |
| `posture` | `wait_duration` s before the rating buttons react (stops accidental key presses) |
| `water` | `daily_goal_ml` ml per day (default 2000) |

Each type's config entry also has `enabled` and `reminders` (minutes within the global interval).

## Testing a page without Python

Open the HTML in a browser with a stub before the page script, e.g.
`window.pywebview = {api: {get_context: async () => ({type: 'water', settings: {daily_goal_ml: 2000}, now: new Date().toISOString()}), close: async () => {}, ...}}`.
