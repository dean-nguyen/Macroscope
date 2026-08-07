"""Tests for cropping the selection out of one full-screen grab.

The crop and the screen it is judged against have to come from the same instant, or an
animating game makes a good crop look like it cannot find itself. That means cropping
from a single grab, which means trusting `SM_XVIRTUALSCREEN` to be the origin PIL would
have cropped a bbox with — and PIL does not expose it.

So the grab's size is checked against `SM_CXVIRTUALSCREEN` first. Measured on a
three-monitor desktop with origin `(-2560, 0)`: DPI-aware, cropping from the full grab
is pixel-identical to PIL's own bbox grab; without DPI awareness the metrics read
`3584x1152` against the same `6400x2400` grab and the crop is garbage (mean abs
difference 149.8). This is the check that turns the second case into a fallback instead
of a corrupted template.
"""

import numpy as np
import pytest
from PIL import Image

from gui.region_capture import RegionCapture

pytestmark = pytest.mark.unit


def _screen(w=6400, h=2400, seed=0):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (h, w, 3), dtype=np.uint8))


def _capture(monkeypatch, screen, origin=(-2560, 0), metrics=None):
    """A RegionCapture as if start() had run on a desktop of that shape."""
    cap = RegionCapture(None, None)
    cap._origin = origin
    cap._virtual_size = screen.size if metrics is None else metrics
    monkeypatch.setattr("gui.region_capture.ImageGrab.grab",
                        lambda **kw: screen)
    return cap


def test_a_crop_from_the_full_grab_matches_a_direct_bbox_grab(monkeypatch):
    screen = _screen()
    cap = _capture(monkeypatch, screen)
    cap.screen = cap._grab_screen()
    assert cap.screen is not None

    # A box on the second monitor, at a deliberately unaligned position.
    x1, y1 = -2560 + 301, 403
    mine = cap._crop_from_screen(x1, y1, x1 + 220, y1 + 140)
    theirs = screen.crop((301, 403, 301 + 220, 403 + 140))   # what PIL's bbox does
    assert np.array_equal(np.asarray(mine), np.asarray(theirs))


def test_metrics_that_disagree_with_the_grab_drop_the_screen(monkeypatch):
    """Without DPI awareness the metrics are the unscaled desktop while the grab is in
    physical pixels. The offset cannot be trusted either, so the fast path is off."""
    screen = _screen()
    cap = _capture(monkeypatch, screen, metrics=(3584, 1152))
    assert cap._grab_screen() is None


def test_unknown_metrics_disable_the_fast_path_rather_than_skip_the_check(monkeypatch):
    """Absence must not read as "no check needed" — that is how a corrupted template
    gets written by a caller that never went through start()."""
    screen = _screen()
    cap = _capture(monkeypatch, screen)
    cap._virtual_size = None
    assert cap._grab_screen() is None


def test_a_selection_running_off_the_desktop_is_refused(monkeypatch):
    screen = _screen(w=800, h=600)
    cap = _capture(monkeypatch, screen, origin=(0, 0))
    cap.screen = cap._grab_screen()
    assert cap._crop_from_screen(-10, 0, 100, 100) is None
    assert cap._crop_from_screen(700, 500, 900, 700) is None
    assert cap._crop_from_screen(10, 10, 110, 110) is not None


def test_no_screen_means_no_crop():
    cap = RegionCapture(None, None)
    assert cap.screen is None
    assert cap._crop_from_screen(0, 0, 10, 10) is None


def test_the_grab_falling_over_is_not_fatal(monkeypatch):
    cap = RegionCapture(None, None)
    cap._virtual_size = (800, 600)

    def boom(**_kw):
        raise OSError("no desktop")

    monkeypatch.setattr("gui.region_capture.ImageGrab.grab", boom)
    assert cap._grab_screen() is None


def test_the_callback_still_gets_a_crop_when_the_fast_path_is_off(monkeypatch):
    """The fallback: take the region on its own and let PIL apply the offset. The
    screen is dropped rather than passed on wrong, so the checks that need it are
    skipped instead of being fed a mismatched picture."""
    got = {}
    cap = RegionCapture(None, lambda img, x, y, w, h: got.update(
        img=img, x=x, y=y, w=w, h=h))
    cap._virtual_size = (3584, 1152)          # disagrees with the grab below
    region = _screen(w=220, h=140, seed=7)

    def grab(**kw):
        return _screen() if kw.get("bbox") is None else region

    monkeypatch.setattr("gui.region_capture.ImageGrab.grab", grab)
    cap._grab(301, 403, 521, 543, 220, 140)

    assert cap.screen is None, "a screen that cannot be trusted must not be passed on"
    assert got["img"] is region
    assert (got["x"], got["y"], got["w"], got["h"]) == (301, 403, 220, 140)
