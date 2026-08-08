# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (run once)
pip install -r requirements.txt

# Run the app
python main.py

# Run the app with console output visible (useful for debugging)
python -u main.py
```

Pure Python — no build step to run the app, and no linter configured. Tests are pytest
(`pip install -r requirements-dev.txt`, then `python -m pytest tests/`; config in
`pytest.ini`). `.github/workflows/ci.yml` runs them plus `tools/import_check.py` on
every push to `main` and every PR; `release.yml` builds the `.exe` with Nuitka on a
`v*` tag.

## Architecture

```
main.py                  Entry point — creates and starts App (tkinter mainloop)
engine/
  paths.py               Centralized path resolution — user data in %APPDATA%, legacy migration
  macro_engine.py        Loads/saves/validates macros; runs them in background threads
  action_runner.py       Dispatches individual action dicts to pyautogui/keyboard/Win32 calls
  pixel_detector.py      Screenshot-based pixel color read, match, wait
  image_matcher.py       OpenCV template matching — find_template / find_all_templates
  rect_detector.py       OpenCV contour-based rectangle/card detection
  background_input.py    Win32 PostMessage API — send mouse/keyboard to a window without moving the real cursor
  wgc_capture.py         Windows.Graphics.Capture — GPU-aware window capture for DX games/emulators
  hotkey_listener.py     Wraps the `keyboard` library for global hotkey registration
gui/
  app.py                 Main tkinter window — macro list, log panel, header controls
  editor.py              Toplevel editor window — visual form per action, JSON sub-editor for branch lists
  picker.py              Full-screen transparent overlay for picking pixel coordinates
  region_capture.py      Full-screen overlay for drag-to-select screen region capture
  arranger.py            Window Arranger dialog — select windows and tile them in a grid
  inspector.py           Debug tool — live capture previews and image-match diagnostics
  widgets.py             Reusable themed widgets (Button, Label, ScrolledText, ...)
  theme.py               Color/font constants for the dark UI theme
