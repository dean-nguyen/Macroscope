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
# normalised correlation to mean anything.
_MIN_NEEDLE_STD = 3.0


# Scales tried when a template does not match at its captured size, i.e. when the
# game runs at a different window size than the one the template was captured at.
#
# The rungs have to be fine, because template matching is unforgiving about scale:
# measured on a 2840-wide capture, the true ratio must be hit within about 1.5% to
# clear a 0.90 threshold. A hand-written ladder with 10% gaps missed most real
# window sizes — at a 1920-wide window (true ratio 0.676) the nearest rung 0.667
# scored 0.908 and 0.700 scored 0.804, where 0.676 scores 1.000. The old floor of
# 0.5 also excluded 1280x720, which needs 0.451.
#
# A sweep is affordable at this density because a rung at the wrong scale is
# rejected by the coarse pass for a fraction of a full match, and sweeps are
# rationed to one per _DISCOVERY_INTERVAL per template anyway.
def _build_scale_ladder(low: float = 0.4, high: float = 2.5,
                        step: float = 1.025) -> Tuple[float, ...]:
    rungs, value = [], low
    while value <= high:
        rungs.append(round(value, 4))
        value *= step
    # Search outward from 1.0: the common case is a window near the captured size.
    return tuple(sorted(rungs, key=lambda s: abs(s - 1.0)))


_SCALE_LADDER = _build_scale_ladder()

# Walking the ladder costs one matchTemplate per rung, and a polling macro spends
# most of its ticks matching NOTHING — so sweeping on every miss would multiply
# the cost of the common case. Discovery is rationed by TIME only, and never
# switched off: a macro is normally started before the element it waits for is on
# screen, so any attempt budget gets spent while the element is legitimately
# absent, and the template can then never be found again for the life of the
# process. Rationing by time bounds the cost without ever giving up.
_DISCOVERY_INTERVAL = 20.0   # seconds between ladder sweeps for the same template

# (resolved template path, haystack w, haystack h) -> scale that matched
_scale_cache: dict = {}
# (haystack w, haystack h) -> a scale that worked for SOME template at this window
# size. Used only as a first guess in _scale_order: a pack is usually captured at
# one resolution, so one template's answer is a good hint for the others. It must
# never gate discovery — templates in a pack can come from different sessions at
# different window sizes, and one of them answering would otherwise permanently
# strand all the rest.
_window_scale: dict = {}
_sweep_state: dict = {}      # key -> monotonic time of the last sweep

# Guards the caches above: several macros can match concurrently (run_folder).
_scale_lock = threading.Lock()


def clear_scale_cache() -> None:
    """Forget discovered template scales (used by tests and on window resize)."""
    with _scale_lock:
        _scale_cache.clear()
        _window_scale.clear()
        _sweep_state.clear()


def _may_sweep(key: tuple) -> bool:
    """Whether to spend a full ladder sweep on this template right now."""
    with _scale_lock:
        last = _sweep_state.get(key, 0.0)
        return (time.monotonic() - last) >= _DISCOVERY_INTERVAL


def _note_sweep(key: tuple) -> None:
    with _scale_lock:
        _sweep_state[key] = time.monotonic()


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
        scope = _frame_state.scope = {"depth": 0, "frames": {}, "coarse": {}}
    return scope


def begin_frame_scope() -> None:
    """Start reusing one capture for every match until the scope ends."""
    _scope()["depth"] += 1


def end_frame_scope() -> None:
    scope = _scope()
    scope["depth"] = max(0, scope["depth"] - 1)
    if scope["depth"] == 0:
        scope["frames"].clear()
        scope["coarse"].clear()


def invalidate_frame_scope() -> None:
    """Drop the shared capture — for pollers that must see a fresh screen."""
    scope = _scope()
    scope["frames"].clear()
    scope["coarse"].clear()


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

    cx, cy, score = result

    # Adjust for region offset when haystack was a sub-region of the screen.
    if region is not None and hwnd is None:
        cx += region[0]
        cy += region[1]

    return (cx, cy, score)


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
        results = [(cx + region[0], cy + region[1], s) for cx, cy, s in results]

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


