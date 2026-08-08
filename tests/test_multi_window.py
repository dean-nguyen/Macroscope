"""One macro, several windows.

Two instances of a game side by side is the ordinary way people run this, and until
now the engine could not express it: everything about a run was keyed by macro name,
so a second `run()` was refused and the second instance simply never started —
without anything saying so. The alternative was a copy of the macro file per window,
which is the copy-per-thing this pack spent a day getting rid of.
"""

import threading
import time

import pytest

import engine.action_runner as ar
from engine import background_input as bi
from engine.macro_engine import MacroEngine

pytestmark = pytest.mark.unit


GAME_A = (111, "陰陽師Onmyoji", "Win32Window")
GAME_B = (222, "陰陽師Onmyoji", "Win32Window")


def _fake_windows(monkeypatch, windows):
    titles = {h: t for h, t, _ in windows}
    classes = {h: c for h, _, c in windows}
    monkeypatch.setattr(bi.win32gui, "EnumWindows",
                        lambda cb, extra: [cb(h, extra) for h, _, _ in windows])
    monkeypatch.setattr(bi.win32gui, "IsWindowVisible", lambda h: True)
    monkeypatch.setattr(bi.win32gui, "GetWindowText", lambda h: titles[h])
    monkeypatch.setattr(bi.win32gui, "GetClassName", lambda h: classes[h])
    monkeypatch.setattr(bi.win32gui, "IsWindow", lambda h: True)


def _engine(monkeypatch, actions=None):
    """An engine whose macro loops harmlessly and never touches a real window."""
    monkeypatch.setattr(ar.im, "find_template", lambda *a, **k: None)
    engine = MacroEngine(log_fn=lambda m: None)
    engine._macros["demo"] = {
        "name": "demo", "loop": True, "loop_delay_ms": 20,
        "background": True, "target_window": "Onmyoji",
        "target_class": "Win32Window", "idle_timeout_ms": 0,
        "actions": actions or [{"type": "wait", "ms": 5}],
    }
    return engine


def _settle(engine, name="demo", alive=True, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if engine.is_running(name) is alive:
            return True
        time.sleep(0.02)
    return engine.is_running(name) is alive


# ── the gap ───────────────────────────────────────────────────────────────────

def test_one_macro_runs_on_two_windows_at_once(monkeypatch):
    _fake_windows(monkeypatch, [GAME_A, GAME_B])
    engine = _engine(monkeypatch)
    try:
        started = engine.run_on_windows("demo", [GAME_A[0], GAME_B[0]])
        assert started == [GAME_A[0], GAME_B[0]]
        assert _settle(engine)
        assert sorted(engine.running_windows("demo")) == [GAME_A[0], GAME_B[0]]
    finally:
        engine.stop_all()


def test_the_same_window_is_not_started_twice(monkeypatch):
    """One run per window, not one run per press."""
    _fake_windows(monkeypatch, [GAME_A])
    engine = _engine(monkeypatch)
    try:
        assert engine.run("demo", hwnd=GAME_A[0]) is True
        assert _settle(engine)
        assert engine.run("demo", hwnd=GAME_A[0]) is False
        assert engine.running_windows("demo") == [GAME_A[0]]
    finally:
        engine.stop_all()


def test_a_window_pinned_run_and_an_unpinned_one_are_separate(monkeypatch):
    _fake_windows(monkeypatch, [GAME_A, GAME_B])
    engine = _engine(monkeypatch)
    try:
        assert engine.run("demo") is True
        assert engine.run("demo", hwnd=GAME_B[0]) is True
        assert _settle(engine)
        assert engine.running_windows("demo") == [GAME_B[0], None]
    finally:
        engine.stop_all()


def test_stop_stops_every_window(monkeypatch):
    """The button says Stop, so it has to mean all of them."""
    _fake_windows(monkeypatch, [GAME_A, GAME_B])
    engine = _engine(monkeypatch)
    engine.run_on_windows("demo", [GAME_A[0], GAME_B[0]])
    assert _settle(engine)

    engine.stop("demo")
    assert _settle(engine, alive=False)
    assert engine.running_windows("demo") == []


def test_stop_all_stops_every_window_too(monkeypatch):
    _fake_windows(monkeypatch, [GAME_A, GAME_B])
    engine = _engine(monkeypatch)
    engine.run_on_windows("demo", [GAME_A[0], GAME_B[0]])
    assert _settle(engine)

    engine.stop_all()
    assert _settle(engine, alive=False)


def test_each_run_drives_its_own_window(monkeypatch):
    """The whole point: the pinned hwnd must reach the actions, or both runs would
    drive whichever window the title search happened to rank first."""
    _fake_windows(monkeypatch, [GAME_A, GAME_B])
    seen = []
    monkeypatch.setattr(ar.bg, "post_click",
                        lambda h, x, y, b="left": seen.append(h))
    monkeypatch.setattr(ar.im, "invalidate_frame_scope", lambda: None)

    engine = _engine(monkeypatch, actions=[{"type": "click", "x": 5, "y": 5}])
    monkeypatch.setattr(engine, "_build_ctx",
                        lambda macro: {"background": True,
                                       "hwnd": macro.get("target_hwnd")})
    try:
        engine.run_on_windows("demo", [GAME_A[0], GAME_B[0]])
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and len(set(seen)) < 2:
            time.sleep(0.02)
    finally:
        engine.stop_all()
    assert set(seen) == {GAME_A[0], GAME_B[0]}, seen


# ── what the UI needs to offer the choice ─────────────────────────────────────

def test_matching_windows_reports_every_candidate(monkeypatch):
    _fake_windows(monkeypatch, [GAME_A, GAME_B])
    engine = _engine(monkeypatch)
    assert [h for h, _ in engine.matching_windows("demo")] == [GAME_A[0], GAME_B[0]]


def test_matching_windows_is_empty_without_a_target(monkeypatch):
    _fake_windows(monkeypatch, [GAME_A])
    engine = _engine(monkeypatch)
    engine._macros["demo"].pop("target_window")
    assert engine.matching_windows("demo") == []
    assert engine.matching_windows("no-such-macro") == []


# ── one run's guard must not speak for the other ──────────────────────────────

def test_a_guard_stopping_one_window_leaves_the_other_running(monkeypatch):
    """With two accounts side by side, one losing its screen says nothing about the
    other — so the guards are per run, not per macro."""
    _fake_windows(monkeypatch, [GAME_A, GAME_B])
    engine = _engine(monkeypatch)
    try:
        engine.run_on_windows("demo", [GAME_A[0], GAME_B[0]])
        assert _settle(engine)

        # Stand in for a guard firing on one window only.
        with engine._lock:
            key = ("demo", GAME_A[0])
            engine._stalled.add(key)
            engine._stop_reasons[key] = "lost its screen"
            engine._stop_flags[key].set()

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if engine.running_windows("demo") == [GAME_B[0]]:
                break
            time.sleep(0.02)
        assert engine.running_windows("demo") == [GAME_B[0]]
        assert engine.stopped_reason("demo") == "lost its screen"
    finally:
        engine.stop_all()
