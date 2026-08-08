"""
Template matching engine — powered by OpenCV.

Uses cv2.matchTemplate with TM_CCOEFF_NORMED for fast, robust matching.
OpenCV's implementation is C++-optimized and handles edge cases reliably.

Coordinate spaces
-----------------
  hwnd given  → haystack is the client area captured via PrintWindow / screen grab
                → returned (cx, cy) are client-space coordinates.
  hwnd=None   → haystack is the whole screen (or a sub-region)
                → returned (cx, cy) are absolute screen coordinates.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageGrab

from engine.paths import TEMPLATES_DIR, data_root

log = logging.getLogger(__name__)


class TemplateMissing(FileNotFoundError):
    """A macro referenced a template image that has not been captured yet.

    Subclasses FileNotFoundError so existing callers keep working, but lets the
    action runner tell "user hasn't captured this screenshot yet" apart from a
    genuine I/O failure — the former should degrade to "not found" instead of
    killing the whole macro run.
    """


class TemplateUnusable(TemplateMissing):
    """The template exists but cannot be matched meaningfully.

    Raised for flat, featureless captures. TM_CCOEFF_NORMED divides by the
    template's standard deviation, so a template with (near-)zero variance —
    an empty panel, a plain background, a solid button fill — correlates
    perfectly with *anything* and scores 1.0 everywhere. Matching such an image
    would not find a button, it would click a random spot, so it is refused.
    Handled like a missing template: the check misses and says why.
    """


# Below this standard deviation a template carries too little structure for
# normalised correlation to mean anything. Public because the capture wizard and
# tools/ check a crop against the same bar the matcher will hold it to.
MIN_NEEDLE_STD = 3.0
_MIN_NEEDLE_STD = MIN_NEEDLE_STD


def _clamp_score(raw: float) -> float:
    """Report TM_CCOEFF_NORMED as it is, with anticorrelation floored at 0.

    Scores used to be remapped as (raw + 1) / 2, which squeezed everything usable
    into [0.5, 1.0]: zero correlation read as 0.50, and unrelated screen content sat
    around 0.70. A user writing threshold=0.70 believed they were asking for "70%
    sure" and were in fact asking for "no correlation at all". Measured on a live
    game window, a template that IS present scores ~0.92 raw and absent ones reach
    ~0.47 raw, so the raw number separates them clearly and means what it says.
    """
    return max(0.0, float(raw))


# Scales searched when a template does not match at its captured size, i.e. when
# the game runs at a different window size than the one it was captured at.
#
# Matching is unforgiving about scale: measured on a 2840-wide capture, the true
# ratio has to be hit within about 1.5% to clear a 0.90 threshold. At a 1920-wide
# window (true ratio 0.676) a rung of 0.667 scored 0.908 and 0.700 scored 0.804,
# where 0.676 scores 1.000. The floor also has to reach 0.451 to cover 1280x720.
#
# Satisfying that with a single ladder needs ~75 rungs, and every rung is a full
# matchTemplate — 284 ms on a 2560x1380 window, so a 19-second stall per template.
# Instead the search is two-stage: a coarse ladder finds which neighbourhood scores
# best, then a fine pass around the winner finds the scale. ~21 matches for the
# same precision. A coarse *veto* was tried first and abandoned; see _discover_scale.
def _build_scale_ladder(low: float = 0.4, high: float = 2.5,
                        step: float = 1.12) -> Tuple[float, ...]:
    rungs, value = [], low
    while value <= high:
        rungs.append(round(value, 4))
        value *= step
    # Search outward from 1.0: the common case is a window near the captured size.
    return tuple(sorted(rungs, key=lambda s: abs(s - 1.0)))


_SCALE_LADDER = _build_scale_ladder()

# Refinement steps around the best coarse rung. The coarse ladder steps 12%, so
# the true scale is within 6% of the winner; +-6% at 1.5% covers it.
_REFINE_FACTORS = tuple(round(1.0 + i * 0.015, 4) for i in range(-4, 5))

# Walking the ladder costs one matchTemplate per rung, and a polling macro spends
# most of its ticks matching NOTHING — so sweeping on every miss would multiply
# the cost of the common case. Discovery is rationed by TIME only, and never
# switched off: a macro is normally started before the element it waits for is on
# screen, so any attempt budget gets spent while the element is legitimately
# absent, and the template can then never be found again for the life of the
# process. Rationing by time bounds the cost without ever giving up.
# Rationed per WINDOW SIZE, not per template. A sweep costs ~6.9 s on a 2560x1380
# window, so nine templates each sweeping on their own schedule would spend 62 s of
# every 20 s interval searching — the macro would never stop sweeping. One sweep per
# interval is enough because the answer generalises: whichever template resolves the
# scale records it in _window_scale, and the others then try that first for the price
# of a single match.
#
# But that only holds once *some* template has answered, and only a template that is
# actually on screen can answer. Rationing by window size alone starved the one that
# could: measured against a live game window at 0.44x, five templates scored in a row
# all missed, because the first (absent) one spent the interval and the next four were
# refused discovery in 0.05 s each. Scored alone with a clean cache, the template whose
# button was plainly visible matched at 0.94. Every pack macro checks absent guard
# templates first, so in a 2.5 s poll loop the scale could never be discovered at all —
# which is why the pack only ever worked at exactly the capture size.
#
# So a template that has never had a discovery pass at this window size is allowed one,
# subject only to a short floor that stops a single tick spending several sweeps at
# once. Templates already tried fall back to the long interval. The one-off cost is
# (number of templates x sweep), paid a tick or two at a time, and it ends the moment
# any visible template answers.
_DISCOVERY_INTERVAL = 20.0

# The floor between two first-time sweeps is "however long the last one took", never
# less than this. A fixed floor cannot serve both ends: a sweep measured 1.1 s on a
# 1236x696 window and ~6.9 s on 2560x1380, so 1 s would let eight templates spend 55 s
# inside a single 2.5 s tick on the big window — blind for a minute, which is worse than
# converging a few seconds later. Waiting out the last sweep's own cost keeps discovery
# to roughly half the wall clock whatever the window size, and it needs no per-window
# tuning.
_SWEEP_FLOOR = 1.0

# Diagnostics (tools/) need the answer more than they need the budget: scoring a whole
# templates directory in one pass is exactly the batch the floor is there to slow down,
# and a report that says "no match" because of rationing is worse than a slow one.
_unrationed = False


def set_unrationed_discovery(enabled: bool = True) -> None:
    """Let every template have a scale search, whatever it costs (diagnostics only).

    A macro must never turn this on: it is the cost the rationing exists to bound.
    Prefer `unrationed_discovery()`, which cannot be left on.
    """
    global _unrationed
    _unrationed = bool(enabled)


@contextlib.contextmanager
def unrationed_discovery():
    """Scope the diagnostics override so it cannot outlive the report that wanted it.

    It is a module global, and the in-app template report runs in the same process as
    the macros. Left on, every later run pays for unlimited scale searches — a
    diagnostic that quietly changes how the thing being diagnosed behaves.
    """
    global _unrationed
    previous = _unrationed
    _unrationed = True
    try:
        yield
    finally:
        _unrationed = previous

# (resolved template path, haystack w, haystack h) -> scale that matched
_scale_cache: dict = {}
# (haystack w, haystack h) -> a scale that worked for SOME template at this window
# size. Used only as a first guess in _scale_order: a pack is usually captured at
# one resolution, so one template's answer is a good hint for the others. It must
# never gate discovery — templates in a pack can come from different sessions at
# different window sizes, and one of them answering would otherwise permanently
# strand all the rest.
_window_scale: dict = {}
_sweep_state: dict = {}      # (haystack w, h) -> monotonic time of the last sweep
_sweep_cost: dict = {}       # (haystack w, h) -> seconds the last sweep there took
# (resolved template path, haystack w, h) -> monotonic time of that template's last
# discovery pass. Per template, not per window size: the retry clock has to be, or
# whichever template is scored first takes every slot forever.
_swept: dict = {}
# (haystack w, h) -> the keys that have asked for a search at this size. Needed to
# answer "who has waited longest", which is what stops the rotation from starving
# everything behind it in scoring order.
_seen: dict = {}

# Guards the caches above: several macros can match concurrently (run_folder).
_scale_lock = threading.Lock()


class Match(tuple):
    """``(cx, cy, score)`` with the size the template actually matched at attached.

    Existing code unpacks three values, so this stays a 3-tuple. ``w``/``h`` are the
    needle's size *after* scaling, which is the only size a caller may reason about:
    matching is scale-aware, so a 40x40 template can match a 20x20 element on a
    half-size window. Bounding click jitter by the file's size instead would let a
    scattered click land outside the element that was matched.
    """

    # No __slots__: a variable-length builtin subtype cannot have them.

    def __new__(cls, cx: int, cy: int, score: float, w: int = 0, h: int = 0):
        self = super().__new__(cls, (cx, cy, score))
        self.w, self.h = int(w), int(h)
        return self

    def moved(self, dx: int, dy: int) -> "Match":
        """The same match, offset — used when the haystack was a sub-region."""
        return Match(self[0] + dx, self[1] + dy, self[2], self.w, self.h)

    @property
    def jitter_bound(self) -> int:
        """How far a click may be scattered and still be inside what was matched:
        a quarter of the smaller side. 0 for a match too small to scatter within."""
        return min(self.w, self.h) // 4


def clear_scale_cache() -> None:
    """Forget discovered template scales (used by tests and on window resize)."""
    global _unrationed
    # Also drops the diagnostics override. It is a module global with no context
    # manager, so anything that turns it on inside this process — a future in-app
    # "why doesn't my template match?" panel, for instance — would otherwise leave
    # every later macro run paying for unlimited searches.
    _unrationed = False
    with _scale_lock:
        _scale_cache.clear()
        _window_scale.clear()
        _sweep_state.clear()
        _sweep_cost.clear()
        _swept.clear()
        _seen.clear()


def _claim_sweep(key: tuple, take: bool = True) -> bool:
    """Whether this template may spend a scale search right now — and claim the slot.

    Three rules, all of which have to allow it. Each of the first two replaced a
    plausible design that measurement killed:

    - **One search at a time per window size.** The floor is what the last search
      there cost. A fixed floor cannot serve a 1.1 s search and a 6.9 s one.
    - **A template waits out ``_DISCOVERY_INTERVAL`` after its own last search.** A
      clock kept per *window size* instead hands every slot to whichever template is
      scored first, and pack macros check absent guard templates first, so the visible
      one starves. Measured: 24 sweeps for the first guard, 0 for the template on
      screen.
    - **The slot goes to the template that has waited longest**, with "never searched"
      counting as forever. Without this, the two rules above still starve everything
      past roughly ``_DISCOVERY_INTERVAL / tick`` positions in scoring order, because
      templates already in the rotation keep taking the slot from those behind them.
      Measured with this pack's own order — 8 templates, the one on screen scored 8th
      behind seven absent guards, 1.1 s searches, 2.5 s poll: after 400 ticks the first
      six guards had swept 66-67 times each, the visible template **zero**, and it was
      never found. With this rule: all 17 templates served, found on tick 17, sweeps
      even at 22-23 each.

    Asking registers the template as waiting at this size — a template that is always
    refused must still join the queue, or it can never become the stalest.

    Check and claim happen under one lock. Two acquisitions let 8 threads start 4
    concurrent searches where the floor allows 1 (measured with a 1 µs switch
    interval), and ``run_folder`` runs macros in parallel by default.
    """
    if _unrationed:
        return True
    with _scale_lock:
        size = key[1:]
        now = time.monotonic()
        waiting = _seen.setdefault(size, set())
        waiting.add(key)

        if (now - _sweep_state.get(size, 0.0)) < max(_SWEEP_FLOOR,
                                                     _sweep_cost.get(size, 0.0)):
            return False

        def waited(k) -> float:
            last = _swept.get(k)
            return float("inf") if last is None else now - last

        mine = waited(key)
        if mine < _DISCOVERY_INTERVAL:
            return False
        if mine < max(waited(k) for k in waiting):
            return False            # someone else has been waiting longer

        if take:
            _sweep_state[size] = now
            _swept[key] = now
        return True


def _may_sweep(key: tuple) -> bool:
    """The same decision without taking the slot. For tests and readability."""
    return _claim_sweep(key, take=False)


def _note_sweep(key: tuple) -> None:
    """Record a search without going through the decision — for tests setting up a
    state. Production code claims through _claim_sweep, which records it itself."""
    with _scale_lock:
        now = time.monotonic()
        _sweep_state[key[1:]] = now
        _swept[key] = now
        _seen.setdefault(key[1:], set()).add(key)


def _note_sweep_cost(key: tuple, seconds: float) -> None:
    """Record what the search cost, and count both floors from when it finished."""
    with _scale_lock:
        now = time.monotonic()
        size = key[1:]
        _sweep_cost[size] = seconds
        _sweep_state[size] = now
        _swept[key] = now


def _record_scale(key: tuple, scale: float) -> None:
    with _scale_lock:
        _scale_cache[key] = scale
        if scale != 1.0:
            _window_scale[key[1:]] = scale


# ── per-tick frame sharing ────────────────────────────────────────────────────
#
# Every image action used to take its own screenshot, so one iteration of a
# macro with seven image checks grabbed seven frames of the same screen. Inside
# a frame scope the capture is taken once and reused, which is both far cheaper
# and more correct: all checks in one iteration now reason about the *same*
# screen instead of racing a UI that may change between them.

# The scope is per-THREAD. Each macro runs on its own thread and several can run
# at once (run_folder), so a shared depth counter would never return to zero while
# any macro was looping — the frames would stop being cleared and every macro
# would keep polling one frozen screenshot. A shared counter is also a non-atomic
# read-modify-write, which drifts upward under contention and never recovers.
_frame_state = threading.local()


def _scope() -> dict:
    scope = getattr(_frame_state, "scope", None)
    if scope is None:
        scope = _frame_state.scope = {"depth": 0, "frames": {}}
    return scope


def begin_frame_scope() -> None:
    """Start reusing one capture for every match until the scope ends."""
    _scope()["depth"] += 1


def end_frame_scope() -> None:
    scope = _scope()
    scope["depth"] = max(0, scope["depth"] - 1)
    if scope["depth"] == 0:
        scope["frames"].clear()


def invalidate_frame_scope() -> None:
    """Drop the shared capture — for pollers that must see a fresh screen."""
    scope = _scope()
    scope["frames"].clear()


def _grab_haystack(hwnd: Optional[int],
                   region: Optional[Tuple[int, int, int, int]]) -> Optional[np.ndarray]:
    """Capture the search area, reusing the scope's frame when one is active."""
    scope = _scope()
    key = ("hwnd", hwnd) if hwnd is not None else ("region", region)
    if scope["depth"] > 0 and key in scope["frames"]:
        return scope["frames"][key]

    if hwnd is not None:
        frame = _capture_hwnd_cv(hwnd)
    elif region is not None:
        x, y, w, h = region
        frame = _capture_screen_cv(bbox=(x, y, x + w, y + h))
    else:
        frame = _capture_screen_cv()

    if frame is not None and scope["depth"] > 0:
        scope["frames"][key] = frame
    return frame


