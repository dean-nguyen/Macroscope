"""Pixel detection utilities using PIL/Pillow screenshots."""

import pyautogui
from PIL import ImageGrab
from typing import Tuple, Optional


def get_pixel_color(x: int, y: int) -> Tuple[int, int, int]:
    """Return the RGB color of a single pixel at (x, y)."""
    screenshot = ImageGrab.grab(bbox=(x, y, x + 1, y + 1), all_screens=True)
    return screenshot.getpixel((0, 0))[:3]


def color_matches(
    actual: Tuple[int, int, int],
    expected: Tuple[int, int, int],
    tolerance: int = 0,
) -> bool:
    """Return True if actual color is within tolerance of expected color."""
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected))


def wait_for_pixel(
    x: int,
    y: int,
    color: Tuple[int, int, int],
    tolerance: int = 0,
    timeout_ms: int = 5000,
    poll_ms: int = 50,
) -> bool:
    """
    Block until pixel at (x, y) matches color or timeout is reached.
    Returns True if match found, False on timeout.
    """
    import time

    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        if color_matches(get_pixel_color(x, y), tuple(color), tolerance):
            return True
        time.sleep(poll_ms / 1000.0)
    return False


def check_pixel(
    x: int,
    y: int,
    color: Tuple[int, int, int],
    tolerance: int = 0,
) -> bool:
    """Immediately check if pixel at (x, y) matches color."""
    return color_matches(get_pixel_color(x, y), tuple(color), tolerance)