# WGC captures via DirectX compositor produce slightly different pixel values
# than GDI screen-grab (the source used to create templates).  The systematic
# brightness/gamma shift reduces TM_CCOEFF_NORMED scores by ~0.08-0.15.
# This constant compensates so that user-facing thresholds behave consistently
# regardless of the capture backend.
_WGC_THRESHOLD_OFFSET = 0.10


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

def _load_needle(template_path: str) -> Tuple[np.ndarray, str]:
    """Resolve *template_path* and read it, or raise TemplateMissing."""
    path = Path(template_path)
    if not path.is_absolute():
        path = data_root() / path
    if not path.exists():
        raise TemplateMissing(f"Template not captured yet: {path}")
    needle = cv2.imread(str(path), cv2.IMREAD_COLOR)
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

    if not _may_sweep(key):
        return None

    _note_sweep(key)
    tried = set(_scale_order(key))
    for s in _SCALE_LADDER:
        if s in tried:
            continue
        result = _cv_match(haystack, _resize_needle(needle, s), threshold)
        if result:
            _record_scale(key, s)
            log.info("template %s matched at scale %.3f for a %dx%d window "
                     "(captured at a different size) — caching for this window",
                     Path(key[0]).name, s, key[1], key[2])
            return result
    return None


def _match_all_scaled(haystack, needle, threshold, key):
    """find_all counterpart of _match_scaled."""
    for s in _scale_order(key):
        results = _cv_match_all(haystack, needle if s == 1.0 else _resize_needle(needle, s),
                                threshold)
        if results:
            _record_scale(key, s)
            return results

    if not _may_sweep(key):
        return []

    _note_sweep(key)
    tried = set(_scale_order(key))
    for s in _SCALE_LADDER:
        if s in tried:
            continue
        results = _cv_match_all(haystack, _resize_needle(needle, s), threshold)
        if results:
            _record_scale(key, s)
            return results
    return []


# ── OpenCV template matching ─────────────────────────────────────────────────

# A full-resolution matchTemplate over a 2840x1600 game window costs ~330 ms, and
# a polling macro spends nearly every tick ruling out templates that are simply
# not on screen. Matching a downscaled copy first is far cheaper and enough to
# reject, so full resolution is only paid when a match looks plausible.
#
# The reduction must be an EXACT, grid-aligned halving. That is not a detail — it
# decides whether the triage is safe at all. Measured on a 2840x1600 haystack with
# needles that are exact crops (so a full match scores 1.0000), worst-case score
# loss across needle content from 1px stripes to smooth gradients:
#
#     scale to 720px wide (ratio 0.2535, misaligned)   loss up to 0.3780
#     scale to 710px wide (ratio 0.2500, aligned)      loss 0.0000
#     one halving  (0.5x,  aligned)                    loss 0.0000
#     two halvings (0.25x, aligned)                    loss 0.0000
#     three halvings (0.125x)                          loss up to 0.2904
#
# At a misaligned ratio the needle and the haystack are resampled onto different
# pixel grids, so high-frequency content decorrelates instead of merely softening.
# Three halvings fail for the same reason: a 260x120 needle reaches 65x30, and 65
# is odd, so the next halving cannot stay aligned. Hence the loop below halves
# only while every dimension involved is still even.
_COARSE_MAX_HALVINGS = 2
_COARSE_MIN_NEEDLE = 24   # a needle smaller than this after halving says too little

# Worst loss measured for aligned halving was 0.0022 (a re-captured button with a
# brightness shift). 0.08 is many times that, and still far above where absent
# needles sit — they scored 0.508-0.594, so the veto floor of 0.82 rejects all of
# them. Both properties were required: safe AND actually useful.
_COARSE_SLACK = 0.08


