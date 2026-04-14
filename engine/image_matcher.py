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
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageGrab

log = logging.getLogger(__name__)


def _app_root() -> Path:
    """Return the application root — works both from source and PyInstaller bundle."""
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


TEMPLATES_DIR = _app_root() / "templates"


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
    path = Path(template_path)
    if not path.is_absolute():
        path = _app_root() / path
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")

    needle = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if needle is None:
        raise FileNotFoundError(f"Could not read template image: {path}")

    if hwnd is not None:
        haystack = _capture_hwnd_cv(hwnd)
    elif region is not None:
        x, y, w, h = region
        haystack = _capture_screen_cv(bbox=(x, y, x + w, y + h))
    else:
        haystack = _capture_screen_cv()

    if haystack is None:
        return None

    # Lower threshold when WGC captured the frame (different color pipeline).
    effective = threshold - _WGC_THRESHOLD_OFFSET if _is_wgc_active(hwnd) else threshold
    result = _cv_match(haystack, needle, effective)
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
    path = Path(template_path)
    if not path.is_absolute():
        path = _app_root() / path
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")

    needle = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if needle is None:
        raise FileNotFoundError(f"Could not read template image: {path}")

    if hwnd is not None:
        haystack = _capture_hwnd_cv(hwnd)
    elif region is not None:
        x, y, w, h = region
        haystack = _capture_screen_cv(bbox=(x, y, x + w, y + h))
    else:
        haystack = _capture_screen_cv()

    if haystack is None:
        return []

    effective = threshold - _WGC_THRESHOLD_OFFSET if _is_wgc_active(hwnd) else threshold
    results = _cv_match_all(haystack, needle, effective)

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