# ── public API ────────────────────────────────────────────────────────────────

def find_template(
    template_path: str,
    hwnd: Optional[int] = None,
    region: Optional[Tuple[int, int, int, int]] = None,
    threshold: float = 0.80,
    **_kwargs,
) -> Optional[Tuple[int, int, float]]:
    """
    Find *template_path* inside a screenshot.

    Parameters
    ----------
    template_path : str
        Path to the template PNG (absolute, or relative to project root).
    hwnd : int, optional
        Win32 window handle.  When given, the haystack is captured via
        PrintWindow (background-safe) and coordinates are client-space.
    region : (x, y, w, h) in screen coords, optional
        Crop the screen capture to this rectangle (ignored when hwnd given).
    threshold : float
        Minimum similarity score in [0, 1].  0.80 is a good default.

    Returns
    -------
    (cx, cy, score) or None
        Centre of the best match and its similarity score.
    """
    needle, resolved = _load_needle(template_path)
    haystack = _grab_haystack(hwnd, region)
    if haystack is None:
        return None

    # Lower threshold when WGC captured the frame (different color pipeline).
    effective = threshold - _WGC_THRESHOLD_OFFSET if _is_wgc_active(hwnd) else threshold
    key = (resolved, haystack.shape[1], haystack.shape[0])
    result = _match_scaled(haystack, needle, effective, key)
    if result is None:
        return None

    # Adjust for region offset when haystack was a sub-region of the screen.
    if region is not None and hwnd is None:
        result = result.moved(region[0], region[1])

    return result