def _coarse_halvings(haystack: np.ndarray, needle: np.ndarray) -> int:
    """How many times both images can be halved while staying grid-aligned."""
    hh, hw = haystack.shape[:2]
    nh, nw = needle.shape[:2]
    steps = 0
    while (steps < _COARSE_MAX_HALVINGS
           and hh % 2 == 0 and hw % 2 == 0
           and nh % 2 == 0 and nw % 2 == 0
           and min(nh // 2, nw // 2) >= _COARSE_MIN_NEEDLE):
        hh, hw, nh, nw = hh // 2, hw // 2, nh // 2, nw // 2
        steps += 1
    return steps


def _halve(img: np.ndarray, steps: int) -> np.ndarray:
    for _ in range(steps):
        img = cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2),
                         interpolation=cv2.INTER_AREA)
    return img


def _coarse_haystack(haystack: np.ndarray, steps: int) -> np.ndarray:
    """Halved copy of the haystack, shared by every template in a frame scope
    (all checks in one macro iteration shrink the very same screenshot).

    The cache holds the source array alongside the small one and confirms
    identity on lookup. Keying on id() alone is not safe: numpy reuses addresses
    aggressively — eight successive same-shape allocations were observed getting
    the identical id — so a freed frame's entry could otherwise be served for a
    completely different, later frame.
    """
    scope = _scope()
    cache = scope["coarse"]
    key = (id(haystack), haystack.shape, steps)
    cached = cache.get(key)
    if cached is not None and cached[0] is haystack:
        return cached[1]

    small = _halve(haystack, steps)
    if scope["depth"] > 0:
        cache[key] = (haystack, small)
    return small


def _coarse_allows(haystack: np.ndarray, needle: np.ndarray, threshold: float) -> bool:
    """Cheap veto: is a full-resolution match worth paying for at all?

    Conservative by design — it only answers "definitely not there", and skips
    itself entirely whenever the reduction could not stay grid-aligned.
    """
    steps = _coarse_halvings(haystack, needle)
    if steps == 0:
        return True

    small_hay = _coarse_haystack(haystack, steps)
    small_needle = _halve(needle, steps)
    if (small_needle.shape[0] > small_hay.shape[0]
            or small_needle.shape[1] > small_hay.shape[1]):
        return True

    result = cv2.matchTemplate(small_hay, small_needle, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    return ((max_val + 1.0) / 2.0) >= (threshold - _COARSE_SLACK)


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

    if not _coarse_allows(haystack, needle, threshold):
        return None

    result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    # TM_CCOEFF_NORMED returns scores in [-1, 1]; remap to [0, 1]
    score = (max_val + 1.0) / 2.0

    if score >= threshold:
        cx = max_loc[0] + tw // 2
        cy = max_loc[1] + th // 2
        return (cx, cy, score)

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

    # Same two guards as _cv_match, so find_all_and_click cannot report a template
    # that image_check calls absent on the very same frame, and a flat needle
    # cannot report matches everywhere.
    if float(needle.std()) < _MIN_NEEDLE_STD:
        return []

    if not _coarse_allows(haystack, needle, threshold):
        return []

    result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)

    # Remap threshold from [0,1] to [-1,1] for raw score comparison
    raw_threshold = threshold * 2.0 - 1.0

    locations = np.where(result >= raw_threshold)
    matches = []

    for pt_y, pt_x in zip(*locations):
        score = (result[pt_y, pt_x] + 1.0) / 2.0
        cx = pt_x + tw // 2
        cy = pt_y + th // 2
        matches.append((cx, cy, score))

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

    for cx, cy, score in matches:
        # Check overlap with already-kept detections
        overlaps = False
        for kx, ky, _ in keep:
            # Simple centre-distance check (faster than IoU for same-size templates)
            if abs(cx - kx) < tw * overlap_thresh and abs(cy - ky) < th * overlap_thresh:
                overlaps = True
                break
        if not overlaps:
            keep.append((cx, cy, score))

    return keep
