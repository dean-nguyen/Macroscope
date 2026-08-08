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
from engine.humanize import DISABLED as _NO_JITTER, Humanize

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
        "wait":         lambda a: _wait(a, ctx),
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

    # Anything that drives the game, or merely waits, can have changed the
    # screen — so the iteration's shared capture must not be trusted past it.
    if t in _INVALIDATES_FRAME:
        im.invalidate_frame_scope()


# Action types that always touch the game or let time pass. The conditional
# ones (find_and_click and friends) invalidate from inside _click instead, so a
# tick where nothing is found still reuses its single capture.
_INVALIDATES_FRAME = frozenset({
    "move", "click", "double_click", "right_click", "drag", "scroll",
    "key", "type", "wait", "pixel_wait",
})

# Action types whose handler resolves xp/yp through _coords. Anything outside this
# set requires pixel x/y, and macro_engine validation enforces that — otherwise a
# macro using xp/yp on, say, `drag` would validate and then raise KeyError at run
# time, while `scroll` would silently act at (0, 0).
ACTIONS_WITH_PROPORTIONS = frozenset({
    "move", "click", "double_click", "right_click", "scroll",
})


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


def _humanize(ctx: Optional[Dict]) -> Humanize:
    """Jitter settings for this run. Absent means no jitter — a bare run_action call
    from a test or a tool should behave exactly as written."""
    value = (ctx or {}).get("humanize")
    return value if isinstance(value, Humanize) else _NO_JITTER


def _recognised(ctx: Optional[Dict]) -> None:
    """Record that the macro just recognised something on screen.

    macro_engine watches this to notice a stall. Every kind of recognition counts —
    a template, a pixel colour, a detected rectangle — because a macro driven by
    pixel checks is working just as much as one driven by templates, and killing it
    for "recognising nothing" would be a lie.
    """
    if ctx is not None:
        ctx["saw_expected"] = True


def _sent_input(ctx: Optional[Dict]) -> None:
    """Record that the macro actually acted on the target this iteration.

    The stall guard needs this: a macro that recognises nothing and *does* nothing
    is a watcher waiting for something to appear, which is fine, while one that
    keeps clicking at a screen it cannot recognise is the case worth stopping.
    """
    if ctx is not None:
        ctx["sent_input"] = True


def _clamp_click(x: int, y: int, ctx: Optional[Dict]):
    """Keep a scattered click inside the area it is allowed to land in.

    Without this, a 3 px scatter on a click at the very edge — `xp: 0.0`, or a
    pixel coordinate on the border — leaves the target: a posted click at (-2, -2)
    is silently dropped by the application, and in foreground mode pyautogui parks
    the real cursor on a screen corner, which is one of its failsafe points, so the
    *next* pyautogui call aborts the macro. Measured: with the default 3 px, a click
    at `xp: 0.999` left a 1280x720 client area 39 times out of 60.

    The one-pixel margin is what keeps a corner failsafe point out of reach.
    """
    cw = (ctx or {}).get("client_w") or 0
    ch = (ctx or {}).get("client_h") or 0
    if not (cw and ch):
        # Plain foreground: coordinates are screen-space and offsets are zero.
        try:
            cw, ch = pyautogui.size()
        except Exception:
            return x, y
    if x is not None:
        x = min(max(1, x), max(1, cw - 2))
    if y is not None:
        y = min(max(1, y), max(1, ch - 2))
    return x, y


def _scatter(x, y, ctx: Optional[Dict], max_px: Optional[int] = None):
    """Jitter a click point, then clamp it back inside the target.

    An exact point is returned untouched — jitter is the only thing that may need
    clamping, and a coordinate the macro author wrote is not ours to move.
    """
    jx, jy = _humanize(ctx).point(x, y, max_px=max_px)
    if (jx, jy) == (x, y):
        return x, y
    return _clamp_click(jx, jy, ctx)


def _coords(a: Dict, ctx: Optional[Dict]):
    """Resolve an action's target point, honouring proportional coordinates.

    ``x``/``y`` are pixels. ``xp``/``yp`` are fractions of the target window's
    client area (0.0-1.0), which keeps a macro working when the player runs the
    game at a different window size — the same guarantee template matching gives
    for images. Pixels win per axis if both are given.

    Only the single-point actions accept these; see ACTIONS_WITH_PROPORTIONS.
    """
    x, y = a.get("x"), a.get("y")
    xp = a.get("xp") if x is None else None      # pixels win, per axis
    yp = a.get("yp") if y is None else None
    if xp is None and yp is None:
        return x, y

    cw = (ctx or {}).get("client_w") or 0
    ch = (ctx or {}).get("client_h") or 0
    if not cw or not ch:
        # Reaching here means an axis has no pixel value to fall back on — if both
        # x and y were given, the per-axis precedence above already returned them.
        # Guessing would click at (0, 0) in background mode, or wherever the cursor
        # happens to sit in foreground mode: a wrong click with no warning.
        raise ActionError(
            "xp/yp need a target_window whose client size could be resolved; "
            "the window was not found, so there is nothing to take a fraction of"
        )

    if xp is not None:
        x = int(round(float(xp) * cw))
    if yp is not None:
        y = int(round(float(yp) * ch))
    return x, y


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
    x, y = _coords(a, ctx)
    if _is_bg(ctx):
        bg.post_move(_hwnd(ctx), x, y)
    else:
        pyautogui.moveTo(x + _ox(ctx), y + _oy(ctx),
                         duration=a.get("duration", 0.1))