def find_all_templates(
    template_path: str,
    hwnd: Optional[int] = None,
    region: Optional[Tuple[int, int, int, int]] = None,
    threshold: float = 0.80,
) -> List[Tuple[int, int, float]]:
    """
    Find ALL occurrences of a template (not just the best one).

    Returns list of (cx, cy, score) sorted by score descending.
    """
    needle, resolved = _load_needle(template_path)
    haystack = _grab_haystack(hwnd, region)
    if haystack is None:
        return []

    effective = threshold - _WGC_THRESHOLD_OFFSET if _is_wgc_active(hwnd) else threshold
    key = (resolved, haystack.shape[1], haystack.shape[0])
    results = _match_all_scaled(haystack, needle, effective, key)

    # Adjust for region offset
    if region is not None and hwnd is None:
        results = [m.moved(region[0], region[1]) for m in results]

    return results


# ── capture helpers ───────────────────────────────────────────────────────────

def _is_window_valid(hwnd: int) -> bool:
    """Check if window handle is still valid, visible, and not minimized."""
    try:
        import win32gui
        # Check if window exists
        if not win32gui.IsWindow(hwnd):
            return False
        # Check if window is minimized
        if win32gui.IsIconic(hwnd):
            return False
        # Check if window has a valid client rect
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        return (right - left) > 0 and (bottom - top) > 0
    except Exception:
        return False


