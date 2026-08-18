"""Pinning a macro to a window in a way that survives restarting the game.

Running one macro per account means each has to name its own client, and a window
handle cannot do that job: the game gets a new one every launch, so a macro pinned to
`target_hwnd` has to be re-pointed by hand each time. Where the window *sits* survives
a restart, and it is also how someone thinks about two clients tiled side by side.
"""

import pytest

from engine import background_input as bi
from engine.macro_engine import MacroEngine, _position_index, _validate

pytestmark = pytest.mark.unit


LEFT = (111, "陰陽師Onmyoji", "Win32Window", (-2560, 0))
RIGHT = (222, "陰陽師Onmyoji", "Win32Window", (-1280, 0))
LOWER = (333, "陰陽師Onmyoji", "Win32Window", (-2560, 800))


def _fake_windows(monkeypatch, windows):
    titles = {h: t for h, t, _c, _r in windows}
    classes = {h: c for h, _t, c, _r in windows}
    rects = {h: r for h, _t, _c, r in windows}
    monkeypatch.setattr(bi.win32gui, "EnumWindows",
                        lambda cb, extra: [cb(h, extra) for h, _, _, _ in windows])
    monkeypatch.setattr(bi.win32gui, "IsWindowVisible", lambda h: True)
    monkeypatch.setattr(bi.win32gui, "GetWindowText", lambda h: titles[h])
    monkeypatch.setattr(bi.win32gui, "GetClassName", lambda h: classes[h])
    monkeypatch.setattr(bi.win32gui, "IsWindow", lambda h: True)
    monkeypatch.setattr(bi.win32gui, "GetWindowRect",
                        lambda h: rects[h] + (rects[h][0] + 100, rects[h][1] + 100))


def _macro(**fields):
    macro = {"name": "m", "actions": [], "target_window": "Onmyoji",
             "target_class": "Win32Window"}
    macro.update(fields)
    return macro


# ── ordering ──────────────────────────────────────────────────────────────────

def test_windows_are_ordered_left_to_right_then_top_to_bottom(monkeypatch):
    _fake_windows(monkeypatch, [RIGHT, LOWER, LEFT])
    ordered = bi.by_screen_position(bi.find_all_windows("Onmyoji"))
    assert [h for h, _ in ordered] == [LEFT[0], LOWER[0], RIGHT[0]]


def test_a_window_whose_rectangle_cannot_be_read_sorts_last(monkeypatch):
    _fake_windows(monkeypatch, [LEFT, RIGHT])

    def boom(h):
        if h == LEFT[0]:
            raise OSError("gone")
        return (-1280, 0, -1180, 100)

    monkeypatch.setattr(bi.win32gui, "GetWindowRect", boom)
    ordered = bi.by_screen_position(bi.find_all_windows("Onmyoji"))
    assert [h for h, _ in ordered] == [RIGHT[0], LEFT[0]], "it must not disappear"


# ── what the engine resolves ──────────────────────────────────────────────────

@pytest.mark.parametrize("position,expected", [(0, LEFT[0]), (1, RIGHT[0])])
def test_a_position_picks_that_window(monkeypatch, position, expected):
    _fake_windows(monkeypatch, [RIGHT, LEFT])       # deliberately not in order
    engine = MacroEngine(log_fn=lambda m: None)
    assert engine._resolve_hwnd(_macro(target_position=position)) == expected


def test_a_position_survives_the_handles_changing(monkeypatch):
    """The whole point. Restart the game and every hwnd is new; the left-hand window
    is still the left-hand window."""
    engine = MacroEngine(log_fn=lambda m: None)
    macro = _macro(target_position=1)

    _fake_windows(monkeypatch, [LEFT, RIGHT])
    assert engine._resolve_hwnd(macro) == RIGHT[0]

    restarted_left = (999, "陰陽師Onmyoji", "Win32Window", (-2560, 0))
    restarted_right = (888, "陰陽師Onmyoji", "Win32Window", (-1280, 0))
    _fake_windows(monkeypatch, [restarted_left, restarted_right])
    assert engine._resolve_hwnd(macro) == restarted_right[0]


def test_a_position_beats_a_stale_handle_that_is_still_valid(monkeypatch):
    """Handles get recycled. A macro that says which window it means by position
    should not be overruled by a number recorded in another session."""
    _fake_windows(monkeypatch, [LEFT, RIGHT])
    engine = MacroEngine(log_fn=lambda m: None)
    macro = _macro(target_position=1, target_hwnd=LEFT[0])
    assert engine._resolve_hwnd(macro) == RIGHT[0]


def test_a_missing_window_resolves_to_nothing_rather_than_the_wrong_one(monkeypatch):
    """Position 1 with only one client open must not quietly become position 0 —
    that is the other account."""
    _fake_windows(monkeypatch, [LEFT])
    logged = []
    engine = MacroEngine(log_fn=logged.append)
    assert engine._resolve_hwnd(_macro(target_position=1)) is None
    assert any("pinned to window position" in m for m in logged), logged


def test_without_a_position_nothing_changes(monkeypatch):
    _fake_windows(monkeypatch, [LEFT, RIGHT])
    engine = MacroEngine(log_fn=lambda m: None)
    assert engine._resolve_hwnd(_macro()) in (LEFT[0], RIGHT[0])
    assert engine._resolve_hwnd(_macro(target_hwnd=RIGHT[0])) == RIGHT[0]


# ── unusable values ───────────────────────────────────────────────────────────

def test_an_unusable_position_is_not_read_as_the_first_window():
    for bad in ("left", None, -1, True, 1.5):
        assert _position_index(bad) is None, bad
    assert _position_index(0) == 0
    assert _position_index(3) == 3