def _click(a: Dict, ctx, jittered: bool = False) -> None:
    # Every clicking path funnels through here, including find_and_click, so this
    # is the one place that reliably knows a click really happened.
    im.invalidate_frame_scope()
    _sent_input(ctx)
    x, y = _coords(a, ctx)
    # `jittered` is a keyword, not a field in the action: callers that already
    # scattered their point against the size of the element they matched have a
    # better bound than anything available here, and a flag living in the action
    # dict would be spoofable by a user's JSON and would survive being saved.
    if not jittered:
        x, y = _scatter(x, y, ctx)
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
    _sent_input(ctx)
    rx, ry = _coords(a, ctx)
    if rx is not None and ry is not None:
        rx, ry = _scatter(rx, ry, ctx)
    x, y = (rx if rx is not None else 0), (ry if ry is not None else 0)
    if _is_bg(ctx):
        bg.post_double_click(_hwnd(ctx), x, y)
    else:
        if rx is not None:
            pyautogui.doubleClick(x + _ox(ctx), y + _oy(ctx))
        else:
            pyautogui.doubleClick()


def _right_click(a: Dict, ctx) -> None:
    _sent_input(ctx)
    rx, ry = _coords(a, ctx)
    if rx is not None and ry is not None:
        rx, ry = _scatter(rx, ry, ctx)
    x, y = (rx if rx is not None else 0), (ry if ry is not None else 0)
    if _is_bg(ctx):
        bg.post_right_click(_hwnd(ctx), x, y)
    else:
        if rx is not None:
            pyautogui.rightClick(x + _ox(ctx), y + _oy(ctx))
        else:
            pyautogui.rightClick()


def _drag(a: Dict, ctx) -> None:
    _sent_input(ctx)
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


# One wheel notch, as Windows counts it. background_input already multiplies by this
# for WM_MOUSEWHEEL; pyautogui does not — it hands `clicks` straight to mouse_event as
# dwData, so pyautogui.scroll(3) asks for 3/120 of a notch and nothing moves. The same
# macro therefore scrolled three notches in background mode and not at all in
# foreground, and the editor's default of 3 was the value that did nothing.
_WHEEL_NOTCH = 120


def _scroll(a: Dict, ctx) -> None:
    _sent_input(ctx)
    rx, ry = _coords(a, ctx)
    x, y = (rx if rx is not None else 0), (ry if ry is not None else 0)
    amount = a.get("amount", 3)
    if _is_bg(ctx):
        bg.post_scroll(_hwnd(ctx), x, y, amount)
    else:
        # `amount` means notches in both modes, so a macro written against one
        # behaves the same in the other.
        clicks = amount * _WHEEL_NOTCH
        ox, oy = _ox(ctx), _oy(ctx)
        if rx is not None:
            pyautogui.scroll(clicks, x=x + ox, y=y + oy)
        else:
            pyautogui.scroll(clicks)


def _key(a: Dict, ctx) -> None:
    _sent_input(ctx)
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
    _sent_input(ctx)
    text = a.get("text", "")
    interval = a.get("interval", 0.02)
    if _is_bg(ctx):
        bg.post_type(_hwnd(ctx), text, interval)
    else:
        pyautogui.typewrite(text, interval=interval)


def _wait(a: Dict, ctx=None) -> None:
    time.sleep(_humanize(ctx).delay(a.get("ms", 0)) / 1000.0)


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
    if success:
        _recognised(ctx)
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
    if matched:
        _recognised(ctx)

    status = "MATCH" if matched else "NO MATCH"
    _log(ctx,
         f"[pixel_check] {status} at window({a['x']},{a['y']}) "
         f"actual={list(actual)} expected={list(expected)} tol={tolerance}")

    branch = "on_match" if matched else "on_no_match"
    branch_actions = a.get(branch, [])
    if branch_actions:
        run_actions_fn(branch_actions)


# ── image-based actions ───────────────────────────────────────────────────────