def _capture_screen(bbox=None) -> Optional[np.ndarray]:
    """Capture screen as float32 RGB (kept for rect_detector compatibility)."""
    try:
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        return np.asarray(img.convert("RGB"), dtype=np.float32)
    except Exception:
        return None


def _capture_screen_cv(bbox=None) -> Optional[np.ndarray]:
    """Capture screen as uint8 BGR (OpenCV convention)."""
    try:
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def _capture_hwnd_cv(hwnd: int) -> Optional[np.ndarray]:
    """
    Capture the client area of *hwnd* as uint8 BGR — COMPLETELY SILENT.

    No z-order changes, no minimize/restore, no focus changes.

      1. WGC — works on GPU apps, emulators, and occluded windows.
      2. Screen grab — fallback when WGC is unavailable.
    """
    if not _is_window_valid(hwnd):
        log.debug("capture_hwnd: hwnd %s invalid/minimized", hwnd)
        return None

    # WGC — primary capture method (works even when window is covered)
    try:
        from engine import wgc_capture
        if wgc_capture.is_available():
            img = wgc_capture.get_frame(hwnd)
            if _looks_valid_bgr(img):
                return img
            log.debug("capture_hwnd: WGC frame invalid for hwnd %s "
                      "(shape=%s, std=%.1f)", hwnd,
                      img.shape if img is not None else None,
                      float(np.std(img)) if img is not None else 0)
    except Exception as exc:
        log.warning("capture_hwnd: WGC error for hwnd %s: %s", hwnd, exc)

    # Screen grab fallback (only works when window is on top)
    screen_grab = _try_screen_grab_window_cv(hwnd)
    if _looks_valid_bgr(screen_grab):
        return screen_grab

    log.warning("capture_hwnd: ALL methods failed for hwnd %s", hwnd)
    return None


