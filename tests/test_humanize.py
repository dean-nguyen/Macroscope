"""Tests for input jitter and the stall guard.

Both exist because a macro was previously a perfect metronome hitting one pixel
forever, and because the only thing that stopped it on an unexpected screen was a
per-game CAPTCHA template that a user may be unable to capture.

Two things here are load-bearing and were untested when first written: that
``_find_and_click`` actually passes a bound derived from the match (and does not let
``_click`` scatter the result a second time), and that a recognised template actually
reaches the stall guard. Both are driven through the real functions below, not through
hand-written flags, because mutating either line left the whole suite green.
"""

import threading
import time

import pytest

import engine.action_runner as ar
import engine.macro_engine as me
from engine import humanize
from engine.humanize import Humanize, from_macro
from engine.image_matcher import Match
from engine.macro_engine import DEFAULT_STALL_TIMEOUT_MS, MacroEngine

pytestmark = pytest.mark.unit


# ── settings ──────────────────────────────────────────────────────────────────

def test_jitter_is_on_by_default():
    """It is a safety feature, so it should not have to be asked for."""
    assert from_macro({}).enabled is True


def test_a_macro_can_turn_it_off():
    setting = from_macro({"humanize": False})
    assert setting.enabled is False
    assert setting.delay(1000) == 1000
    assert setting.point(50, 60) == (50, 60)


def test_a_macro_can_tune_it():
    setting = from_macro({"humanize": {"timing_pct": 0.5, "click_px": 9}})
    assert setting.timing_pct == 0.5
    assert setting.click_px == 9


def test_one_knob_can_be_zeroed_without_disabling_the_other():
    """click_px: 0 means "scatter timing but not clicks" — not "use the default"."""
    setting = from_macro({"humanize": {"click_px": 0}})
    assert setting.click_px == 0
    assert setting.timing_pct == humanize.DEFAULT_TIMING_PCT


def test_a_null_setting_falls_back_to_the_default():
    """An explicit null must not reach float() and kill the run."""
    assert from_macro({"humanize": None}).enabled is True
    assert from_macro({"humanize": {"timing_pct": None}}).timing_pct == \
        humanize.DEFAULT_TIMING_PCT


def test_anything_a_reader_would_write_as_off_is_off():
    """Only `false` is documented, but reading `0` as "on" would be a trap."""
    for value in (False, 0, ""):
        assert from_macro({"humanize": value}).enabled is False, value


# ── timing ────────────────────────────────────────────────────────────────────

def test_delays_are_scattered_but_stay_in_range():
    humanize.seed(1)
    setting = Humanize(timing_pct=0.15, click_px=0)
    values = {round(setting.delay(2500)) for _ in range(200)}
    assert len(values) > 50, "a metronome is the thing being removed"
    assert min(values) >= 2500 * 0.85 - 1
    assert max(values) <= 2500 * 1.15 + 1


def test_delay_is_proportional_not_a_fixed_offset():
    """A 200 ms settle and a 2500 ms poll must both stay sensible at one setting."""
    humanize.seed(2)
    setting = Humanize(timing_pct=0.2, click_px=0)
    assert all(160 <= setting.delay(200) <= 240 for _ in range(50))


def test_delay_never_goes_negative():
    humanize.seed(3)
    setting = Humanize(timing_pct=2.0, click_px=0)
    assert all(setting.delay(10) >= 0 for _ in range(100))


def test_zero_delay_stays_zero():
    assert Humanize(timing_pct=0.5).delay(0) == 0


