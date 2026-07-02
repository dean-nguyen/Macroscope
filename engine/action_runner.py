"""
Execute individual macro actions.

Each handler receives an `action` dict and an optional `ctx` dict:

  ctx = {
      "background": bool,   # True → PostMessage (no cursor movement)
      "hwnd": int | None,   # target window handle (required when background=True)
  }

When ctx["background"] is False or ctx is None, pyautogui is used (foreground).
When ctx["background"] is True and hwnd is set, win32 PostMessage is used.

Supported action types:
  move, click, double_click, right_click, drag, scroll,
  key, type, wait, pixel_wait, pixel_check,
  find_and_click, image_wait, image_check
"""

import time
import pyautogui
from typing import Any, Callable, Dict, List, Optional

import engine.pixel_detector as pd
import engine.background_input as bg
import engine.image_matcher as im
import engine.rect_detector as rd

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.01


class ActionError(Exception):
    pass


def run_action(
    action: Dict[str, Any],
    run_actions_fn: Callable,
    ctx: Optional[Dict] = None,
) -> None:
    """Dispatch a single action dict to the appropriate handler."""
    t = action.get("type", "")
    handlers = {
        "move":         lambda a: _move(a, ctx),
        "click":        lambda a: _click(a, ctx),
        "double_click": lambda a: _double_click(a, ctx),
        "right_click":  lambda a: _right_click(a, ctx),
        "drag":         lambda a: _drag(a, ctx),
        "scroll":       lambda a: _scroll(a, ctx),
        "key":          lambda a: _key(a, ctx),
        "type":         lambda a: _type(a, ctx),
        "wait":         lambda a: _wait(a),
        "stop":         lambda a: _stop(a, ctx),
        "pixel_wait":     lambda a: _pixel_wait(a, ctx),
        "pixel_check":    lambda a: _pixel_check(a, run_actions_fn, ctx),
        "find_and_click": lambda a: _find_and_click(a, run_actions_fn, ctx),
        "image_wait":     lambda a: _image_wait(a, ctx),
        "image_check":    lambda a: _image_check(a, run_actions_fn, ctx),
        "find_rects_and_click": lambda a: _find_rects_and_click(a, run_actions_fn, ctx),
        "find_all_and_click":   lambda a: _find_all_and_click(a, run_actions_fn, ctx),
    }
    handler = handlers.get(t)
    if handler is None:
        raise ActionError(f"Unknown action type: '{t}'")
    handler(action)


# ── context helpers ────────────────────────────────────────────────────────────

def _is_bg(ctx: Optional[Dict]) -> bool:
    return bool(ctx and ctx.get("background") and ctx.get("hwnd"))


def _hwnd(ctx: Dict) -> int:
    return ctx["hwnd"]


def _ox(ctx: Optional[Dict]) -> int:
    """X offset for window-relative foreground mode (0 in background/screen mode)."""
    return ctx.get("offset_x", 0) if ctx else 0


def _oy(ctx: Optional[Dict]) -> int:
    """Y offset for window-relative foreground mode (0 in background/screen mode)."""
    return ctx.get("offset_y", 0) if ctx else 0


def _log(ctx: Optional[Dict], msg: str) -> None:
    """Forward a message to the macro engine log (no-op if unavailable)."""
    fn = ctx.get("log") if ctx else None
    if callable(fn):
        fn(msg)


def _search_hwnd(ctx: Optional[Dict]) -> Optional[int]:
    """
    Return the window handle to use for image capture.

    Background mode       → the background hwnd   (client-area capture, no cursor)
    Foreground+target     → anchor_hwnd            (client-area capture for speed/accuracy)
    Plain foreground      → None                   (full-screen capture)
    """
    if _is_bg(ctx):
        return _hwnd(ctx)
    return ctx.get("anchor_hwnd") if ctx else None


def _make_click_ctx_for_found(ctx: Optional[Dict], search_hwnd_used: Optional[int]):
    """
    After find_template returns (cx, cy) in client-space (when hwnd was given)
    or screen-space (hwnd=None), build the click ctx so _click lands correctly.

    - Background hwnd used  → keep ctx as-is (background click, client coords)
    - Anchor hwnd used      → keep ctx as-is (_click will add offset_x/y to client coords)
    - Full-screen search    → zero the offset (_click must use raw screen coords)
    """
    if search_hwnd_used is None and ctx:
        # Screen-space result: strip the window offset so we don't double-add it
        return dict(ctx, offset_x=0, offset_y=0)
    return ctx