# A template captured through one backend and matched against the other loses some
# correlation, because WGC reads the DirectX compositor while a screen grab reads
# GDI. Measured on a live game window by capturing both ways and cross-scoring the
# same regions:
#
#   static UI (bottom bar, right column)   0.037 - 0.046 raw
#   animated areas (counters, characters)  up to 0.36 raw
#
# The animated numbers are not colour: a control run comparing two WGC frames 50 ms
# apart reproduced most of that drift on its own. A template of an animated region
# is unreliable whatever the backend, so the allowance is set from the static
# measurement — 0.08 raw, roughly double the worst honest case.
#
# It used to be 0.10 in the old remapped score, i.e. 0.20 raw: four times what is
# needed, silently loosening every threshold in every macro. That is why absent
# templates scoring 0.47 raw came close to passing a nominal 0.60 floor.
_WGC_THRESHOLD_OFFSET = 0.08


def _is_wgc_active(hwnd: Optional[int]) -> bool:
    """True if *hwnd* currently has an active WGC session."""
    if hwnd is None:
        return False
    try:
        from engine import wgc_capture
        return hwnd in wgc_capture._manager._sessions
    except Exception:
        return False


def _looks_valid_bgr(img: Optional[np.ndarray]) -> bool:
    """Reject obviously-blank BGR uint8 frames."""
    if img is None or img.size == 0:
        return False
    try:
        return float(np.std(img)) > 4.0
    except Exception:
        return False


