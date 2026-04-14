"""
Rectangle / card detector using OpenCV contour analysis.

Finds rectangular regions in a screenshot — useful for detecting UI cards,
buttons, inventory slots, etc. in games and applications.

Coordinate spaces follow the same convention as image_matcher:
  hwnd given  → haystack is the client area → returned coords are client-space
  hwnd=None   → haystack is the whole screen → returned coords are screen-space
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import cv2
import numpy as np


# ── public API ────────────────────────────────────────────────────────────────

def find_rectangles(
    hwnd: Optional[int] = None,
    min_w: int = 40,
    min_h: int = 40,
    max_w: int = 800,
    max_h: int = 800,
    aspect_min: float = 0.3,
    aspect_max: float = 3.5,
    merge_distance: int = 10,
) -> List[Tuple[int, int, int, int]]:
    """
    Detect rectangular regions in a screenshot.

    Parameters
    ----------
    hwnd : optional window handle (client-area capture via image_matcher)
    min_w, min_h : minimum rectangle dimensions to accept
    max_w, max_h : maximum rectangle dimensions to accept
    aspect_min, aspect_max : allowed width/height ratio range
    merge_distance : rectangles within this pixel distance are merged

    Returns
    -------
    List of (cx, cy, w, h) sorted top-to-bottom then left-to-right.
    cx, cy are the centre of each detected rectangle.
    """
    img = _capture(hwnd)
    if img is None:
        return []

    rects = _detect_rects(
        img,
        min_w=min_w, min_h=min_h,
        max_w=max_w, max_h=max_h,
        aspect_min=aspect_min, aspect_max=aspect_max,
    )

    if merge_distance > 0:
        rects = _merge_nearby(rects, merge_distance)

    # Sort: top-to-bottom (by cy), then left-to-right (by cx)
    rects.sort(key=lambda r: (r[1], r[0]))
    return rects


# ── capture ──────────────────────────────────────────────────────────────────

def _capture(hwnd: Optional[int]) -> Optional[np.ndarray]:
    """Capture image as BGR uint8 numpy array (OpenCV convention)."""
    from engine.image_matcher import _capture_hwnd_cv, _capture_screen_cv
    if hwnd is not None:
        return _capture_hwnd_cv(hwnd)
    return _capture_screen_cv()


# ── detection ────────────────────────────────────────────────────────────────

def _detect_rects(
    img: np.ndarray,
    min_w: int,
    min_h: int,
    max_w: int,
    max_h: int,
    aspect_min: float,
    aspect_max: float,
) -> List[Tuple[int, int, int, int]]:
    """
    Detect rectangles using edge detection + contour analysis.

    Returns list of (cx, cy, w, h).
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Adaptive threshold to handle varying backgrounds
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 30, 120)

    # Dilate edges to close small gaps in rectangle borders
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    results = []
    for cnt in contours:
        # Approximate the contour to a polygon
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)

        # Accept 4-sided polygons (rectangles) or use bounding rect for near-rects
        if len(approx) < 4 or len(approx) > 6:
            continue

        x, y, w, h = cv2.boundingRect(approx)

        # Size filter
        if w < min_w or h < min_h or w > max_w or h > max_h:
            continue

        # Aspect ratio filter
        aspect = w / max(h, 1)
        if aspect < aspect_min or aspect > aspect_max:
            continue

        # Rectangularity check: contour area vs bounding rect area
        area = cv2.contourArea(cnt)
        rect_area = w * h
        if rect_area > 0 and area / rect_area < 0.5:
            continue  # too irregular

        cx = x + w // 2
        cy = y + h // 2
        results.append((cx, cy, w, h))

    return results


def _merge_nearby(
    rects: List[Tuple[int, int, int, int]],
    distance: int,
) -> List[Tuple[int, int, int, int]]:
    """Merge rectangles whose centres are within `distance` pixels."""
    if not rects:
        return rects
    merged = []
    used = [False] * len(rects)
    for i, (cx1, cy1, w1, h1) in enumerate(rects):
        if used[i]:
            continue
        group_cx, group_cy, group_w, group_h, count = cx1, cy1, w1, h1, 1
        for j in range(i + 1, len(rects)):
            if used[j]:
                continue
            cx2, cy2, w2, h2 = rects[j]
            if abs(cx1 - cx2) < distance and abs(cy1 - cy2) < distance:
                group_cx += cx2
                group_cy += cy2
                group_w = max(group_w, w2)
                group_h = max(group_h, h2)
                count += 1
                used[j] = True
        merged.append((group_cx // count, group_cy // count, group_w, group_h))
        used[i] = True
    return merged