# ── individual handlers ────────────────────────────────────────────────────────

def _move(a: Dict, ctx) -> None:
    if _is_bg(ctx):
        bg.post_move(_hwnd(ctx), a["x"], a["y"])
    else:
        pyautogui.moveTo(a["x"] + _ox(ctx), a["y"] + _oy(ctx),
                         duration=a.get("duration", 0.1))


def _click(a: Dict, ctx) -> None:
    x, y = a.get("x"), a.get("y")
    button = a.get("button", "left")
    if _is_bg(ctx):
        cx, cy = (x or 0), (y or 0)
        clicks = a.get("clicks", 1)
        interval = a.get("interval", 0.05)
        for i in range(clicks):
            bg.post_click(_hwnd(ctx), cx, cy, button)
            if i < clicks - 1:
                time.sleep(interval)
    else:
        ox, oy = _ox(ctx), _oy(ctx)
        clicks = a.get("clicks", 1)
        interval = a.get("interval", 0.0)
        if x is not None and y is not None:
            pyautogui.click(x + ox, y + oy,
                            button=button, clicks=clicks, interval=interval)
        else:
            pyautogui.click(button=button, clicks=clicks, interval=interval)


def _double_click(a: Dict, ctx) -> None:
    x, y = a.get("x", 0), a.get("y", 0)
    if _is_bg(ctx):
        bg.post_double_click(_hwnd(ctx), x, y)
    else:
        if a.get("x") is not None:
            pyautogui.doubleClick(x + _ox(ctx), y + _oy(ctx))
        else:
            pyautogui.doubleClick()


def _right_click(a: Dict, ctx) -> None:
    x, y = a.get("x", 0), a.get("y", 0)
    if _is_bg(ctx):
        bg.post_right_click(_hwnd(ctx), x, y)
    else:
        if a.get("x") is not None:
            pyautogui.rightClick(x + _ox(ctx), y + _oy(ctx))
        else:
            pyautogui.rightClick()


def _drag(a: Dict, ctx) -> None:
    if _is_bg(ctx):
        bg.post_drag(
            _hwnd(ctx),
            a["x"], a["y"], a["x2"], a["y2"],
            duration=a.get("duration", 0.2),
            button=a.get("button", "left"),
        )
    else:
        ox, oy = _ox(ctx), _oy(ctx)
        pyautogui.moveTo(a["x"] + ox, a["y"] + oy)
        pyautogui.dragTo(
            a["x2"] + ox, a["y2"] + oy,
            duration=a.get("duration", 0.2),
            button=a.get("button", "left"),
        )


def _scroll(a: Dict, ctx) -> None:
    x, y = a.get("x", 0), a.get("y", 0)
    amount = a.get("amount", 3)
    if _is_bg(ctx):
        bg.post_scroll(_hwnd(ctx), x, y, amount)
    else:
        ox, oy = _ox(ctx), _oy(ctx)
        if a.get("x") is not None:
            pyautogui.scroll(amount, x=x + ox, y=y + oy)
        else:
            pyautogui.scroll(amount)


def _key(a: Dict, ctx) -> None:
    keys = a.get("keys", [])
    if not keys:
        raise ActionError("'key' action requires a 'keys' list")
    if _is_bg(ctx):
        bg.post_key(_hwnd(ctx), keys)
    else:
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)


def _type(a: Dict, ctx) -> None:
    text = a.get("text", "")
    interval = a.get("interval", 0.02)
    if _is_bg(ctx):
        bg.post_type(_hwnd(ctx), text, interval)
    else:
        pyautogui.typewrite(text, interval=interval)


def _wait(a: Dict) -> None:
    time.sleep(a.get("ms", 0) / 1000.0)


def _stop(a: Dict, ctx) -> None:
    """Request the running macro to stop (ends its loop).

    Placed in a branch (e.g. on_found of an "out of tickets" image_check) so a
    limited-attempt daily halts itself once exhausted instead of looping.
    """
    _log(ctx, "[stop] macro stop requested")
    fn = ctx.get("request_stop") if ctx else None
    if callable(fn):
        fn()


