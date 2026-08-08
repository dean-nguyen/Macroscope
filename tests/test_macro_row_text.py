"""Tests for what a macro row reads.

Measured on a live window at 250% display scaling: the name label wanted 429-541 px
and the grid handed it 267, so all four rows of a two-account setup rendered as
"Onmyoji - Realm F" — the same seventeen characters, four times, with no ellipsis to
say anything was missing. Three things had to be true for a row to identify itself:
the shared folder prefix had to go, what survives truncation had to be the tail, and
the window a macro drives had to appear at all.
"""

import tkinter as tk

import pytest

from gui.app import _fit_text, _short_name, _window_label

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def measure():
    """A real font measurer — the widths are the whole point of _fit_text."""
    from tkinter import font as tkfont
    try:
        window = tk.Tk()
    except tk.TclError:                      # pragma: no cover - headless CI
        pytest.skip("no display")
    window.withdraw()
    yield tkfont.Font(font=("Segoe UI", 10))
    window.destroy()


# ── the folder prefix ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, folder, expected", [
    ("Onmyoji - Realm Raid (Guild)", "Onmyoji", "Realm Raid (Guild)"),
    ("Onmyoji: Realm Raid",          "Onmyoji", "Realm Raid"),
    ("Onmyoji — Realm Raid",         "Onmyoji", "Realm Raid"),
    ("Onmyoji / Realm Raid",         "Onmyoji", "Realm Raid"),
    ("onmyoji - Realm Raid",         "Onmyoji", "Realm Raid"),   # case-insensitive
])
def test_the_folder_name_is_not_repeated_in_the_row(name, folder, expected):
    assert _short_name(name, folder) == expected


@pytest.mark.parametrize("name, folder", [
    ("Onmyojitsu Trainer", "Onmyoji"),    # prefix without a separator: a real word
    ("Realm Raid",         "Onmyoji"),    # nothing shared
    ("Onmyoji",            "Onmyoji"),    # stripping it would leave nothing
    ("Onmyoji - ",         "Onmyoji"),    # ditto, once whitespace is dropped
    ("Onmyoji - Raid",     ""),           # loose macro: the prefix is all it has
])
def test_a_name_is_only_shortened_when_the_folder_really_is_a_prefix(name, folder):
    assert _short_name(name, folder) == name


# ── the ellipsis ──────────────────────────────────────────────────────────────

def test_text_that_fits_is_left_alone(measure):
    text = "Realm Raid (Guild)"
    assert _fit_text(measure, text, measure.measure(text) + 10) == text


def test_the_ellipsis_keeps_what_tells_the_rows_apart(measure):
    """The regression this file exists for.

    Truncating from the right gives four identical rows, because everything that
    differs between the duplicates of one pack macro is at the end.
    """
    names = ["Realm Raid (Guild)", "Realm Raid (Guild) (2)",
             "Realm Raid (Individual)", "Realm Raid (Individual) (2)"]
    width = measure.measure("Realm Raid (Gui")     # narrower than any of them

    shown = [_fit_text(measure, n, width) for n in names]

    assert all(s != n for s, n in zip(shown, names)), "expected these to be truncated"
    assert len(set(shown)) == len(names), f"rows are indistinguishable: {shown}"
    assert all(s.endswith((")", "(2)")) for s in shown), shown


def test_the_result_actually_fits(measure):
    for width in (40, 80, 120, 200, 400):
        shown = _fit_text(measure, "Realm Raid (Individual) (2)", width)
        assert measure.measure(shown) <= width or shown == "…", (width, shown)


def test_tail_share_zero_truncates_from_the_right(measure):
    """What the subtitle wants: the description reads left to right."""
    text = "Raid the Individual 3x3 target list"
    shown = _fit_text(measure, text, measure.measure("Raid the Ind"), tail_share=0.0)
    assert shown.startswith("Raid the")
    assert shown.endswith("…")


def test_a_zero_width_label_is_not_truncated_to_nothing(measure):
    """Tk reports width 1 before a widget is mapped; that is not a real measurement."""
    assert _fit_text(measure, "Realm Raid", 0) == "Realm Raid"


# ── which window ──────────────────────────────────────────────────────────────

def test_a_pinned_position_is_what_the_row_shows():
    assert _window_label({"target_window": "Onmyoji", "target_position": 2}) == "window 2"


def test_a_pinned_handle_is_shown_when_there_is_no_position():
    assert _window_label({"target_window": "Onmyoji", "target_hwnd": 1641012}) \
        == "pinned #1641012"


def test_position_wins_over_a_handle():
    """Same precedence as _resolve_hwnd, so the row cannot claim the wrong window."""
    label = _window_label({"target_position": 1, "target_hwnd": 1641012})
    assert label == "window 1"


def test_an_unpinned_macro_still_names_its_target():
    assert _window_label({"target_window": "Onmyoji"}) == "BG: Onmyoji"
    assert _window_label({}) == "Background"


def test_two_duplicates_of_one_macro_do_not_read_the_same():
    """The setup the whole feature is for: same pack macro, one per game client."""
    first  = {"target_window": "Onmyoji", "target_position": 1}
    second = {"target_window": "Onmyoji", "target_position": 2}
    assert _window_label(first) != _window_label(second)
