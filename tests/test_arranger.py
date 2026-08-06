"""Tests for the window-tiling arithmetic.

Reported symptom: "Arrange Windows doesn't work well on the second monitor."
Measured on a real two-monitor desktop, three separate causes put windows off the
display — two of them on the primary monitor as well.
"""

import pytest

from gui.arranger import tile_rects

pytestmark = pytest.mark.unit

# A primary monitor, and a secondary one to the LEFT of it. The negative origin is
# the real arrangement on the machine this was reported from, and it is why the
# placement maths must never assume a monitor starts at a non-negative coordinate.
PRIMARY = {"work": (0, 0, 3840, 2280)}
LEFT_SECONDARY = {"work": (-2560, 0, 2560, 1380)}
TALL_SECONDARY = {"work": (3840, 361, 1440, 2200)}
MONITORS = [PRIMARY, LEFT_SECONDARY, TALL_SECONDARY]


def _inside(monitor, rect):
    wx, wy, ww, wh = monitor["work"]
    x, y, w, h = rect
    return x >= wx and y >= wy and x + w <= wx + ww and y + h <= wy + wh


@pytest.mark.parametrize("monitor", MONITORS)
@pytest.mark.parametrize("cols,gap,count", [
    (1, 0, 1), (1, 0, 4), (2, 0, 5), (2, 8, 5), (3, 0, 7),
    (4, 12, 4), (2, 0, 9), (5, 4, 3),
])
def test_every_window_lands_on_the_chosen_monitor(monitor, cols, gap, count):
    """The bug in one sentence: rows advanced by the full work-area height, so
    everything past the first row started exactly at the bottom edge."""
    rects = tile_rects(monitor, cols, gap, count)
    assert len(rects) == count
    outside = [r for r in rects if not _inside(monitor, r)]
    assert not outside, f"{len(outside)} rect(s) off-monitor: {outside}"


@pytest.mark.parametrize("monitor", MONITORS)
def test_windows_are_resized_to_fit_not_left_oversized(monitor):
    """Keeping each window's original height moved it unchanged onto a monitor
    that may be far shorter — a 2400px window overflowed a 1380px work area by
    1020px. Tiling has to mean fitting."""
    _, _, _, wh = monitor["work"]
    for _, _, _, h in tile_rects(monitor, 2, 0, 4):
        assert h <= wh


def test_rows_split_the_height():
    rects = tile_rects(PRIMARY, 2, 0, 4)
    assert len(rects) == 4
    heights = {h for _, _, _, h in rects}
    assert heights == {2280 // 2}, heights
    tops = sorted({y for _, y, _, _ in rects})
    assert tops == [0, 1140]


def test_columns_never_exceed_the_window_count():
    """Asking for 5 columns with 2 windows must not produce slivers."""
    rects = tile_rects(PRIMARY, 5, 0, 2)
    assert len(rects) == 2
    assert all(w == 3840 // 2 for _, _, w, _ in rects)


def test_gaps_cannot_consume_the_axis():
    """An absurd gap must still yield usable, on-monitor rects."""
    rects = tile_rects({"work": (0, 0, 400, 300)}, 3, 500, 6)
    assert len(rects) == 6
    assert all(w >= 1 and h >= 1 for _, _, w, h in rects)


def test_no_windows_no_rects():
    assert tile_rects(PRIMARY, 2, 0, 0) == []


def test_negative_origin_is_preserved_not_normalised():
    """Coordinates are virtual-desktop absolute, which is what SetWindowPos takes."""
    rects = tile_rects(LEFT_SECONDARY, 2, 0, 2)
    assert min(x for x, _, _, _ in rects) == -2560
