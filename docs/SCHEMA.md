# Macro JSON reference

A macro is one JSON object in one file. `MacroEngine.load_all()` reads every `*.json`
found recursively under the macros directory — `%APPDATA%/Macroscope/macros/`, or
`macros/` inside the project when `APPDATA` is unset (`engine/paths.py`). That
directory is user data and is not tracked, which is why this reference lives in
`docs/` rather than beside the macros.

Everything here is read out of `engine/macro_engine.py` (validation and macro-level
fields), `engine/action_runner.py` (the handlers and their optional fields),
`engine/humanize.py` and `engine/rect_detector.py`. Where the GUI editor pre-fills a
different value from the engine's own default, both are given: the editor always
writes the field explicitly, so what it shows is what runs.

`name`, `actions`, `stall_timeout_ms` and `humanize` are validated. Other unknown keys
— at macro level and inside an action — are accepted and ignored, but a macro-level key
the form does not show survives being opened and saved in the GUI editor. An unknown
action `type` is rejected at load.

## Macro-level fields

| Field | Type | Default | What it does |
|---|---|---|---|
| `name` | string | **required** | Also the filename (`<name>.json`) and the key the engine indexes by. Must be unique across the whole tree: `load_all` keys by name, so a duplicate in another folder silently replaces the first one loaded. |
| `actions` | list | **required** | Must be a list. Validated recursively, including branch lists. |
| `description` | string | `""` | Shown under the macro name in the list, truncated to 40 characters. |
| `trigger` | object | none | `{"type": "hotkey", "keys": ["ctrl", "F1"]}`. Registered only when `type` is `"hotkey"` and `keys` is non-empty. Keys are joined with `+` and handed to the `keyboard` library. The hotkey **toggles**: it starts the macro, or stops it if it is already running. Registration happens in `gui/app.py`, so a hotkey does nothing when the engine is driven from a script. |
| `loop` | bool | `false` | Repeat the action list until stopped. Without it the list runs once. |
| `loop_delay_ms` | int | `0` | Pause between iterations. Jittered (see `humanize`). |
| `background` | bool | `false` | Route input through `PostMessage` instead of the real cursor. Needs a window that resolves; if it does not, the engine logs `falling back to foreground mode` and uses the real cursor. |
| `target_window` | string | `""` | Substring of the window title, case-insensitive. Resolved **once** at the start of a run, so identically-titled windows cannot be flipped between mid-run. A substring is not an identity: `"Onmyoji"` also matched a YouTube tab, and the macro posted a click into the browser. So candidates are **ranked** — a window whose title is its own name over one showing content the user named, then an exact title, then the shortest title — and when several still match, every candidate is logged with its window class. |
| `target_class` | string | none | Win32 window class, written by the editor's window picker. Filters the title search, and it is the reliable signal: the class outlives the handle, so next session the stale `target_hwnd` is dropped and this is what stops the title search picking a browser tab. A class that matches nothing is **ignored rather than enforced** — an application that changes it in an update must not silently stop being found. |
| `target_hwnd` | int | none | Exact handle, written by the editor's window picker. Preferred over the title while the handle is still valid; a handle saved in a previous session is stale, and the title search takes over. Not worth hand-writing. |
| `stall_timeout_ms` | int | `300000` (5 min) | Stop a **looping** macro that has been *sending input* this long without recognising anything it looks for, and log why. It exists so there is a safety stop that needs no template: it catches a verification prompt, a disconnect, maintenance and a UI change alike, where a per-game CAPTCHA template catches one of those and only if the user could capture it. Deliberately far longer than any battle or loading screen — it is not a progress timeout. `0` disables it. Ignored when `loop` is false, and inert for a macro that has no recognising action to judge by (see below). |
| `humanize` | `false` \| `true` \| object | `true` | Scatter timing and click position. It exists because before it every delay was a fixed constant and every click landed on the exact centre pixel of the match, which is a metronome hitting one pixel forever. `false` turns it off — reasonable for a macro that must hit an exact pixel. An object tunes it: `{"timing_pct": 0.15, "click_px": 3}` are the defaults; `timing_pct` is a fraction (so a short `wait` and a long poll both stay sensible) and `click_px` is a radius in pixels. Either may be `0` on its own. **This does not make automation undetectable.** It removes the obvious signature and no more. |

Both are checked at load: a `stall_timeout_ms` that is not a number, or a `humanize`
that is neither a boolean nor an object of numbers, is rejected by name. They are
otherwise only read while a macro is already running, so a wrong type used to surface
as a `TypeError` minutes into a run that had been working.

