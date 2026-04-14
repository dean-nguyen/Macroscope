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
  macro_engine.py        Loads/saves/validates macros; runs them in background threads
  action_runner.py       Dispatches individual action dicts to pyautogui/keyboard/Win32 calls
  pixel_detector.py      Screenshot-based pixel color read, match, wait
  image_matcher.py       OpenCV template matching — find_template / find_all_templates
  rect_detector.py       OpenCV contour-based rectangle/card detection
  background_input.py    Win32 PostMessage API — send mouse/keyboard to a window without moving the real cursor
  hotkey_listener.py     Wraps the `keyboard` library for global hotkey registration
gui/
  app.py                 Main tkinter window — macro list, log panel, header controls
  editor.py              Toplevel editor window — JSON text editor + action snippet sidebar
  picker.py              Full-screen transparent overlay for picking pixel coordinates
  region_capture.py      Full-screen overlay for drag-to-select screen region capture
  arranger.py            Window Arranger dialog — select windows and tile them in a grid
  widgets.py             Reusable themed widgets (Button, Label, ScrolledText, ...)
  theme.py               Color/font constants for the dark UI theme
macros/
  SCHEMA.md              Full macro JSON schema reference
  *.json                 Individual macro files (loaded at startup)
templates/               Template images for image matching actions (PNG files)
```

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