def test_poll_intervals_and_keystroke_gaps_are_left_exact(monkeypatch):
    """Only wait.ms and loop_delay_ms are scattered. A poll period and a typing
    interval are rates the author chose, not pauses meant to look human."""
    seen = {}
    monkeypatch.setattr(ar.pd, "wait_for_pixel",
                        lambda **kw: seen.update(kw) or False)
    ctx = {"humanize": Humanize(timing_pct=0.9)}

    ar._pixel_wait({"x": 1, "y": 1, "color": [0, 0, 0],
                    "poll_ms": 50, "timeout_ms": 5000}, ctx)
    assert seen["poll_ms"] == 50 and seen["timeout_ms"] == 5000

    typed = {}
    monkeypatch.setattr(ar.bg, "post_type",
                        lambda h, t, i: typed.update(text=t, interval=i))
    ar._type({"text": "hi", "interval": 0.02},
             {"background": True, "hwnd": 1, "humanize": Humanize(timing_pct=0.9)})
    assert typed["interval"] == 0.02


# ── click position ────────────────────────────────────────────────────────────

def test_click_points_are_scattered_within_the_radius():
    humanize.seed(4)
    setting = Humanize(timing_pct=0, click_px=3)
    points = {setting.point(100, 200) for _ in range(200)}
    assert len(points) > 10
    assert all(abs(x - 100) <= 3 and abs(y - 200) <= 3 for x, y in points)


def test_a_caller_can_cap_the_scatter():
    humanize.seed(5)
    setting = Humanize(timing_pct=0, click_px=50)
    points = {setting.point(100, 100, max_px=2) for _ in range(200)}
    assert all(abs(x - 100) <= 2 and abs(y - 100) <= 2 for x, y in points)


def test_missing_coordinates_are_left_alone():
    assert Humanize(click_px=5).point(None, None) == (None, None)


def test_a_scattered_click_cannot_leave_the_client_area():
    """Measured before the clamp: with the default 3 px, a click at xp 0.999 left a
    1280x720 client area 39 times out of 60. A posted click outside the client area
    is silently dropped, and in foreground mode a corner is a pyautogui failsafe
    point, which aborts the macro on its next call."""
    humanize.seed(8)
    ctx = {"client_w": 1280, "client_h": 720, "humanize": Humanize(click_px=3)}
    moved = 0
    for x, y in ((0, 0), (1279, 719)):
        for _ in range(60):
            jx, jy = ar._scatter(x, y, ctx)
            assert 0 <= jx <= 1279 and 0 <= jy <= 719, (x, y, jx, jy)
            if (jx, jy) != (x, y):
                moved += 1
                # Where jitter did move the point, it is kept a pixel clear of the
                # edge, which is what keeps a corner failsafe point out of reach.
                assert 0 < jx < 1279 and 0 < jy < 719, (x, y, jx, jy)
    assert moved > 0, "nothing was scattered, so nothing was under test"


def test_an_exact_coordinate_is_never_moved_by_the_clamp():
    """The clamp exists to contain jitter. A coordinate the macro author wrote is
    not ours to move, even one on the very edge."""
    ctx = {"client_w": 1280, "client_h": 720, "humanize": Humanize(click_px=0)}
    assert ar._scatter(0, 0, ctx) == (0, 0)
    assert ar._scatter(1279, 719, ctx) == (1279, 719)


# ── wiring into the action runner ─────────────────────────────────────────────

def test_actions_are_exact_when_no_settings_are_in_ctx(monkeypatch):
    """A bare run_action from a test or a tool must behave exactly as written."""
    assert ar._humanize(None).enabled is False
    assert ar._humanize({}).enabled is False

    seen = []
    monkeypatch.setattr(ar.bg, "post_click",
                        lambda h, x, y, b="left": seen.append((x, y)))
    for _ in range(20):
        ar.run_action({"type": "click", "x": 500, "y": 500}, None,
                      {"background": True, "hwnd": 1})
    assert set(seen) == {(500, 500)}


def test_wait_uses_the_run_s_settings(monkeypatch):
    slept = []
    monkeypatch.setattr(ar.time, "sleep", lambda s: slept.append(s))

    ar._wait({"ms": 1000}, {"humanize": Humanize(timing_pct=0.0)})
    assert slept == [1.0]

    humanize.seed(6)
    slept.clear()
    ar._wait({"ms": 1000}, {"humanize": Humanize(timing_pct=0.2)})
    assert slept[0] != 1.0 and 0.8 <= slept[0] <= 1.2