def _try_screen_grab_window(hwnd: int) -> Optional[np.ndarray]:
    """Screen grab of window client area as float32 RGB (for rect_detector)."""
    try:
        import win32gui
        cx0, cy0 = win32gui.ClientToScreen(hwnd, (0, 0))
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        w, h = right - left, bottom - top
        if w <= 0 or h <= 0:
            return None
        bbox = (cx0, cy0, cx0 + w, cy0 + h)
        return _capture_screen(bbox=bbox)
    except Exception:
        return _capture_screen()


def _try_screen_grab_window_cv(hwnd: int) -> Optional[np.ndarray]:
    """Screen grab of window client area as uint8 BGR (for OpenCV matching).

    Works even if window is partially occluded (grabs visible parts).
    Returns None only if window is completely offscreen or has zero size.
    """
    try:
        import win32gui
        cx0, cy0 = win32gui.ClientToScreen(hwnd, (0, 0))
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        w, h = right - left, bottom - top
        if w <= 0 or h <= 0:
            return None
        bbox = (cx0, cy0, cx0 + w, cy0 + h)
        result = _capture_screen_cv(bbox=bbox)
        # Validate result has actual content (not all black/blank)
        if result is not None and _looks_valid_bgr(result):
            return result
        return None
    except Exception:
        return None


# ── template loading & scale handling ────────────────────────────────────────

def imread_unicode(path) -> Optional[np.ndarray]:
    """Read an image OpenCV cannot open itself.

    `cv2.imread` goes through a narrow-char API on Windows and returns None for any
    path containing non-ASCII characters. Templates live under `%APPDATA%/Macroscope`,
    so a single accented character in a profile name would make every template in a
    pack report as unreadable.
    """
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _load_needle(template_path: str) -> Tuple[np.ndarray, str]:
    """Resolve *template_path* and read it, or raise TemplateMissing."""
    path = Path(template_path)
    if not path.is_absolute():
        path = data_root() / path
    if not path.exists():
        raise TemplateMissing(f"Template not captured yet: {path}")
    needle = imread_unicode(path)
    if needle is None:
        raise TemplateMissing(f"Template image is unreadable/corrupt: {path}")
    if float(needle.std()) < _MIN_NEEDLE_STD:
        raise TemplateUnusable(
            f"Template is flat/featureless so it would match anywhere: {path} — "
            f"re-capture it with more distinctive detail inside the box"
        )
    return needle, str(path)


