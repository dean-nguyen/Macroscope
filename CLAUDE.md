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

No build step, no test runner, no linter configured. The project is pure Python.

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
  editor.py              Toplevel editor window — JSON text editor + action snippet sidebar
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

1. `App._reload_macros()` calls `MacroEngine.load_all()` which reads every `macros/*.json`.
2. Macros with a `trigger.hotkey` are registered with `HotkeyListener`.
3. When triggered (hotkey or play button), `MacroEngine.run(name)` spawns a daemon thread.
4. The thread calls `_execute()` -> iterates `actions` -> dispatches each to `action_runner.run_action()`.
5. `run_action()` receives a context dict (`ctx`) with optional `hwnd` for background mode. When `hwnd` is set, mouse/keyboard actions route through `background_input.py` (Win32 PostMessage) instead of pyautogui.
6. Branching actions (`pixel_check`, `image_check`, `find_and_click`, `find_all_and_click`, `find_rects_and_click`) accept a `run_actions_fn` callback to execute nested `on_match`/`on_no_match`/`on_found`/`on_not_found` action lists.
7. All log output is forwarded through `App._log()`, which marshals to the tkinter main thread via `self.after(0, ...)`.

### Background mode

Macros with `"background": true` and a `"target_window"` title substring route all input through `background_input.py` using Win32 `PostMessage`. Coordinates become client-space (relative to window's inner top-left). Does not work with DirectInput/raw-input games.

### Action types

All action types recognized by the engine (registered in both `action_runner.py` handlers and `macro_engine.py` `_REQUIRED_ACTION_FIELDS`):

`move`, `click`, `double_click`, `right_click`, `drag`, `scroll`, `key`, `type`, `wait`, `pixel_wait`, `pixel_check`, `find_and_click`, `image_wait`, `image_check`, `find_rects_and_click`, `find_all_and_click`

Image-based actions (`find_and_click`, `image_wait`, `image_check`, `find_all_and_click`) use `image_matcher.py` (OpenCV `matchTemplate`). `find_rects_and_click` uses `rect_detector.py` (OpenCV contour analysis).

### Image matching behaviour

`engine/image_matcher.py` carries four behaviours worth knowing before touching it:

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
  are rationed by time **per window size**, not per template, because the answer
  generalises through `_window_scale`; they are never switched off, since "nothing
  matched yet" is the normal state before an element appears.
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

### Proportional coordinates

`move`, `click` (and anything routing through `_click`, including
`find_and_click`) accept `xp`/`yp` — fractions `0.0-1.0` of the target window's
client area — instead of `x`/`y` pixels, so coordinate-driven macros survive a
window resize. Requires a resolved `target_window`; `_build_ctx` supplies
`client_w`/`client_h`. Pixels win if both are given.

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
5. Add a snippet dict to `_SNIPPETS` in `gui/editor.py` so it appears in the sidebar.
6. Document it in `macros/SCHEMA.md`.