def test_an_explicit_click_is_jittered(monkeypatch):
    seen = []
    monkeypatch.setattr(ar.bg, "post_click",
                        lambda h, x, y, b="left": seen.append((x, y)))
    humanize.seed(7)
    ctx = {"background": True, "hwnd": 1, "humanize": Humanize(click_px=4)}

    for _ in range(30):
        ar._click({"x": 500, "y": 500}, ctx)
    assert len(set(seen)) > 1, "a fixed-coordinate click is still a pattern"
    assert all(abs(x - 500) <= 4 and abs(y - 500) <= 4 for x, y in seen)


# ── find_and_click: the bound comes from the match, applied once ──────────────

def _stub_match(monkeypatch, match):
    monkeypatch.setattr(ar.im, "find_template", lambda *a, **k: match)
    monkeypatch.setattr(ar.im, "invalidate_frame_scope", lambda: None)
    clicks = []
    monkeypatch.setattr(ar.bg, "post_click",
                        lambda h, x, y, b="left": clicks.append((x, y)))
    return clicks


def test_find_and_click_stays_inside_the_element_it_matched(monkeypatch):
    """The radius must come from the size the template *matched* at. Matching is
    scale-aware, so on a half-size window a 40x40 template matches a 20x20 element
    and the file's own size would let the click land outside it."""
    humanize.seed(11)
    clicks = _stub_match(monkeypatch, Match(300, 200, 0.95, 20, 20))
    ctx = {"background": True, "hwnd": 1, "client_w": 1280, "client_h": 720,
           "humanize": Humanize(click_px=50)}   # far larger than the element

    for _ in range(60):
        ar._find_and_click({"type": "find_and_click", "template": "t.png"},
                           lambda acts: None, ctx)

    assert len(set(clicks)) > 1, "the centre pixel every time is the pattern"
    for x, y in clicks:
        assert abs(x - 300) <= 5 and abs(y - 200) <= 5, (x, y)


def test_find_and_click_is_not_jittered_a_second_time(monkeypatch):
    """_click must not scatter a point that was already scattered against a bound it
    does not know about."""
    humanize.seed(12)
    clicks = _stub_match(monkeypatch, Match(300, 200, 0.95, 4, 4))
    # jitter_bound of a 4x4 match is 1, so a doubly-jittered click would land
    # further than 1 px away.
    ctx = {"background": True, "hwnd": 1, "humanize": Humanize(click_px=8)}

    for _ in range(60):
        ar._find_and_click({"type": "find_and_click", "template": "t.png"},
                           lambda acts: None, ctx)

    for x, y in clicks:
        assert abs(x - 300) <= 1 and abs(y - 200) <= 1, (x, y)


def test_a_match_with_no_size_is_clicked_exactly(monkeypatch):
    """0 means "do not scatter", not "scatter freely" — so an older 3-tuple or a
    stub without a size cannot widen the jitter."""
    clicks = _stub_match(monkeypatch, (300, 200, 0.95))
    ctx = {"background": True, "hwnd": 1, "humanize": Humanize(click_px=50)}

    ar._find_and_click({"type": "find_and_click", "template": "t.png"},
                       lambda acts: None, ctx)
    assert clicks == [(300, 200)]


# ── what counts as recognising the screen ─────────────────────────────────────

def test_a_matched_template_reaches_the_stall_guard(monkeypatch):
    """The one line that connects the guard to reality. Removing it left all 120
    tests passing while every looping template macro would die after five minutes."""
    monkeypatch.setattr(ar.im, "find_template", lambda *a, **k: Match(1, 2, 0.9, 8, 8))
    ctx = {}
    ar._safe_find({"template": "t.png"}, None, 0.8, ctx)
    assert ctx.get("saw_expected") is True