### What the stall guard judges

The condition is **clicking blind**, not merely matching nothing:

- A macro that recognises nothing and sends no input is a watcher waiting for
  something to appear. That is a normal and safe thing to be, and it is left alone
  however long it waits.
- A macro that keeps clicking at a screen it cannot recognise is the case this exists
  for, and it is stopped.
- A macro with no recognising action at all — nothing but coordinates, keys and
  waits — recognises nothing by construction, so the guard has no signal and never
  arms. `pixel_wait`, `pixel_check`, `image_wait`, `image_check`, `find_and_click`,
  `find_all_and_click` and `find_rects_and_click` are what count, including inside a
  branch list.

A stall does **not** cancel the rest of a sequential folder run, unlike the user
pressing Stop. One macro losing track of its screen is no reason to abandon the
others.

### What jitter touches

`wait.ms` and `loop_delay_ms` are scattered by `timing_pct`. Nothing else is: a
`poll_ms`, a `timeout_ms`, a `click_delay`, a typing `interval` and a `duration` are
rates and limits the macro author chose, not pauses meant to look human.

A click is scattered by up to `click_px`, then kept inside the client area — without
that clamp, 3 px on a click at `xp: 0.999` left a 1280×720 client area 39 times out of
60, where a posted click outside the window is silently dropped and the real cursor
would sit on a pyautogui failsafe corner. When the click came from a match
(`find_and_click`, `find_all_and_click`, `find_rects_and_click`), the radius is capped
at a quarter of the *matched* element's smaller side — the size it matched at, not the
size of the template file, because matching is scale-aware and a 40×40 template can
match a 20×20 element on a half-size window.