def _resize_needle(needle: np.ndarray, scale: float) -> np.ndarray:
    h, w = needle.shape[:2]
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(needle, (nw, nh), interpolation=interp)


def _scale_order(key: tuple) -> List[float]:
    """Scales worth trying cheaply, best guess first: this template's known
    scale, then whatever scale the window is known to run at, then the size the
    template was captured at."""
    with _scale_lock:
        guesses = (_scale_cache.get(key), _window_scale.get(key[1:]), 1.0)
    order = []
    for candidate in guesses:
        if candidate is not None and candidate not in order:
            order.append(candidate)
    return order


def _score_at(haystack: np.ndarray, needle: np.ndarray, scale: float) -> float:
    """Best correlation for *needle* resized by *scale*, with no threshold."""
    scaled = needle if scale == 1.0 else _resize_needle(needle, scale)
    if (scaled.shape[0] > haystack.shape[0] or scaled.shape[1] > haystack.shape[1]
            or float(scaled.std()) < _MIN_NEEDLE_STD):
        return -1.0
    result = cv2.matchTemplate(haystack, scaled, cv2.TM_CCOEFF_NORMED)
    return _clamp_score(cv2.minMaxLoc(result)[1])


def _best_of(haystack, needle, scales) -> Tuple[Optional[float], float]:
    best_scale, best_score = None, -1.0
    for s in scales:
        score = _score_at(haystack, needle, s)
        if score > best_score:
            best_scale, best_score = s, score
    return best_scale, best_score


def _discover_scale(haystack: np.ndarray, needle: np.ndarray) -> Optional[float]:
    """Find the scale at which *needle* best matches, coarse then refined.

    Scanning for the best SCORE, rather than for the first rung above a threshold,
    is what lets the ladder be coarse: the winner locates the neighbourhood and the
    refinement finds the scale itself. ~21 matchTemplate calls in total, against
    ~75 for a single ladder fine enough to land within matching's tolerance.
    """
    coarse, coarse_score = _best_of(haystack, needle, _SCALE_LADDER)
    if coarse is None or coarse_score < 0:
        return None
    fine = [round(coarse * f, 4) for f in _REFINE_FACTORS]
    refined, refined_score = _best_of(haystack, needle, fine)
    return refined if refined_score >= coarse_score else coarse


def _match_scaled(haystack, needle, threshold, key):
    """_cv_match, but tolerant of the game running at a different window size
    than the template was captured at.

    The cheap path — the template's known scale, the window's known scale, then
    the captured size — runs first, so a normal tick costs one or two
    matchTemplate calls. The full ladder only runs when none of those hit, and is
    rationed by time in _may_sweep so a macro that legitimately matches nothing
    does not pay for discovery on every tick — but is never disabled outright,
    because "nothing matched yet" is the normal state before an element appears.
    """
    for s in _scale_order(key):
        result = _cv_match(haystack, needle if s == 1.0 else _resize_needle(needle, s),
                           threshold)
        if result:
            _record_scale(key, s)
            return result

    if not _claim_sweep(key):
        return None

    started = time.monotonic()
    try:
        scale = _discover_scale(haystack, needle)
    finally:
        # In a finally: a search that raises must still spend its ration, or a template
        # whose search blows up gets a free retry on every single tick.
        _note_sweep_cost(key, time.monotonic() - started)
    if scale is None:
        return None
    result = _cv_match(haystack, _resize_needle(needle, scale)
                       if scale != 1.0 else needle, threshold)
    if result:
        _record_scale(key, scale)
        log.info("template %s matched at scale %.3f for a %dx%d window "
                 "(captured at a different size) — caching for this window",
                 Path(key[0]).name, scale, key[1], key[2])
    return result