```

### User data paths

User-created data (macros, template images) is stored under `%APPDATA%/Macroscope/`:

```
%APPDATA%/Macroscope/
├── macros/          Macro JSON files
└── templates/       Template images for image matching
```

`engine/paths.py` is the single source of truth for all path resolution. On first launch of a packaged `.exe`, `migrate_legacy_data()` copies any existing exe-relative `macros/` and `templates/` into the APPDATA location. When running from source, `data_root()` falls back to the project directory if APPDATA is unset.

### Data flow

1. `App._reload_macros()` calls `MacroEngine.load_all()` which reads every `*.json` under `macros/`, recursively — a macro's subfolder becomes its runtime-only `_folder`.
2. Macros whose `trigger` is `{"type": "hotkey", "keys": [...]}` are registered with `HotkeyListener`. The hotkey toggles: it starts the macro, or stops it if running.
3. When triggered (hotkey or play button), `MacroEngine.run(name)` spawns a daemon thread.
4. The thread calls `_execute()` -> iterates `actions` -> dispatches each to `action_runner.run_action()`.
5. `run_action()` receives a context dict (`ctx`) with optional `hwnd` for background mode. When `hwnd` is set, mouse/keyboard actions route through `background_input.py` (Win32 PostMessage) instead of pyautogui.
6. Branching actions (`pixel_check`, `image_check`, `find_and_click`, `find_all_and_click`, `find_rects_and_click`) accept a `run_actions_fn` callback to execute nested `on_match`/`on_no_match`/`on_found`/`on_not_found` action lists.
7. All log output is forwarded through `App._log()`, which marshals to the tkinter main thread via `self.after(0, ...)`.

### Background mode

Macros with `"background": true` and a `"target_window"` title substring route all input through `background_input.py` using Win32 `PostMessage`. Coordinates become client-space (relative to window's inner top-left). Does not work with DirectInput/raw-input games.

### Action types

All action types recognized by the engine (registered in both `action_runner.py` handlers and `macro_engine.py` `_REQUIRED_ACTION_FIELDS`):

`move`, `click`, `double_click`, `right_click`, `drag`, `scroll`, `key`, `type`, `wait`, `stop`, `pixel_wait`, `pixel_check`, `find_and_click`, `image_wait`, `image_check`, `find_rects_and_click`, `find_all_and_click`

Every field of every one of them, with the real defaults, is in `docs/SCHEMA.md`.

Image-based actions (`find_and_click`, `image_wait`, `image_check`, `find_all_and_click`) use `image_matcher.py` (OpenCV `matchTemplate`). `find_rects_and_click` uses `rect_detector.py` (OpenCV contour analysis).

### Image matching behaviour

`engine/image_matcher.py` carries six behaviours worth knowing before touching it:

- **Uncaptured templates degrade, they don't crash.** A missing file raises
  `TemplateMissing` (a `FileNotFoundError` subclass); `action_runner._safe_find`
  turns it into a normal no-match and logs it once, and `MacroEngine._execute`
  lists every missing template at the start of a run. Before this, one missing
  file aborted the whole macro — the default state of a freshly installed pack.
- **Matching is scale-aware.** A template captured at one window size still matches
  at another. The cheap path runs first — this template's known scale, then the
  window's known scale, then 1.0 — so a normal tick costs one or two matches. Only
  if all miss does `_discover_scale` run a **two-stage search**: a coarse ladder
  scanning for the best *score* (not the first rung over a threshold, which is what
  lets it be coarse), then a fine pass around the winner. ~21 matches for ~1.5%
  precision, where one ladder fine enough would need ~75 and stall 19 s. Searches
  are rationed by time and never switched off, since "nothing matched yet" is the
  normal state before an element appears.
- **`_claim_sweep` decides and claims in one lock, under three rules.** Two of them
  replaced a design that looked right and starved the only template that could answer.
  Check-and-claim is one acquisition because two let 8 threads start 4 concurrent
  searches where the floor allows 1, and `run_folder` runs macros in parallel.
  1. **One search at a time per window size** (floor: what the last one cost).
  2. **A template waits out `_DISCOVERY_INTERVAL` after its own search.** Keeping that
     clock per *window size* instead hands every slot to whichever template is scored
     first. Measured against a live window at 0.44x: five templates scored in a row all
     read "no match" because the first (absent) one spent the interval; the one whose
     button was plainly visible scored **0.94** given a search of its own.
  3. **The slot goes to whoever has waited longest**, never-searched counting as
     forever. Rules 1 and 2 alone still starve everything past about
     `_DISCOVERY_INTERVAL / tick` positions in scoring order, because templates already
     in the rotation keep taking the slot from those behind them. Measured with this
     pack's own order — 8 templates, the visible one scored last behind seven absent
     guards, 1.1 s searches, 2.5 s poll: after 400 ticks the front six had swept 66-67
     times each, the visible one **zero**, and it was never found. With rule 3: 8/8 and
     17/17 templates served, found on tick 16 and 25, sweeps even.

  Asking registers a template as waiting (`_seen`); one that is always refused must
  still join the queue or it can never become the stalest. **Every pack macro checks
  absent guard templates first, so this ordering is the ordinary case, not a corner** —
  and it is why the pack only ever worked at exactly the capture size.
- **The floor between two first-time searches is what the last search cost**
  (`_sweep_cost`), never below `_SWEEP_FLOOR`. A fixed floor cannot serve both ends: a
  search measured 1.1 s on a 1236x696 window and ~6.9 s on 2560x1380, so 1 s would let
  eight templates spend 55 s inside a single 2.5 s tick on the big window — blind for a
  minute, which is worse than converging a few seconds later. Measured with the adaptive
  floor: one search per tick, the visible template found after 5 ticks, every later tick
  back to 0.36 s.
- **`set_unrationed_discovery()` is for `tools/` only.** Scoring a whole templates
  directory in one pass is exactly the batch the floor exists to slow down, and a report
  that says "no match" because the previous template spent the budget is worse than a
  slow one. A macro must never turn it on.
- **Do not add a downscaling pre-filter.** One was tried and removed. Shrinking both
  images before comparing only works when the element's position aligns with the
  sampling grid: the same button lost 0.0000 at a multiple-of-4 offset and 0.1181 one
  pixel over, so real matches were being vetoed silently. An app puts its buttons
  where it likes, so no slack is both safe and useful.
- **One capture per macro iteration.** `begin_frame_scope`/`end_frame_scope`
  (called by `_execute`) make every image check in one tick share a single
  screenshot, so checks judge the same screen instead of racing a changing UI.
  Anything that sends input, or `image_wait` polling, invalidates it.
- **Scores are raw `TM_CCOEFF_NORMED`,** with anticorrelation floored at 0, so a
  threshold means what it says. Measured on a live game window: a present
  template scores `~0.92` (an exact crop of the same frame scores `1.0000`), and
  absent ones reach `~0.47`. The pack uses `0.80` for anything it clicks and
  `0.70` for stop-guards, where a false stop is the safe direction.
  Scores used to be remapped as `(raw + 1) / 2`, which squeezed everything usable
  into `[0.5, 1.0]` — zero correlation read as `0.50` and unrelated content sat
  near `0.70`, so `threshold=0.70` asked for no correlation at all.
- **`_WGC_THRESHOLD_OFFSET` allows for cross-backend colour drift** when a
  GDI-sourced template is matched against a WGC frame. Measured by capturing one
  window both ways and cross-scoring: static UI costs `0.037-0.046` raw, so the
  allowance is `0.08`. Do not raise it from an animated region's number — a
  control comparing two WGC frames 50 ms apart reproduced most of that drift on
  its own, and comparing captures taken at different instants measures the game
  animating, not the backends differing.

### Choosing which window a macro drives

`target_window` is a case-insensitive substring, and a substring is not an identity. A
macro set to `"Onmyoji"` resolved to a browser tab titled
`(176) Onmyoji - 預選賽 … - YouTube` and posted its clicks into the browser — measured,
while the game window `陰陽師Onmyoji` was open.

- `background_input.find_all_windows` **ranks** candidates instead of taking whatever
  `EnumWindows` reaches first: not a decorated tab or folder, then an exact title, then
  the shortest remaining title.
- **There is no "begins with the pattern" tier**, though it looks obvious. The game's
  own title is `陰陽師Onmyoji`, which only *contains* the pattern, so a prefix tier
  promoted `Onmyoji Launcher`, `Onmyoji - Google Search - Google Chrome` and
  `Onmyoji Wiki | Fandom` above the game — the same defect wearing a different title.
- **The tab/folder demotion applies only to a *decorated* title.** Demoting
  `_TITLE_HOSTING_CLASSES` outright was measured picking a Notepad file called
  `slack rollout notes.txt` over Slack itself: Electron is `Chrome_WidgetWin_1`, which
  this file lists as a supported target, and an Electron app's window is titled just
  `Slack` while a browser tab is always decorated. Demoted, never excluded — a window of
  one of those classes that is the only match is still returned.
- **This cannot always be right, and the code says so.** A folder titled exactly
  `Onmyoji` still outranks a game titled `陰陽師Onmyoji`, because an exact title genuinely
  is the stronger signal and nothing in a title or a class says which window is the
  application. `tests/test_window_resolution.py` pins that outcome *and* shows
  `target_class` settling it, rather than pretending the ranking solved it.
- `target_class` is the reliable answer and the window picker records it alongside
  `target_hwnd`, because the class outlives the handle: next session the hwnd is stale
  and the title search takes over. A class that matches nothing is **dropped rather than
  enforced** — an application that changes its window class in an update must not
  silently stop being found, and picking the wrong window is the failure worth
  preventing.
- When several windows still match, `_resolve_hwnd` logs each candidate *with its class*
  and says how to fix it. "Using topmost" does not tell a user their browser was chosen.

### Capture-time template validation

`engine/template_check.py` judges a crop *before* it is saved, from both capture paths
(`gui/capture_wizard.py` and the editor's Capture Region), through the shared
`gui/capture_review.py` dialog. It exists because the engine could only ever report a
failure later, in a log, when the screen that would have explained it is gone.

- **The bar for a featureless crop is the matcher's own** (`im.MIN_NEEDLE_STD`), so the
  wizard cannot accept what `_load_needle` will reject. This is the only **blocker**;
  the dialog offers no way to save one.
- **Uniqueness is measured, not guessed.** `_cv_match_all` counts the crop's matches on
  the screen it came from. A crop appearing five times is a warning, not a blocker,
  because `find_all_and_click` is built on exactly that.
- **Judge against the frame the crop came from, never a fresh grab.** A second grab of
  an animating game is a different picture, and a crop that cannot find itself in it
  looks like a bad crop rather than a late screenshot. So `RegionCapture` takes one
  full-screen grab and crops the selection out of it, the way `tools/game_probe.py`
  already did.
- **That cropping trusts `SM_XVIRTUALSCREEN` to be the origin PIL used**, which PIL
  does not expose, so the grab's size is checked against `SM_CXVIRTUALSCREEN` first and
  `self.screen` is dropped rather than passed on wrong. Measured both ways on a
  three-monitor desktop with a negative origin: with per-monitor DPI awareness (what
  `main.py` declares) the metrics read `origin=(-2560,0) size=6400x2400`, the grab is
  `6400x2400`, and cropping from it is **pixel-identical** to PIL's own bbox grab —
  `max abs diff 0`, including a box on the negatively-offset monitor. Without DPI
  awareness the metrics read `3584x1152` against the same `6400x2400` grab, and the
  crop was garbage (`mean abs diff 149.8`). The size check is what turns that into a
  fallback instead of a corrupted template.
- **The collision threshold is `0.80` because that is what macros click at.** Two
  templates scoring above it are interchangeable to the engine whatever they look like
  to a person — measured: a plain `OK` button scored 0.91 against a completely
  different button. Reporting below that bar would name collisions the engine could
  never make.
- **Cross-scoring runs the matcher's own two-stage search, in both directions.** It has
  to: the check claims the engine cannot tell two crops apart, and the engine is
  scale-aware. Comparing crops as stored missed a real duplicate twice in one session —
  the Realm Raid attack button captured at 2840x1600 and at 1236x696 scored 0.31 as
  stored and 0.85 across scales; and two captures of the same "Tap to continue" bar sit
  at a ratio of 0.435, which falls *between* the 0.400 and 0.448 rungs, so the coarse
  ladder alone still reported nothing and the fine pass was what reached 0.92.
- **The check is not instant, and it grows with the templates directory.** Measured:
  ~42 ms per already-captured template (worst 73 ms) plus ~0.7 s to scan a 6400x2400
  screen — 1.4 s for a small pack, ~5 s for a large one. `gui/capture_review.py`
  therefore runs it on a worker with a modal that says what it is doing, and shows
  nothing at all if it finishes inside 350 ms, because a dialog that flashes is worse
  than none.
- **Past `_TOO_MANY_HITS` raw matches, stop counting.** Deduplicating is quadratic
  (`_nms` is a Python double loop) and a small crop of ordinary screen content produces
  thousands: on a real 6400x2400 desktop a 16 px crop hit 12779 positions, and one worst
  case spent **57 s inside `_nms` alone** — a frozen capture dialog. Past a couple of
  hundred hits the exact number tells the user nothing they cannot see, and the message
  says "it is texture, not a thing" instead.
- Re-capturing excludes the file being replaced (`capture_review.other_templates`), or
  every re-capture would collide with the version it is replacing.

### Jitter and the stall guard

Both live behind per-macro fields and are **on by default**, because they are safety
features and asking for them defeats the point.

- `engine/humanize.py` scatters delays by a *fraction* (±15%, so a 300 ms settle and a
  2500 ms poll both stay sensible) and click points by a radius in pixels (3 by
  default). It reaches exactly two delays: `wait.ms` and the macro's `loop_delay_ms`.
  Every other interval in the schema — `type.interval`, the `poll_ms` of `pixel_wait`
  and `image_wait`, `click_delay`, `click.interval`, `move`/`drag` `duration` — is used
  as written, so do not describe the whole macro's timing as randomised.
  Settings reach the runner through `ctx["humanize"]`; a bare `run_action` call with no
  ctx does exactly what the action says, which is what tests and `tools/` want.
  `"humanize": false` disables it (so do `0` and `""`); `{"timing_pct": …,
  "click_px": …}` tunes it, and either may be `0` on its own. Seed with
  `humanize.seed()` in tests — it owns its own `Random` so nothing else can disturb it.
- **A jittered click is clamped, and bounded by the match.** `_scatter` jitters, then
  keeps the point inside the client area: 3 px on a click at `xp: 0.999` left a
  1280×720 client area 39 times out of 60, and outside the client area a posted click
  is silently dropped while the real cursor lands on a pyautogui failsafe corner —
  which aborts the *next* pyautogui call. An exact coordinate is never clamped; only
  jitter is ours to contain. Callers that matched something pass
  `max_px=_bound_of(match)`, a quarter of the size the template **matched at**, which
  `image_matcher.Match` carries alongside `(cx, cy, score)`. The template file's own
  size is the wrong bound: matching is scale-aware, so a 40×40 template matches a 20×20
  element on a half-size window. `_click(…, jittered=True)` is a keyword rather than a
  field in the action, because a flag living in the action dict is spoofable from a
  user's JSON and survives being saved.
- **Stall guard.** `_execute` stops a looping macro that has been *sending input* for
  `stall_timeout_ms` (default 5 minutes; `0` disables) without recognising anything.
  It replaces the per-game CAPTCHA template as the primary safety stop, because it
  needs no template and so also catches disconnects, maintenance and a changed UI.
  Three details keep it from firing on macros that work, and each replaced a
  plausible-sounding rule that measurement killed:
  - The condition is **clicking blind**, not matching nothing. A macro that recognises
    nothing and clicks nothing is a watcher waiting for an element to appear — the
    normal state, exactly as `image_matcher` says of scale search — so stopping it
    would be a false positive. `_sent_input(ctx)` marks the handlers that act.
  - Recognition is **any** kind: `_recognised(ctx)` is called from `_safe_find`, from a
    matched `pixel_check`, from a successful `pixel_wait`, and from detected rects.
    Setting it only on template matches stopped a loop whose `pixel_check` matched its
    exact expected colour on every single tick.
  - A macro with no recognising action anywhere in its tree (`_can_recognise`) is not
    guarded at all — it recognises nothing by construction, so the guard has no signal.
  It cannot see a macro that **recognises something and still makes no progress**.
  Measured: a Realm Raid run pressed Refresh 23 times in 10 minutes without refreshing
  anything, because a dialog it never answered was in the way — and `find_and_click`
  matched Refresh every tick, so the clock reset every tick. That is a real gap in what
  the guard can detect, not a bug in it; closing it needs a different signal.
  A stall records the macro in `_stalled`, so a sequential folder run can tell it from
  the user pressing Stop; both set the same event, and conflating them let one macro
  losing its screen cancel the rest of someone's dailies. `stall_timeout_ms` is coerced
  in `_stall_timeout_of` *and* validated at load, because it is only read on an
  iteration that recognised nothing — a string there used to raise a `TypeError`
  minutes into a run that had been working.

Neither makes automation undetectable. Do not describe them as if they do.

### Proportional coordinates

`move`, `click`, `double_click`, `right_click` and `scroll` — the set in
`ACTIONS_WITH_PROPORTIONS` — accept `xp`/`yp`, fractions `0.0-1.0` of the target
window's client area, instead of `x`/`y` pixels, so coordinate-driven macros survive a
window resize. Requires a resolved `target_window`; `_build_ctx` supplies
`client_w`/`client_h`, and `_coords` raises rather than guessing when they are 0.
Pixels win per axis if both are given.

Nothing else takes them. `find_and_click` builds its own `{"type": "click", "x": …}`
from the match, so `xp` on *that* action is silently ignored; `drag`, `pixel_check` and
`pixel_wait` require pixel `x`/`y`, and validation rejects `xp`/`yp` there with a
message naming the actions that do support it. Waiving the requirement more widely once
let a macro validate and then raise `KeyError` at run time, or act at `(0, 0)` in
silence.

### Where this input method works, and where it cannot

Worth knowing before pointing the engine at a new application, because the limit is
architectural rather than a matter of tuning.

- **Works:** ordinary Win32 and Electron applications, and games that read input
  through the normal window message queue — turn-based and UI-driven titles, and
  Android emulators (BlueStacks, Nox, LDPlayer). `background_input.py` reaches these
  with `PostMessage`, so no real cursor moves and the window can stay covered.
- **Does not work:** anything reading **raw input** or **DirectInput** directly
  rather than from the message queue. Posted messages simply never arrive; nothing
  in this engine can fix that. Foreground mode with real cursor movement
  (`pyautogui`) is the only fallback, and it takes over the machine.
- **Do not attempt:** titles with kernel-level anti-cheat (Vanguard, Easy
  Anti-Cheat, BattlEye) or a client that actively fingerprints synthetic input.
  Posted input will not beat them, and the attempt gets the *user's* account banned.
  Action-combat gacha titles are typically in this category.

Capture has a matching split: `wgc_capture.py` (Windows.Graphics.Capture) reads a
window's own frames and works while it is occluded; the GDI screen-grab fallback
photographs whatever is on top, so it is only trustworthy for the foreground window.
See `tools/README.md` — that distinction has bitten twice.

### Thread safety

- `MacroEngine._lock` guards `_macros`, `_running`, `_stop_flags`.
- GUI updates from worker threads must use `self.after(0, callback)` — never touch tkinter widgets directly from a thread.
- `MacroEngine._stop_flags[name]` is a `threading.Event`; workers check `stop.is_set()` between every action.

### Adding a new action type

1. Add a handler `_my_action(a: Dict, ctx: Dict)` in `engine/action_runner.py`. Use `ctx.get("hwnd")` for background mode support.
2. Register it in the `handlers` dict inside `run_action()`.
3. Add required fields to `_REQUIRED_ACTION_FIELDS` in `engine/macro_engine.py`.
4. If the action supports branching, add `on_match`/`on_found` etc. and register the branch keys in `_validate_actions()`.
5. In `gui/editor.py`: add its fields to `_F`, **and** add it to a `_GROUPS` row or it
   will not appear in the action picker (`_ICON`/`_COLOR` are optional cosmetics that
   fall back to the type name). `tests/test_editor_actions.py` fails if you forget —
   which is how `stop` was found unreachable after shipping in both pack macros.
6. Document it in `docs/SCHEMA.md` — the reference for macro JSON.