# Templates already reported as uncaptured — so a looping macro logs each one
# once instead of every tick.
_warned_missing: set = set()


def _safe_find(a: Dict, sh, threshold: float, ctx, find_all: bool = False):
    """Run a template search, treating an uncaptured template as "not visible".

    A macro that references a screenshot the user has not captured yet used to
    raise out of the whole run, so one missing file killed the entire macro —
    which is the normal state of a freshly installed pack. Degrading to the
    no-match branch keeps the rest of the macro working, and the miss is logged
    (once per template) so it is not silent.
    """
    try:
        if find_all:
            found = im.find_all_templates(a["template"], hwnd=sh, threshold=threshold)
        else:
            found = im.find_template(a["template"], hwnd=sh, threshold=threshold)
        if found:
            _recognised(ctx)
        return found
    except im.TemplateMissing as exc:
        ref = a["template"]
        if ref not in _warned_missing:
            _warned_missing.add(ref)
            _log(ctx, f"[missing template] {exc} — treating as not found. "
                      f"Capture it via Images → Guided capture…")
        return [] if find_all else None


def _bound_of(match) -> int:
    """How far a click on *match* may be scattered and stay inside it.

    A match from image_matcher carries the size it matched at; anything else (an
    older tuple, a stub in a test) gives no bound, and 0 means "do not scatter"
    rather than "scatter freely".
    """
    return getattr(match, "jitter_bound", 0)


def _find_and_click(a: Dict, run_actions_fn: Callable, ctx) -> None:
    """Find a template image and click inside it."""
    sh = _search_hwnd(ctx)
    threshold = a.get("threshold", 0.80)
    result = _safe_find(a, sh, threshold, ctx)
    if result:
        cx, cy, score = result
        # Scatter the click within the matched element rather than always hitting its
        # exact centre, bounded by the size the template *matched* at — not the size
        # of the file. Matching is scale-aware, so on a half-size window a 40x40
        # template matches a 20x20 element, and the file's size would let the jitter
        # land outside it.
        jx, jy = _scatter(cx, cy, ctx, max_px=_bound_of(result))
        _log(ctx,
             f"[find_and_click] FOUND '{a['template']}' "
             f"at ({'client' if sh else 'screen'})({cx},{cy}) score={score:.3f}"
             + (f" → clicking ({jx},{jy})" if (jx, jy) != (cx, cy) else ""))
        click_a   = {"type": "click", "x": jx, "y": jy,
                     "button": a.get("button", "left")}
        click_ctx = _make_click_ctx_for_found(ctx, sh)
        _click(click_a, click_ctx, jittered=True)
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
        # A poller must never reuse the iteration's shared frame, or it would
        # re-test the same stale screenshot until it times out.
        im.invalidate_frame_scope()
        if _safe_find(a, sh, threshold, ctx):
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
    result    = _safe_find(a, sh, threshold, ctx)
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

    _recognised(ctx)
    _log(ctx, f"[find_rects] detected {len(rects)} rects")
    for i, (cx, cy, w, h) in enumerate(rects):
        _log(ctx, f"  [{i}] centre=({cx},{cy}) size={w}x{h}")

    index = a.get("index", 0)
    button = a.get("button", "left")
    click_delay = a.get("click_delay", 500) / 1000.0
    click_ctx = _make_click_ctx_for_found(ctx, sh)

    if index == "all":
        for i, (cx, cy, w, h) in enumerate(rects):
            jx, jy = _scatter(cx, cy, ctx, max_px=min(w, h) // 4)
            _log(ctx, f"[find_rects] clicking rect [{i}] at ({jx},{jy})")
            click_a = {"type": "click", "x": jx, "y": jy, "button": button}
            _click(click_a, click_ctx, jittered=True)
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
        jx, jy = _scatter(cx, cy, ctx, max_px=min(w, h) // 4)
        _log(ctx, f"[find_rects] clicking rect [{idx}] at ({jx},{jy})")
        click_a = {"type": "click", "x": jx, "y": jy, "button": button}
        _click(click_a, click_ctx, jittered=True)
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

    matches = _safe_find(a, sh, threshold, ctx, find_all=True)

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

    for i, match in enumerate(matches):
        cx, cy = match[0], match[1]
        # Bounded by this match's own size, as in find_and_click.
        jx, jy = _scatter(cx, cy, ctx, max_px=_bound_of(match))
        _log(ctx, f"[find_all] clicking [{i}] at ({jx},{jy})")
        click_a = {"type": "click", "x": jx, "y": jy, "button": button}
        _click(click_a, click_ctx, jittered=True)
        if a.get("on_found"):
            run_actions_fn(a["on_found"])
        if i < len(matches) - 1 and delay > 0:
            time.sleep(delay)
