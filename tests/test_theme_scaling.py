"""Tests for making pixel padding follow the display scale.

A layout built from raw pixel numbers stays at 100% while Tk grows the text, because
font sizes are in points and pixels are not: at 250% a 10pt font renders 2.5x larger
and the padding around it does not. Text then overflows and panels clip mid-word.

The patch used to wrap the three geometry managers, which covers
`widget.pack(padx=10)` and misses `tk.Label(parent, padx=10)` — 41 constructor sites
and 2 `configure()` calls whose inner padding rendered at 1/SCALE of its intent.
Everything funnels through `Misc._options`, so that is where it belongs, and patching
both would scale a `pack` twice.
"""

import tkinter as tk

import pytest

from gui import theme as T

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def root(tk_root):
    """The session's one root.

    Creating and destroying a Tk root per test is flaky — it raised TclError on a
    different test each run, so a real failure looked like an intermittent skip. The
    same hazard bites across *files*, which is why the root now lives in conftest and
    nothing destroys it mid-run.
    """
    return tk_root


@pytest.fixture(autouse=True)
def restore_patch(monkeypatch):
    """The patch is global and permanent by design, so isolate it per test."""
    monkeypatch.setattr(T, "_patched", False)
    monkeypatch.setattr(T, "SCALE", 1.0)
    monkeypatch.setattr(tk.Misc, "_options", tk.Misc._options)
    yield


def _apply(scale):
    T.SCALE = scale
    T._scale_pixel_options()


def test_padding_on_a_widget_option_is_scaled(root):
    """The case the geometry-manager patch could not see."""
    _apply(2.5)
    label = tk.Label(root, text="x", padx=10, pady=4)
    assert int(label.cget("padx")) == 25
    assert int(label.cget("pady")) == 10


def test_padding_on_a_geometry_call_is_scaled(root):
    _apply(2.5)
    label = tk.Label(root, text="x")
    label.pack(padx=20, pady=6)
    assert int(label.pack_info()["padx"]) == 50
    assert int(label.pack_info()["pady"]) == 15


def test_padding_is_not_scaled_twice(root):
    """pack goes through _options as well, so keeping the old geometry patch
    alongside this one would double every pack padding."""
    _apply(2.0)
    label = tk.Label(root, text="x")
    label.pack(padx=10)
    assert int(label.pack_info()["padx"]) == 20, "20 means once, 40 means twice"


def test_configure_is_scaled(root):
    _apply(2.0)
    label = tk.Label(root, text="x")
    label.configure(padx=7)
    assert int(label.cget("padx")) == 14


def test_nothing_moves_at_100_percent(root):
    """init_scaling does not patch at all when SCALE is 1, but the patch must be a
    no-op even if it is applied."""
    _apply(1.0)
    label = tk.Label(root, text="x", padx=9)
    label.pack(padx=3)
    assert int(label.cget("padx")) == 9
    assert int(label.pack_info()["padx"]) == 3


def test_a_padding_string_keeps_its_own_unit(root):
    """Tk accepts "4m", "2p" and so on; those already resolve against the display's
    DPI, so scaling them would apply it twice."""
    _apply(2.0)
    label = tk.Label(root, text="x", padx="4m")
    assert str(label.cget("padx")) == "4m"   # cget hands back a Tcl pixel object


def test_a_two_sided_padding_is_scaled_on_both_sides(root):
    _apply(2.0)
    label = tk.Label(root, text="x")
    label.pack(padx=(3, 8))
    assert label.pack_info()["padx"] == (6, 16)


def test_querying_an_option_still_works(root):
    """cget and a string-form configure() call reach _options with a string rather
    than a mapping, which must not be treated as one."""
    _apply(2.0)
    label = tk.Label(root, text="x", padx=5)
    assert int(label.cget("padx")) == 10
    assert label.configure("padx")[-1] == 10


def test_patching_twice_does_not_stack(root):
    _apply(2.0)
    T._scale_pixel_options()             # the guard should make this a no-op
    label = tk.Label(root, text="x", padx=10)
    assert int(label.cget("padx")) == 20


def test_other_options_are_left_alone(root):
    """`width` means characters on a Label and pixels on a Frame, which is exactly
    why only padding is handled centrally."""
    _apply(2.0)
    label = tk.Label(root, text="x", width=12, wraplength=100)
    assert int(label.cget("width")) == 12
    assert int(label.cget("wraplength")) == 100