def test_a_missed_template_does_not(monkeypatch):
    monkeypatch.setattr(ar.im, "find_template", lambda *a, **k: None)
    ctx = {}
    ar._safe_find({"template": "t.png"}, None, 0.8, ctx)
    assert not ctx.get("saw_expected")


def test_a_matched_pixel_counts_as_recognition(monkeypatch):
    """A macro driven by pixel checks is working just as much as one driven by
    templates. Judging it "blind" was a measured bug: a loop whose pixel_check
    matched its exact expected colour on every tick was stopped as stalled."""
    monkeypatch.setattr(ar.pd, "get_pixel_color", lambda x, y: (10, 20, 30))
    ctx = {}
    ar._pixel_check({"x": 1, "y": 1, "color": [10, 20, 30]}, lambda acts: None, ctx)
    assert ctx.get("saw_expected") is True

    other = {}
    ar._pixel_check({"x": 1, "y": 1, "color": [99, 99, 99]}, lambda acts: None, other)
    assert not other.get("saw_expected")


def test_clicking_is_recorded_as_sending_input(monkeypatch):
    monkeypatch.setattr(ar.bg, "post_click", lambda h, x, y, b="left": None)
    monkeypatch.setattr(ar.im, "invalidate_frame_scope", lambda: None)
    ctx = {"background": True, "hwnd": 1}
    ar._click({"x": 5, "y": 5}, ctx)
    assert ctx.get("sent_input") is True


# ── stall guard ───────────────────────────────────────────────────────────────

def _looping(**fields):
    macro = {
        "name": "m", "loop": True, "loop_delay_ms": 1,
        "actions": [{"type": "image_check", "template": "t.png"},
                    {"type": "click", "x": 10, "y": 10}],
    }
    macro.update(fields)
    return macro


def _run_guarded(engine, macro, timeout=5.0):
    """Run _execute on a worker and always tear it down.

    Without the finally, a regression leaves a daemon thread spinning _execute at
    ~1000 iterations/sec for the rest of the session.
    """
    stop = threading.Event()
    thread = threading.Thread(target=engine._execute, args=(macro, stop), daemon=True)
    thread.start()
    try:
        thread.join(timeout=timeout)
        return thread, stop
    finally:
        stop.set()


def test_stall_guard_stops_a_macro_clicking_at_a_screen_it_cannot_read(monkeypatch):
    """The generic replacement for a per-game CAPTCHA template: it fires for a
    verification prompt, a disconnect, maintenance *or* a changed UI, and needs no
    template at all."""
    monkeypatch.setattr(ar.im, "find_template", lambda *a, **k: None)
    monkeypatch.setattr(ar.bg, "post_click", lambda h, x, y, b="left": None)
    logged = []
    engine = MacroEngine(log_fn=logged.append)

    thread, stop = _run_guarded(engine, _looping(stall_timeout_ms=60))

    assert not thread.is_alive(), "the stall guard did not stop the loop"
    assert stop.is_set()
    assert any("stalled" in m for m in logged), logged


def test_a_watcher_that_clicks_nothing_is_left_alone(monkeypatch):
    """Recognising nothing is the normal state of a macro waiting for something to
    appear, and it is doing no harm — the dangerous case is clicking blind."""
    monkeypatch.setattr(ar.im, "find_template", lambda *a, **k: None)
    logged = []
    engine = MacroEngine(log_fn=logged.append)
    watcher = {
        "name": "w", "loop": True, "loop_delay_ms": 1, "stall_timeout_ms": 30,
        "actions": [{"type": "image_check", "template": "t.png",
                     "on_found": [{"type": "click", "x": 1, "y": 1}]}],
    }

    thread, stop = _run_guarded(engine, watcher, timeout=0.4)

    assert thread.is_alive(), "a macro that only watches must not be stopped"
    assert not any("stalled" in m for m in logged), logged