def test_a_wrong_type_is_rejected_at_load():
    for bad in ("left", -1, True, 1.5):
        with pytest.raises(ValueError) as exc:
            _validate({"name": "m", "actions": [], "target_position": bad})
        assert "target_position" in str(exc.value)

    _validate({"name": "m", "actions": [], "target_position": 0})
    _validate({"name": "m", "actions": [], "target_position": 7})
    _validate({"name": "m", "actions": [], "target_position": None})


# ── what the picker records ───────────────────────────────────────────────────

def test_picking_one_of_two_identical_windows_records_its_position(monkeypatch):
    from types import SimpleNamespace

    from gui.editor import MacroEditor

    _fake_windows(monkeypatch, [LEFT, RIGHT])
    form = SimpleNamespace(_target_var=SimpleNamespace(set=lambda v: None),
                           _bg_var=SimpleNamespace(set=lambda v: None),
                           _target_hwnd=None, _target_class=None,
                           _target_position=None)
    MacroEditor._on_window_picked(form, RIGHT[0], RIGHT[1])
    assert form._target_position == 1
    assert form._target_hwnd == RIGHT[0]


def test_picking_a_window_with_a_unique_title_records_no_position(monkeypatch):
    """There is nothing to disambiguate, and a position would only go stale if the
    user moved the window."""
    from types import SimpleNamespace

    from gui.editor import MacroEditor

    only = (444, "Notepad", "Notepad", (0, 0))
    _fake_windows(monkeypatch, [only])
    form = SimpleNamespace(_target_var=SimpleNamespace(set=lambda v: None),
                           _bg_var=SimpleNamespace(set=lambda v: None),
                           _target_hwnd=None, _target_class=None,
                           _target_position=7)
    MacroEditor._on_window_picked(form, only[0], only[1])
    assert form._target_position is None


# ── the pin is part of the targeting ──────────────────────────────────────────
#
# `matching_windows` is what lets the app offer "run on all of them", and it used to
# read `target_window` alone. So a macro pinned to one client still reported both, the
# app asked "run on all 2?" about a macro that had already been told which one, and
# answering *yes* calls `run(hwnd=…)` per window — which overrides the pin. With one
# macro per account that runs account A's macro on account B, the exact failure the pin
# exists to prevent.
#
# Measured on two live clients before the fix: `_resolve_hwnd` returned 461138 for
# position 0 and 133830 for position 1, while `matching_windows` returned 2 every time.

def _engine(monkeypatch, macro, windows):
    _fake_windows(monkeypatch, windows)
    engine = MacroEngine(log_fn=lambda *a, **k: None)
    with engine._lock:
        engine._macros["m"] = macro
    return engine


def test_an_unpinned_macro_is_ambiguous_and_reports_every_window(monkeypatch):
    """Asking is right here: without it the second instance never ran and nothing said
    so."""
    engine = _engine(monkeypatch, _macro(), [LEFT, RIGHT])
    assert len(engine.matching_windows("m")) == 2


@pytest.mark.parametrize("index, expected", [(0, LEFT[0]), (1, RIGHT[0])])
def test_a_position_pinned_macro_reports_only_that_window(monkeypatch, index, expected):
    engine = _engine(monkeypatch, _macro(target_position=index), [RIGHT, LEFT])
    assert [h for h, _ in engine.matching_windows("m")] == [expected]


def test_a_position_that_does_not_exist_reports_no_window(monkeypatch):
    """Never the whole list. A position is how a macro says "the left-hand client", so
    offering the others is offering the wrong account — and `_resolve_hwnd` returns
    None here for the same reason."""
    engine = _engine(monkeypatch, _macro(target_position=5), [LEFT, RIGHT])
    assert engine.matching_windows("m") == []


def test_a_live_handle_pin_reports_only_that_window(monkeypatch):
    engine = _engine(monkeypatch, _macro(target_hwnd=RIGHT[0]), [LEFT, RIGHT])
    assert [h for h, _ in engine.matching_windows("m")] == [RIGHT[0]]


def test_a_stale_handle_is_not_a_pin_and_the_choice_comes_back(monkeypatch):
    """`_resolve_hwnd` falls back to the title search when the saved handle is dead, so
    the macro really is ambiguous again — this is the one case where asking is right
    despite `target_hwnd` being set."""
    engine = _engine(monkeypatch, _macro(target_hwnd=999999), [LEFT, RIGHT])
    monkeypatch.setattr(bi.win32gui, "IsWindow", lambda h: h != 999999)
    assert len(engine.matching_windows("m")) == 2


def test_position_wins_over_a_handle_here_too(monkeypatch):
    """Same precedence as `_resolve_hwnd`, or the app would offer a window the run
    would not use."""
    macro = _macro(target_position=0, target_hwnd=RIGHT[0])
    engine = _engine(monkeypatch, macro, [LEFT, RIGHT])
    assert [h for h, _ in engine.matching_windows("m")] == [LEFT[0]]
    assert engine._resolve_hwnd(macro) == LEFT[0]


@pytest.mark.parametrize("pin", [None, 0, 1])
def test_it_agrees_with_resolve_hwnd_in_every_case(monkeypatch, pin):
    """The two must not drift: what the app offers has to be what the run will drive."""
    macro = _macro() if pin is None else _macro(target_position=pin)
    engine = _engine(monkeypatch, macro, [LEFT, RIGHT])
    windows = engine.matching_windows("m")
    resolved = engine._resolve_hwnd(macro)
    if len(windows) == 1:
        assert windows[0][0] == resolved
    else:
        assert resolved == windows[0][0], "the first offered is what an unpinned run takes"
