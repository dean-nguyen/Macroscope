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
_SCALE_LADDER = (0.5, 0.6, 0.667, 0.75, 0.8, 0.9, 1.1, 1.2, 1.25, 1.333, 1.5, 1.667, 2.0)

# Walking the ladder costs one matchTemplate per rung, and a polling macro spends
# most of its ticks matching NOTHING — so sweeping on every miss would multiply
# the cost of the common case by ~14x. Discovery is therefore rationed: it runs
# at most once per interval per template, at most a few times, and stops for good
# once the window's scale is known.
_DISCOVERY_INTERVAL = 15.0   # seconds between sweeps for the same template
_DISCOVERY_ATTEMPTS = 3      # give up after this many fruitless sweeps

# (resolved template path, haystack w, haystack h) -> scale that matched
_scale_cache: dict = {}
# (haystack w, haystack h) -> scale that worked for ANY template at this window
# size. A pack is captured at one resolution, so the first template to resolve
# its scale answers for all the others.
_window_scale: dict = {}
_sweep_state: dict = {}      # key -> [attempts, last attempt time]


def clear_scale_cache() -> None:
    """Forget discovered template scales (used by tests and on window resize)."""
    _scale_cache.clear()
    _window_scale.clear()
    _sweep_state.clear()


def _may_sweep(key: tuple) -> bool:
    """Whether to spend a full ladder sweep on this template right now."""
    if key[1:] in _window_scale:
        return False                      # window scale already known
    attempts, last = _sweep_state.get(key, (0, 0.0))
    if attempts >= _DISCOVERY_ATTEMPTS:
        return False
    return (time.monotonic() - last) >= _DISCOVERY_INTERVAL


def _note_sweep(key: tuple) -> None:
    attempts, _ = _sweep_state.get(key, (0, 0.0))
    _sweep_state[key] = (attempts + 1, time.monotonic())


def _record_scale(key: tuple, scale: float) -> None:
    _scale_cache[key] = scale
    # Only a real discovery generalises to the whole window. A plain 1.0 match
    # must not populate this, or one resolution-independent element could block
    # scale discovery for every other template at that window size.
    if scale != 1.0:
        _window_scale.setdefault(key[1:], scale)


# ── per-tick frame sharing ────────────────────────────────────────────────────
#
# Every image action used to take its own screenshot, so one iteration of a
# macro with seven image checks grabbed seven frames of the same screen. Inside
# a frame scope the capture is taken once and reused, which is both far cheaper
# and more correct: all checks in one iteration now reason about the *same*
# screen instead of racing a UI that may change between them.

_frame_scope: dict = {"depth": 0, "frames": {}, "coarse": {}}


def begin_frame_scope() -> None:
    """Start reusing one capture for every match until the scope ends."""
    _frame_scope["depth"] += 1


def end_frame_scope() -> None:
    _frame_scope["depth"] = max(0, _frame_scope["depth"] - 1)
    if _frame_scope["depth"] == 0:
        _frame_scope["frames"].clear()
        _frame_scope["coarse"].clear()


def invalidate_frame_scope() -> None:
    """Drop the shared capture — for pollers that must see a fresh screen."""
    _frame_scope["frames"].clear()
    _frame_scope["coarse"].clear()


def _grab_haystack(hwnd: Optional[int],
                   region: Optional[Tuple[int, int, int, int]]) -> Optional[np.ndarray]:
    """Capture the search area, reusing the scope's frame when one is active."""
    key = ("hwnd", hwnd) if hwnd is not None else ("region", region)
    if _frame_scope["depth"] > 0 and key in _frame_scope["frames"]:
        return _frame_scope["frames"][key]

    if hwnd is not None:
        frame = _capture_hwnd_cv(hwnd)
    elif region is not None:
        x, y, w, h = region
        frame = _capture_screen_cv(bbox=(x, y, x + w, y + h))
    else:
        frame = _capture_screen_cv()

    if frame is not None and _frame_scope["depth"] > 0:
        _frame_scope["frames"][key] = frame
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
    order = []
    for candidate in (_scale_cache.get(key), _window_scale.get(key[1:]), 1.0):
        if candidate is not None and candidate not in order:
            order.append(candidate)
    return order


def _match_scaled(haystack, needle, threshold, key):
    """_cv_match, but tolerant of the game running at a different window size
    than the template was captured at.

    The cheap path — the template's known scale, the window's known scale, then
    the captured size — runs first, so a normal tick costs one or two
    matchTemplate calls. The full ladder only runs when no scale is known yet,
    and is rationed by _may_sweep so a macro that legitimately matches nothing
    does not pay for discovery on every tick.
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
# not on screen. Matching a downscaled copy first costs a fraction of that and is
# plenty to reject, so full resolution is only paid when a match looks plausible.
_COARSE_TARGET_W = 720    # downscale the haystack to about this width to triage
_COARSE_MIN_NEEDLE = 12   # below this the shrunken needle is too small to judge

# Measured on a live 2840x1600 Onmyoji window: shrinking to 720px wide costs a
# template that IS on screen about 0.03 of raw correlation (0.924 -> 0.893),
# while templates that are absent stay at 0.27-0.53. 0.05 in remapped score
# (=0.10 raw) is therefore several times the observed loss, yet still tight
# enough to reject every non-match — which is what makes the triage pay.
_COARSE_SLACK = 0.05


def _coarse_haystack(haystack: np.ndarray, factor: float) -> np.ndarray:
    """Downscaled copy of the haystack, shared by every template in a frame scope
    (all checks in one macro iteration shrink the very same screenshot)."""
    cache = _frame_scope["coarse"]
    key = (id(haystack), haystack.shape)
    small = cache.get(key)
    if small is None:
        small = cv2.resize(haystack,
                           (int(haystack.shape[1] * factor), int(haystack.shape[0] * factor)),
                           interpolation=cv2.INTER_AREA)
        if _frame_scope["depth"] > 0:
            cache[key] = small
    return small


def _coarse_allows(haystack: np.ndarray, needle: np.ndarray, threshold: float) -> bool:
    """Cheap veto: is a full-resolution match worth paying for at all?

    Conservative by design — it only answers "definitely not there", with slack
    so that shrink-induced score loss can never reject a real match.
    """
    sh, sw = haystack.shape[:2]
    if sw <= _COARSE_TARGET_W:
        return True

    f = _COARSE_TARGET_W / float(sw)
    nh, nw = max(1, int(needle.shape[0] * f)), max(1, int(needle.shape[1] * f))
    if min(nh, nw) < _COARSE_MIN_NEEDLE:
        return True

    small_hay = _coarse_haystack(haystack, f)
    if nh > small_hay.shape[0] or nw > small_hay.shape[1]:
        return True
    small_needle = cv2.resize(needle, (nw, nh), interpolation=cv2.INTER_AREA)

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