def _pixel_wait(a: Dict, ctx=None) -> None:
    x = a["x"] + _ox(ctx)
    y = a["y"] + _oy(ctx)
    success = pd.wait_for_pixel(
        x=x, y=y,
        color=tuple(a["color"]),
        tolerance=a.get("tolerance", 0),
        timeout_ms=a.get("timeout_ms", 5000),
        poll_ms=a.get("poll_ms", 50),
    )
    if not success and a.get("fail_on_timeout", False):
        raise ActionError(
            f"pixel_wait timed out at ({x}, {y}) "
            f"waiting for color {a['color']}"
        )


def _pixel_check(a: Dict, run_actions_fn: Callable, ctx) -> None:
    sx = a["x"] + _ox(ctx)
    sy = a["y"] + _oy(ctx)
    actual = pd.get_pixel_color(sx, sy)
    expected = tuple(a["color"])
    tolerance = a.get("tolerance", 0)
    matched = pd.color_matches(actual, expected, tolerance)

    status = "MATCH" if matched else "NO MATCH"
    _log(ctx,
         f"[pixel_check] {status} at window({a['x']},{a['y']}) "
         f"actual={list(actual)} expected={list(expected)} tol={tolerance}")

    branch = "on_match" if matched else "on_no_match"
    branch_actions = a.get(branch, [])
    if branch_actions:
        run_actions_fn(branch_actions)


# ── image-based actions ───────────────────────────────────────────────────────

def _find_and_click(a: Dict, run_actions_fn: Callable, ctx) -> None:
    """Find a template image and click its centre."""
    sh = _search_hwnd(ctx)
    threshold = a.get("threshold", 0.80)
    result = im.find_template(a["template"], hwnd=sh, threshold=threshold)
    if result:
        cx, cy, score = result
        _log(ctx,
             f"[find_and_click] FOUND '{a['template']}' "
             f"at ({'client' if sh else 'screen'})({cx},{cy}) score={score:.3f}")
        click_a   = {"type": "click", "x": cx, "y": cy, "button": a.get("button", "left")}
        click_ctx = _make_click_ctx_for_found(ctx, sh)
        _click(click_a, click_ctx)
        if a.get("on_found"):
            run_actions_fn(a["on_found"])
    else:
        _log(ctx, f"[find_and_click] NOT FOUND '{a['template']}' (threshold={threshold})")
        if a.get("on_not_found"):
            run_actions_fn(a["on_not_found"])


def _image_wait(a: Dict, ctx) -> None:
    """Poll until a template image appears on screen (or times out)."""
    sh         = _search_hwnd(ctx)
    timeout_ms = a.get("timeout_ms", 5000)
    poll_ms    = a.get("poll_ms", 500)
    threshold  = a.get("threshold", 0.80)
    deadline   = time.time() + timeout_ms / 1000.0

    _log(ctx, f"[image_wait] waiting for '{a['template']}' (timeout={timeout_ms}ms)")
    while time.time() < deadline:
        if im.find_template(a["template"], hwnd=sh, threshold=threshold):
            _log(ctx, f"[image_wait] FOUND '{a['template']}'")
            return
        time.sleep(poll_ms / 1000.0)

    _log(ctx, f"[image_wait] TIMEOUT '{a['template']}'")
    if a.get("fail_on_timeout", False):
        raise ActionError(f"image_wait timed out: '{a['template']}'")


def _image_check(a: Dict, run_actions_fn: Callable, ctx) -> None:
    """Branch based on whether a template image is currently visible."""
    sh        = _search_hwnd(ctx)
    threshold = a.get("threshold", 0.80)
    result    = im.find_template(a["template"], hwnd=sh, threshold=threshold)
    status    = f"FOUND at {result[:2]} score={result[2]:.3f}" if result else "NOT FOUND"
    _log(ctx, f"[image_check] {status} '{a['template']}'")
    branch = "on_found" if result else "on_not_found"
    if a.get(branch):
        run_actions_fn(a[branch])


# ── rectangle detection actions ──────────────────────────────────────────────