Keys beginning with `_` are runtime-only and stripped when a macro is saved. The
engine adds `_folder` (the macro's location relative to the macros root) at load.

### What jitter actually touches

Only `wait.ms` and the macro's `loop_delay_ms` are scattered in time, and only click
*points* are scattered in space. `type.interval`, `image_wait.poll_ms`,
`pixel_wait.poll_ms`, `click.interval`, `click_delay`, `move.duration` and
`drag.duration` are used exactly as written.

## Coordinates

`x`/`y` are pixels. In background mode, and in foreground mode with a resolved target
window, they are **client** coordinates — relative to the window's inner top-left.
With no target window they are screen coordinates.

`xp`/`yp` are fractions `0.0`–`1.0` of the target window's client area, so a
coordinate-driven macro survives the window being resized. They are accepted by
`move`, `click`, `double_click`, `right_click` and `scroll` only
(`ACTIONS_WITH_PROPORTIONS` in `action_runner.py`). Pixels win **per axis** if both
are given.

They need a target window whose client size resolved. If it did not, the action
raises rather than guessing — a guess would click at `(0, 0)` in background mode, or
wherever the cursor happens to sit in foreground mode, with no warning.

## Actions

### Timing and control

**`wait`** — required `ms`. Jittered by `timing_pct`.

**`stop`** — no fields. Asks the current run to stop; put it in a branch (the
`on_found` of an "out of tickets" `image_check`) so a limited-attempt macro halts
itself instead of looping. The stop flag is checked before every subsequent action,
including on return from a branch, so the rest of the iteration does not run. Outside
a macro run — a bare `run_action` from a test or `tools/` — it logs and does nothing,
because the callback that stops the run comes from the runner.

`stop` is missing from the editor's action picker (`_GROUPS` in `gui/editor.py`), so
it can currently only be added by editing JSON or by importing a pack that uses it.

### Mouse

**`click`** — no required fields. Optional `x`/`y` or `xp`/`yp`; `button`
(`"left"` | `"right"` | `"middle"`, default `"left"`); `clicks` (default `1`);
`interval` seconds between repeated clicks — **default `0.05` in background mode and
`0.0` in foreground**. With no coordinates, foreground clicks wherever the cursor is
and background clicks at client `(0, 0)`.

**`double_click`** — no required fields. Optional `x`/`y` or `xp`/`yp`. `button` is
not read; it is always a left double-click. In background mode it is two left clicks
50 ms apart.

**`right_click`** — no required fields. Optional `x`/`y` or `xp`/`yp`.

**`move`** — required `x`, `y` (or `xp`, `yp`). Optional `duration` seconds
(default `0.1`), foreground only — background posts a single `WM_MOUSEMOVE`.

**`drag`** — required `x`, `y`, `x2`, `y2`. Pixels only; `xp`/`yp` is rejected at
load. Optional `duration` seconds (default `0.2`), `button` (default `"left"`). In
background mode any button other than `"left"` is treated as right, so a
middle-button drag is not available there.

**`scroll`** — no required fields. Optional `x`/`y` or `xp`/`yp`, `amount`
(default `3`). Positive scrolls up.

> `amount` is **wheel notches in both modes**. It used not to be: background posted
> `amount * WHEEL_DELTA` while foreground handed `amount` straight to
> `pyautogui.scroll`, which passes it to `mouse_event` as a raw delta where one notch
> is 120 — so the same macro scrolled three notches in the background and asked for
> 3/120 of a notch in the foreground, which is to say nothing at all, and `3` was the
> editor's default. The runner multiplies for the foreground path now.
>
> Whether a *posted* wheel message scrolls a given application at all is a separate
> question and still open — see `docs/BACKLOG.md`.

### Keyboard

**`key`** — required `keys`, a list of key names. An empty list raises. It is a chord,
not a sequence: background holds the modifiers (`ctrl`, `alt`, `shift`, `win`),
presses the remaining keys and releases the modifiers; foreground uses
`pyautogui.press` for one key and `pyautogui.hotkey` for more than one.

**`type`** — required `text`. Optional `interval` seconds between characters
(default `0.02`, not jittered). Background sends one `WM_CHAR` per character.

### Pixel colour

Pixel actions always read the **screen**, via `ImageGrab` — never the window's own
frames. The window offset is added to `x`/`y`, so the coordinates are window-relative,
but the window must be visible and unobscured for the reading to mean anything. There
is no occlusion-safe path here as there is for image matching, and no scale awareness:
a pixel check does not survive a window resize. Prefer an image check where you can.

**`pixel_wait`** — required `x`, `y`, `color` (`[r, g, b]`). Optional `tolerance`
(default `0`; the editor pre-fills `10`) — the maximum absolute difference allowed per
channel; `timeout_ms` (default `5000`); `poll_ms` (default `50`, not exposed by the
editor); `fail_on_timeout` (default `false`) — `true` raises, which aborts the whole
macro.

**`pixel_check`** — required `x`, `y`, `color`. Optional `tolerance` (default `0`;
editor pre-fills `10`). Branches: `on_match`, `on_no_match`.

### Image matching

`template` is a path. A relative path resolves against the data root, so the
conventional form is `templates/<name>.png`. A template that has not been captured yet
is not an error: the check reports no match, the miss is logged once, and every
uncaptured template is listed when the run starts — one missing file used to abort the
whole macro, which is the normal state of a freshly installed pack. A flat, featureless
crop is refused the same way, because it would correlate with anything.

Scores are raw `TM_CCOEFF_NORMED` with anticorrelation floored at zero, so a threshold
means what it says. Measured on a live game window, a present template scores ~0.92 and
absent ones reach ~0.47. The Onmyoji pack uses `0.80` for anything it clicks and `0.70`
for stop-guards, where a false stop is the safe direction.

**`find_and_click`** — required `template`. Optional `threshold` (default `0.80`),
`button` (default `"left"`). Branches: `on_found` (runs *after* the click),
`on_not_found`. Clicks the centre of the single best match, scattered by
`min(click_px, ¼ of the template's smaller side)` so the scatter cannot leave the
element that was matched. Takes its coordinates from the match, so `x`/`y`/`xp`/`yp` on
this action are ignored.

**`image_check`** — required `template`. Optional `threshold` (default `0.80`).
Branches: `on_found`, `on_not_found`. Does not click.

**`image_wait`** — required `template`. Optional `threshold` (default `0.80`),
`timeout_ms` (default `5000`), `poll_ms` (default `500`), `fail_on_timeout`
(default `false`) — `true` raises and aborts the macro. Each poll discards the
iteration's shared capture, so it sees a fresh frame rather than re-testing one
screenshot until it times out. No branches.

**`find_all_and_click`** — required `template`. Optional `threshold` (default `0.70` —
lower than the single-match default, because the template is an *example* of a
repeated element rather than the exact thing), `button` (default `"left"`),
`click_delay` ms between clicks (default `500`), `order` (`"top_left"` default, or
`"score"` for highest match first). Branches: `on_found` runs after **each** click,
`on_not_found` once if there were no matches. Unlike `find_and_click`, these clicks are
not bounded by the template size — they get the plain `click_px` scatter.

### Rectangle detection

**`find_rects_and_click`** — no required fields. Optional `index` (0-based integer or
`"all"`, default `0`), `min_w`/`min_h` (default `40`), `max_w`/`max_h` (default `800`),
`button` (default `"left"`), `click_delay` ms between clicks when `index` is `"all"`
(default `500`). Branches: `on_found` runs after each click, `on_not_found` when
nothing was detected **or** when `index` is out of range.

`rect_detector.find_rectangles` also takes `aspect_min` (0.3), `aspect_max` (3.5) and
`merge_distance` (10). The action does not pass them, so they cannot be tuned from a
macro.

## Branch lists

There are four branch keys. `pixel_check` uses `on_match`/`on_no_match`; the image and
rectangle actions use `on_found`/`on_not_found`. Each is a list of actions with the
same schema, nested to any depth — `packs/onmyoji/realm-raid.macro.json` nests four
levels to walk a 3×3 grid.

Validation recurses into all four keys wherever it finds them, on any action. That
means a branch key on an action whose handler never reads it — `on_found` on
`image_wait`, say — validates cleanly and is then silently ignored.

## Fields that are ignored rather than rejected

| What | Where | What happens |
|---|---|---|
| `xp`/`yp` | on `find_and_click`, `image_check`, `find_all_and_click`, `find_rects_and_click`, `key`, `type`, `wait` | Silently ignored — those handlers do not resolve coordinates from the action. |
| `xp`/`yp` | on `drag`, `pixel_check`, `pixel_wait` | Rejected at load with a message naming the actions that do support it. Waiving the requirement more widely once let a macro validate and then fail at run time. |
| `stall_timeout_ms` | on a macro with `loop: false` | Ignored; the guard only runs in the loop. |
| `stall_timeout_ms` | on a macro with no recognising action | Ignored; the guard has nothing to judge by. |
| `on_found` etc. | on an action whose handler does not read it | Validated, then ignored. |
| `button` | on `double_click` | Ignored; always left. |
| Any unknown key | macro level or inside an action | Ignored. |

## A worked example

```json
{
  "name": "Claim daily rewards",
  "description": "Runs on the rewards screen. Stops when the list is empty.",
  "trigger": { "type": "hotkey", "keys": ["ctrl", "F2"] },
  "background": true,
  "target_window": "Some Game",
  "loop": true,
  "loop_delay_ms": 2500,
  "stall_timeout_ms": 180000,
  "humanize": { "timing_pct": 0.2, "click_px": 4 },
  "actions": [
    {
      "type": "image_check",
      "template": "templates/verification_prompt.png",
      "threshold": 0.70,
      "on_found": [
        { "type": "stop" }
      ]
    },
    {
      "type": "image_check",
      "template": "templates/nothing_left_to_claim.png",
      "threshold": 0.70,
      "on_found": [
        { "type": "stop" }
      ]
    },
    {
      "type": "find_all_and_click",
      "template": "templates/claim_button.png",
      "threshold": 0.70,
      "click_delay": 400,
      "order": "top_left",
      "on_found": [
        { "type": "wait", "ms": 800 }
      ],
      "on_not_found": [
        {
          "type": "find_and_click",
          "template": "templates/next_page.png",
          "threshold": 0.80,
          "on_found": [
            { "type": "wait", "ms": 1200 }
          ],
          "on_not_found": [
            { "type": "click", "xp": 0.5, "yp": 0.92 },
            { "type": "wait", "ms": 1200 }
          ]
        }
      ]
    },
    {
      "type": "image_wait",
      "template": "templates/rewards_screen.png",
      "threshold": 0.80,
      "timeout_ms": 8000,
      "poll_ms": 500
    }
  ]
}
```

What each part is doing, and why it is shaped that way:

- The two stop-guards come first, at `0.70`, so a run is abandoned before it clicks
  anything on a screen it does not understand. A false stop is the cheap failure.
- `find_all_and_click` treats `claim_button.png` as an example and clicks every match,
  top-to-bottom. Its `on_found` runs once per click.
- The `on_not_found` chain is the fallback: try the next page, and if that button is
  not there either, click a fixed spot proportionally so the macro survives a resize.
- `image_wait` at the end holds until the screen has settled, rather than assuming a
  fixed `wait` was long enough.
- `stall_timeout_ms` is shortened to 3 minutes because nothing on this screen takes
  longer than that; the 5-minute default is sized for battles and loading screens.

## Adding an action type

See "Adding a new action type" in `CLAUDE.md`. This file is step 6.
