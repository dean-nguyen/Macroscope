"""Tests for the `stop` action that halts a running (looping) macro."""

import threading

import pytest

from engine.entitlements import BASIC_ACTIONS
from engine.macro_engine import MacroEngine, _validate

pytestmark = pytest.mark.unit


def test_stop_is_a_basic_action():
    # Free tier can use stop (it's not a paid detection feature).
    assert "stop" in BASIC_ACTIONS


def test_stop_action_validates():
    _validate({"name": "m", "actions": [{"type": "stop"}]})  # no exception


def test_stop_halts_a_looping_macro():
    eng = MacroEngine(log_fn=lambda *a: None)
    stop = threading.Event()
    macro = {"name": "m", "loop": True, "actions": [{"type": "stop"}]}

    # Without the stop action this loops forever; run it with a watchdog.
    t = threading.Thread(target=eng._execute, args=(macro, stop), daemon=True)
    t.start()
    t.join(timeout=5)

    assert not t.is_alive(), "stop action did not halt the loop"
    assert stop.is_set()


def test_stop_sets_flag_without_loop():
    eng = MacroEngine(log_fn=lambda *a: None)
    stop = threading.Event()
    eng._execute({"name": "m", "actions": [{"type": "stop"}]}, stop)
    assert stop.is_set()