def test_a_macro_that_cannot_recognise_anything_is_not_guarded():
    """A purely coordinate-driven macro recognises nothing by construction. Judging
    it by that would stop something that is working perfectly."""
    logged = []
    engine = MacroEngine(log_fn=logged.append)
    blind = {
        "name": "b", "loop": True, "loop_delay_ms": 1, "stall_timeout_ms": 30,
        "actions": [{"type": "wait", "ms": 0}],
    }

    thread, stop = _run_guarded(engine, blind, timeout=0.4)

    assert thread.is_alive()
    assert not any("stalled" in m for m in logged), logged


def test_recognising_something_resets_the_stall_clock(monkeypatch):
    """A long battle or loading screen must not be mistaken for a stall."""
    logged = []
    engine = MacroEngine(log_fn=logged.append)
    ticks = {"n": 0}
    deadline = time.monotonic() + 5.0

    def fake_run_action(action, run_actions_fn, ctx):
        ticks["n"] += 1
        ctx["saw_expected"] = True
        ctx["sent_input"] = True
        # Bounded two ways: by the count under test, and by a wall clock, so a
        # regression that stops invoking this is a failure rather than a hang.
        if ticks["n"] >= 6 or time.monotonic() > deadline:
            stop.set()

    monkeypatch.setattr(me, "run_action", fake_run_action)
    stop = threading.Event()
    engine._execute(_looping(stall_timeout_ms=30), stop)

    assert ticks["n"] >= 6
    assert not any("stalled" in m for m in logged), logged


def test_the_stall_guard_can_be_disabled(monkeypatch):
    monkeypatch.setattr(ar.im, "find_template", lambda *a, **k: None)
    monkeypatch.setattr(ar.bg, "post_click", lambda h, x, y, b="left": None)
    logged = []
    engine = MacroEngine(log_fn=logged.append)

    thread, stop = _run_guarded(engine, _looping(stall_timeout_ms=0), timeout=0.4)

    assert thread.is_alive(), "stall_timeout_ms: 0 must mean never stop on its own"
    assert not any("stalled" in m for m in logged)


def test_the_default_timeout_is_long_enough_not_to_fire_by_accident():
    """It must be far longer than any battle or loading screen; five minutes of
    clicking without recognising anything means the macro is not working."""
    assert DEFAULT_STALL_TIMEOUT_MS >= 3 * 60 * 1000


def test_an_unusable_timeout_does_not_kill_a_running_macro():
    """The value is only read on an iteration that recognised nothing, so a string
    used to surface as a TypeError minutes into a run that had been working."""
    assert me._stall_timeout_of({"stall_timeout_ms": "soon"}) == \
        DEFAULT_STALL_TIMEOUT_MS
    assert me._stall_timeout_of({"stall_timeout_ms": None}) == DEFAULT_STALL_TIMEOUT_MS
    assert me._stall_timeout_of({"stall_timeout_ms": [60]}) == DEFAULT_STALL_TIMEOUT_MS
    assert me._stall_timeout_of({"stall_timeout_ms": -5}) == 0
    assert me._stall_timeout_of({"stall_timeout_ms": 0}) == 0
    assert me._stall_timeout_of({"stall_timeout_ms": "600000"}) == 600000


def test_a_wrong_type_is_rejected_at_load_not_mid_run():
    for bad in ({"stall_timeout_ms": "600000"}, {"stall_timeout_ms": -1},
                {"humanize": "off"}, {"humanize": {"click_px": "three"}}):
        macro = {"name": "m", "actions": [], **bad}
        with pytest.raises(ValueError):
            me._validate(macro)

    # And the usable forms still load.
    for good in ({"stall_timeout_ms": 0}, {"stall_timeout_ms": 60000},
                 {"humanize": False}, {"humanize": {"timing_pct": 0.2}}):
        me._validate({"name": "m", "actions": [], **good})


def test_recognition_is_found_inside_nested_branches():
    assert me._can_recognise([{"type": "click", "x": 1, "y": 1}]) is False
    assert me._can_recognise([
        {"type": "wait", "ms": 1,
         "on_no_match": [{"type": "image_check", "template": "t.png"}]},
    ]) is True
