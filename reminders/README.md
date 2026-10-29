# Reminder library

Every reminder type is one directory here: `reminders/<type>/reminder.html` plus any assets it
needs (CSS, JS, SVG). `src/library.py` lists the types with their metadata. When a reminder is due,
the daemon starts `notifications.py show <type> --settings '<json>'`, which opens the page in a
pywebview window (`src/overlay.py`).

## Window

Every reminder opens as a frameless, fullscreen, focused window (tested on GNOME Wayland: started
from the systemd service, it comes to the front with focus). The page decides how intrusive it is:
eye relax flashes, water shows a shelf of three glasses (200, 300, 500 ml) and a carafe that fills up to the daily goal: tip a glass into the carafe (it sloshes while carried) or press 1/2/3 to log it.
Stretch walks through four moves with an animated figure, breathing paces 4-7-8 breaths with a
growing and shrinking circle, fresh air shows an open window. Pages close right after the user's
action or when their sequence ends.

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
| `posture` | none; the rating buttons react at once (older configs may still hold `wait_duration`, it is removed on load) |
| `water` | `daily_goal_ml` ml per day (default 2000) |
| `stretch` | `move_duration` s per move (default 20); four moves, then the page closes |
| `breathing` | `cycles` 4-7-8 breaths (default 3); closes after the last exhale |
| `airing` | none. "Done" closes, "Later" snoozes 10 min |

Each type's config entry also has `enabled`, `every` (minutes between two reminders of the type) and
`reminders` (minutes within the global interval, computed from `every` by the settings window).

## Adding a type

1. Add an entry to `LIBRARY` in `src/library.py`: `title`, `icon` (Material Symbols name for the
   settings window), `symbolic_icon` (GNOME icon for the top bar), `color`, `defaults` (with
   `enabled`, `every`, `reminders` and the type's settings) and `fields` (settings shown in its card).
2. Add `reminders/<type>/reminder.html`, using `../common.css` and `../common.js`.

The settings window, the scheduler and the GNOME top bar pick the type up from the library. The
daemon's `STATUS` reply lists the enabled types as `types: [{key, title}]`; the top bar builds its
"<title> now" items from it. When water is enabled, `STATUS` also has `water_today_ml` and
`water_goal_ml`, which the top bar shows as "Water today: 1200 / 2000 ml".

## Testing a page without Python

Open the HTML in a browser with a stub before the page script, e.g.
`window.pywebview = {api: {get_context: async () => ({type: 'water', settings: {daily_goal_ml: 2000}, now: new Date().toISOString()}), close: async () => {}, ...}}`.
