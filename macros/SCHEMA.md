# Macro JSON Schema

Every macro is a single `.json` file saved in this `macros/` directory.
The app loads all `*.json` files from this folder automatically.

---

## Top-level fields

| Field           | Type    | Required | Description |
|-----------------|---------|----------|-------------|
| `name`          | string  | ✅       | Unique identifier (also used as the filename stem) |
| `description`   | string  | –        | Human-readable description shown in the UI |
| `trigger`       | object  | –        | Global hotkey that fires the macro |
| `loop`          | boolean | –        | If `true`, repeat the macro until stopped (default `false`) |
| `loop_delay_ms` | number  | –        | Milliseconds to wait between loop iterations (default `0`) |
| `background`    | boolean | –        | If `true`, send input directly to `target_window` without moving the real cursor/keyboard (default `false`) |
| `target_window` | string  | –        | Substring of the target window title (case-insensitive). Required when `background` is `true`. |
| `actions`       | array   | ✅       | Ordered list of action objects |

### Background mode

Setting `"background": true` routes all mouse/keyboard actions through the
Win32 `PostMessage` API directly into the target window's message queue.
Your real cursor does not move and your physical keyboard is unaffected,
so you can keep using the PC while the macro runs.

```json
"background": true,
"target_window": "Notepad"
```

If the window title is not found at run time the macro falls back to normal
(foreground) mode and logs a warning.

Coordinates (`x`, `y`) in background mode are **client-space** — relative to
the inner top-left corner of the target window, not the screen.

### trigger object

```json
"trigger": { "type": "hotkey", "keys": ["ctrl", "F1"] }
```

`keys` values are pyautogui/keyboard key names: `ctrl`, `alt`, `shift`, `win`,
`F1`–`F12`, `a`–`z`, `0`–`9`, etc.

---

## Action types

### `wait`
Pause execution.
```json
{ "type": "wait", "ms": 500 }
```

### `move`
Move the mouse cursor.
```json
{ "type": "move", "x": 100, "y": 200, "duration": 0.1 }
```
`duration` (seconds) is optional (default `0.1`).

### `click`
Click the mouse.
```json
{ "type": "click", "x": 100, "y": 200, "button": "left", "clicks": 1, "interval": 0.0 }
```
`x`/`y` are optional (clicks at current position if omitted).
`button`: `"left"` | `"right"` | `"middle"`.

### `double_click`
Double-click.
```json
{ "type": "double_click", "x": 100, "y": 200 }
```

### `right_click`
Right-click.
```json
{ "type": "right_click", "x": 100, "y": 200 }
```

### `drag`
Click-and-drag from one position to another.
```json
{ "type": "drag", "x": 50, "y": 50, "x2": 300, "y2": 300, "duration": 0.3, "button": "left" }
```

### `scroll`
Scroll the mouse wheel.
```json
{ "type": "scroll", "x": 500, "y": 400, "amount": 3 }
```
Positive `amount` scrolls up, negative scrolls down.

### `key`
Press a key or key combination.
```json
{ "type": "key", "keys": ["ctrl", "c"] }
```
Single key: `{ "type": "key", "keys": ["enter"] }`

### `type`
Type a string character by character.
```json
{ "type": "type", "text": "Hello world!", "interval": 0.02 }
```
`interval` (seconds between keystrokes) is optional (default `0.02`).

### `pixel_wait`
Block until a pixel reaches the expected color, or timeout.
```json
{
  "type": "pixel_wait",
  "x": 640, "y": 360,
  "color": [255, 0, 0],
  "tolerance": 15,
  "timeout_ms": 10000,
  "poll_ms": 50,
  "fail_on_timeout": false
}
```
`color` is `[R, G, B]`. `tolerance` allows per-channel variance.
Set `fail_on_timeout: true` to abort the macro on timeout.

### `pixel_check`
Branch based on the current pixel color.
```json
{
  "type": "pixel_check",
  "x": 640, "y": 360,
  "color": [255, 0, 0],
  "tolerance": 15,
  "on_match": [ ...actions... ],
  "on_no_match": [ ...actions... ]
}
```
`on_match` and `on_no_match` are optional action lists.

### `find_all_and_click`
Use ONE screenshot as an example to find ALL similar elements and click each.
Screenshot one card → it finds all 9 cards and clicks them in order.
```json
{
  "type": "find_all_and_click",
  "template": "templates/one_card.png",
  "threshold": 0.70,
  "button": "left",
  "click_delay": 500,
  "order": "top_left",
  "on_found": [ ...actions per click... ],
  "on_not_found": [ ...actions if zero matches... ]
}
```
`template`: screenshot of ONE example element (card, button, slot, etc.).
`threshold`: similarity score (default 0.70 — lower finds more varied matches).
`click_delay`: ms between each click (default 500).
`order`: `"top_left"` (top-to-bottom, left-to-right) or `"score"` (best match first).

### `find_rects_and_click`
Detect rectangular cards/buttons in the window and click one (or all).
```json
{
  "type": "find_rects_and_click",
  "index": 0,
  "min_w": 40, "min_h": 40,
  "max_w": 800, "max_h": 800,
  "button": "left",
  "click_delay": 500,
  "on_found": [ ...actions... ],
  "on_not_found": [ ...actions... ]
}
```
`index`: which rectangle to click (0-based, sorted top-to-bottom then left-to-right), or `"all"` to click every detected rect.
`min_w`/`min_h`/`max_w`/`max_h`: size filters for detected rectangles.
`click_delay`: ms between clicks when `index` is `"all"`.
`on_found`/`on_not_found`: optional branch action lists.

---

## Full example

```json
{
  "name": "auto_heal",
  "description": "Press F1 when HP bar turns red",
  "trigger": { "type": "hotkey", "keys": ["ctrl", "F5"] },
  "loop": true,
  "loop_delay_ms": 200,
  "actions": [
    {
      "type": "pixel_check",
      "x": 120, "y": 950,
      "color": [200, 30, 30],
      "tolerance": 20,
      "on_match": [
        { "type": "key", "keys": ["F1"] },
        { "type": "wait", "ms": 1000 }
      ]
    }
  ]
}
```