def _match_all_scaled(haystack, needle, threshold, key):
    """find_all counterpart of _match_scaled."""
    for s in _scale_order(key):
        results = _cv_match_all(haystack, needle if s == 1.0 else _resize_needle(needle, s),
                                threshold)
        if results:
            _record_scale(key, s)
            return results

    if not _claim_sweep(key):
        return []

    started = time.monotonic()
    try:
        tried = set(_scale_order(key))
        for s in _SCALE_LADDER:
            if s in tried:
                continue
            results = _cv_match_all(haystack, _resize_needle(needle, s), threshold)
            if results:
                _record_scale(key, s)
                return results
        return []
    finally:
        _note_sweep_cost(key, time.monotonic() - started)


# ── OpenCV template matching ─────────────────────────────────────────────────

def _cv_match(
    haystack: np.ndarray,
    needle: np.ndarray,
    threshold: float,
) -> Optional[Tuple[int, int, float]]:
    """
    Find the best match using OpenCV's matchTemplate (TM_CCOEFF_NORMED).

    Returns (cx, cy, score) or None.
    """
    th, tw = needle.shape[:2]
    sh, sw = haystack.shape[:2]

    if th > sh or tw > sw:
        return None

    # Defence in depth: _load_needle rejects flat templates, but a needle can
    # also arrive here rescaled or from another caller. A zero-variance needle
    # scores 1.0 against anything, so never let one report a match.
    if float(needle.std()) < _MIN_NEEDLE_STD:
        return None

    result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    score = _clamp_score(max_val)

    if score >= threshold:
        cx = max_loc[0] + tw // 2
        cy = max_loc[1] + th // 2
        return Match(cx, cy, score, tw, th)

    return None


def _cv_match_all(
    haystack: np.ndarray,
    needle: np.ndarray,
    threshold: float,
) -> List[Tuple[int, int, float]]:
    """
    Find ALL matches above threshold using non-maximum suppression.

    Returns list of (cx, cy, score) sorted by score descending.
    """
    th, tw = needle.shape[:2]
    sh, sw = haystack.shape[:2]

    if th > sh or tw > sw:
        return []

    # Same flat-needle guard as _cv_match: a zero-variance needle would otherwise
    # report matches everywhere.
    if float(needle.std()) < _MIN_NEEDLE_STD:
        return []

    result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)

    locations = np.where(result >= threshold)
    matches = []

    for pt_y, pt_x in zip(*locations):
        score = _clamp_score(result[pt_y, pt_x])
        cx = pt_x + tw // 2
        cy = pt_y + th // 2
        matches.append(Match(cx, cy, score, tw, th))

    if not matches:
        return []

    # Non-maximum suppression: remove overlapping detections
    matches = _nms(matches, tw, th)
    matches.sort(key=lambda m: m[2], reverse=True)
    return matches


def _nms(
    matches: List[Tuple[int, int, float]],
    tw: int,
    th: int,
    overlap_thresh: float = 0.5,
) -> List[Tuple[int, int, float]]:
    """Non-maximum suppression to remove overlapping detections."""
    if not matches:
        return matches

    # Sort by score descending
    matches = sorted(matches, key=lambda m: m[2], reverse=True)
    keep = []

    for match in matches:
        cx, cy = match[0], match[1]
        # Check overlap with already-kept detections
        overlaps = False
        for kx, ky, _ in keep:
            # Simple centre-distance check (faster than IoU for same-size templates)
            if abs(cx - kx) < tw * overlap_thresh and abs(cy - ky) < th * overlap_thresh:
                overlaps = True
                break
        if not overlaps:
            # Kept as-is, so a Match keeps the size it matched at.
            keep.append(match)

    return keep