def _find_rects_and_click(a: Dict, run_actions_fn: Callable, ctx) -> None:
    """
    Detect rectangular cards/buttons and click one (or each).

    Fields:
      index       – which rect to click (0-based), or "all" to click each
      click_delay – ms between clicks when index="all"
      min_w/min_h – minimum rect size (default 40)
      max_w/max_h – maximum rect size (default 800)
      button      – mouse button (default "left")
      on_found    – actions to run after each click
      on_not_found – actions to run if no rects detected
    """
    sh = _search_hwnd(ctx)

    rects = rd.find_rectangles(
        hwnd=sh,
        min_w=a.get("min_w", 40),
        min_h=a.get("min_h", 40),
        max_w=a.get("max_w", 800),
        max_h=a.get("max_h", 800),
    )

    if not rects:
        _log(ctx, "[find_rects] NO RECTS detected")
        if a.get("on_not_found"):
            run_actions_fn(a["on_not_found"])
        return

    _log(ctx, f"[find_rects] detected {len(rects)} rects")
    for i, (cx, cy, w, h) in enumerate(rects):
        _log(ctx, f"  [{i}] centre=({cx},{cy}) size={w}x{h}")

    index = a.get("index", 0)
    button = a.get("button", "left")
    click_delay = a.get("click_delay", 500) / 1000.0
    click_ctx = _make_click_ctx_for_found(ctx, sh)

    if index == "all":
        for i, (cx, cy, w, h) in enumerate(rects):
            _log(ctx, f"[find_rects] clicking rect [{i}] at ({cx},{cy})")
            click_a = {"type": "click", "x": cx, "y": cy, "button": button}
            _click(click_a, click_ctx)
            if a.get("on_found"):
                run_actions_fn(a["on_found"])
            if i < len(rects) - 1 and click_delay > 0:
                time.sleep(click_delay)
    else:
        idx = int(index)
        if idx < 0 or idx >= len(rects):
            _log(ctx, f"[find_rects] index {idx} out of range (found {len(rects)})")
            if a.get("on_not_found"):
                run_actions_fn(a["on_not_found"])
            return
        cx, cy, w, h = rects[idx]
        _log(ctx, f"[find_rects] clicking rect [{idx}] at ({cx},{cy})")
        click_a = {"type": "click", "x": cx, "y": cy, "button": button}
        _click(click_a, click_ctx)
        if a.get("on_found"):
            run_actions_fn(a["on_found"])


def _find_all_and_click(a: Dict, run_actions_fn: Callable, ctx) -> None:
    """
    Use a template image as an *example* to find ALL similar regions,
    then click each one in order (top-to-bottom, left-to-right).

    This is the key difference from find_and_click (which finds only the best
    single match).  Give it a screenshot of ONE card and it will find all 9.

    Fields:
      template    – path to the example image (screenshot of one card/button)
      threshold   – similarity threshold (default 0.70, lower = more lenient)
      button      – mouse button (default "left")
      click_delay – ms to wait between each click (default 500)
      order       – "top_left" (default) or "score" (highest match first)
      on_found    – actions to run after EACH match is clicked
      on_not_found – actions to run if zero matches
    """
    sh        = _search_hwnd(ctx)
    threshold = a.get("threshold", 0.70)
    button    = a.get("button", "left")
    delay     = a.get("click_delay", 500) / 1000.0
    order     = a.get("order", "top_left")

    matches = im.find_all_templates(a["template"], hwnd=sh, threshold=threshold)

    if not matches:
        _log(ctx, f"[find_all] NO matches for '{a['template']}' (threshold={threshold})")
        if a.get("on_not_found"):
            run_actions_fn(a["on_not_found"])
        return

    # Sort by position (top-to-bottom, left-to-right) unless score order requested
    if order == "top_left":
        matches.sort(key=lambda m: (m[1], m[0]))  # cy, cx
    # else already sorted by score from find_all_templates

    _log(ctx, f"[find_all] found {len(matches)} matches for '{a['template']}'")
    for i, (cx, cy, score) in enumerate(matches):
        _log(ctx, f"  [{i}] ({cx},{cy}) score={score:.3f}")

    click_ctx = _make_click_ctx_for_found(ctx, sh)

    for i, (cx, cy, score) in enumerate(matches):
        _log(ctx, f"[find_all] clicking [{i}] at ({cx},{cy})")
        click_a = {"type": "click", "x": cx, "y": cy, "button": button}
        _click(click_a, click_ctx)
        if a.get("on_found"):
            run_actions_fn(a["on_found"])
        if i < len(matches) - 1 and delay > 0:
            time.sleep(delay)
