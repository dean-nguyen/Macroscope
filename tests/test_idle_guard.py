"""Tests for stopping a macro that is doing nothing at all.

The stall guard watches for a macro *clicking* at a screen it cannot recognise. That
leaves a hole its own design creates: both raid macros gate every click behind an "am
I on the right screen" check, so a tick that fails it sends no input — and a tick that
sends no input can never meet the stall guard's condition. Measured as the outcome of
an unrecognised popup covering the target list: the macro loops forever, clicks
nothing, says nothing.

The two guards answer different questions and both are timeouts, because nothing here
can tell a stuck macro from a patient one. A watcher legitimately waiting hours sets
idle_timeout_ms: 0.
"""

import threading
import time

import pytest

import engine.action_runner as ar
import engine.macro_engine as me
from engine.macro_engine import (DEFAULT_IDLE_TIMEOUT_MS, DEFAULT_STALL_TIMEOUT_MS,
                                 MacroEngine)

pytestmark = pytest.mark.unit


def _looping(**fields):
    macro = {
        "name": "m", "loop": True, "loop_delay_ms": 1,
        "actions": [{"type": "image_check", "template": "t.png"},
                    {"type": "click", "x": 10, "y": 10}],
    }
    macro.update(fields)
    return macro


def _gated(**fields):
    """The shape of both raid macros: every click sits behind a screen check, so a
    tick that fails the check sends nothing at all."""
    macro = {
        "name": "m", "loop": True, "loop_delay_ms": 1,
        "actions": [{"type": "image_check", "template": "list.png",
                     "on_found": [{"type": "click", "x": 1, "y": 1}]}],
    }
    macro.update(fields)
    return macro


def _run(engine, macro, timeout=5.0):
    stop = threading.Event()
    thread = threading.Thread(target=engine._execute, args=(macro, stop), daemon=True)
    thread.start()
    try:
        thread.join(timeout=timeout)
        return thread.is_alive()
    finally:
        stop.set()
        thread.join(timeout=5.0)


# ── the gap this closes ───────────────────────────────────────────────────────

def test_a_macro_doing_nothing_at_all_is_stopped(monkeypatch):
    """The shape of both raid macros with an unrecognised popup over the list: the
    outer check misses, so nothing inside it runs, so no input is ever sent."""
    monkeypatch.setattr(ar.im, "find_template", lambda *a, **k: None)
    logged = []
    engine = MacroEngine(log_fn=logged.append)

    alive = _run(engine, _gated(idle_timeout_ms=60))

    assert not alive, "a macro that does nothing must not loop forever"
    assert any("[idle]" in m for m in logged), logged
    assert engine.stopped_reason("m")


def test_the_reason_is_kept_so_the_app_can_say_it(monkeypatch):
    """A guard that fires when nobody is watching has to leave something behind that
    is not only a line in a collapsible log."""
    monkeypatch.setattr(ar.im, "find_template", lambda *a, **k: None)
    engine = MacroEngine(log_fn=lambda m: None)
    _run(engine, _gated(idle_timeout_ms=60, stall_timeout_ms=0))

    reason = engine.stopped_reason("m")
    assert reason and "idle_timeout_ms" in reason, reason
    assert engine.stopped_reason("never-ran") is None


def test_a_macro_that_acts_is_not_idle(monkeypatch):
    """Sending input is doing something, even when nothing is recognised — that case
    belongs to the stall guard, on its own much shorter clock."""
    monkeypatch.setattr(ar.im, "find_template", lambda *a, **k: None)
    monkeypatch.setattr(ar.bg, "post_click", lambda h, x, y, b="left": None)
    engine = MacroEngine(log_fn=lambda m: None)

    alive = _run(engine, _looping(idle_timeout_ms=60, stall_timeout_ms=0),
                 timeout=0.5)
    assert alive, "a macro sending input is not idle"


def test_a_macro_that_recognises_something_is_not_idle(monkeypatch):
    """A watcher that sees its element and waits is working, not stuck."""
    monkeypatch.setattr(ar.im, "find_template",
                        lambda *a, **k: ar.im.Match(1, 2, 0.9, 8, 8))
    engine = MacroEngine(log_fn=lambda m: None)

    watcher = {
        "name": "m", "loop": True, "loop_delay_ms": 1, "idle_timeout_ms": 60,
        "actions": [{"type": "image_check", "template": "t.png"}],
    }
    assert _run(engine, watcher, timeout=0.5), "recognising is doing something"


def test_the_idle_guard_can_be_disabled(monkeypatch):
    """A watcher waiting hours for a daily reset is a real macro, and nothing here
    can tell it apart from a stuck one."""
    monkeypatch.setattr(ar.im, "find_template", lambda *a, **k: None)
    logged = []
    engine = MacroEngine(log_fn=logged.append)

    quiet = {
        "name": "m", "loop": True, "loop_delay_ms": 1, "idle_timeout_ms": 0,
        "actions": [{"type": "image_check", "template": "t.png"}],
    }
    assert _run(engine, quiet, timeout=0.4)
    assert not any("[idle]" in m for m in logged)


# ── the two guards stay distinct ──────────────────────────────────────────────

def test_the_stall_guard_still_fires_on_its_own_clock(monkeypatch):
    monkeypatch.setattr(ar.im, "find_template", lambda *a, **k: None)
    monkeypatch.setattr(ar.bg, "post_click", lambda h, x, y, b="left": None)
    logged = []
    engine = MacroEngine(log_fn=logged.append)

    alive = _run(engine, _looping(stall_timeout_ms=60, idle_timeout_ms=0))
    assert not alive
    assert any("[stalled]" in m for m in logged), logged


def test_idle_is_the_longer_clock_of_the_two():
    """Doing nothing is also what a patient macro does, so it gets far more rope
    than one that is clicking at a screen it cannot read."""
    assert DEFAULT_IDLE_TIMEOUT_MS > DEFAULT_STALL_TIMEOUT_MS


def test_a_guard_stop_does_not_cancel_a_folder_run(monkeypatch):
    """One macro losing its screen is no reason to abandon the rest of the dailies —
    and both guards set the same stop flag the user's Stop button does."""
    monkeypatch.setattr(ar.im, "find_template", lambda *a, **k: None)
    engine = MacroEngine(log_fn=lambda m: None)
    _run(engine, _gated(idle_timeout_ms=60, stall_timeout_ms=0))
    assert "m" in engine._stalled


# ── unusable values must not kill a running macro ─────────────────────────────

def test_an_unusable_idle_timeout_falls_back(monkeypatch):
    assert me._idle_timeout_of({"idle_timeout_ms": "soon"}) == DEFAULT_IDLE_TIMEOUT_MS
    assert me._idle_timeout_of({"idle_timeout_ms": None}) == DEFAULT_IDLE_TIMEOUT_MS
    assert me._idle_timeout_of({"idle_timeout_ms": -5}) == 0
    assert me._idle_timeout_of({"idle_timeout_ms": 900}) == 900


def test_a_wrong_type_is_rejected_at_load():
    for bad in ({"idle_timeout_ms": "soon"}, {"idle_timeout_ms": -1},
                {"idle_timeout_ms": True}):
        with pytest.raises(ValueError) as exc:
            me._validate({"name": "m", "actions": [], **bad})
        assert "idle_timeout_ms" in str(exc.value)

    me._validate({"name": "m", "actions": [], "idle_timeout_ms": 0})
    me._validate({"name": "m", "actions": [], "idle_timeout_ms": 900000})
