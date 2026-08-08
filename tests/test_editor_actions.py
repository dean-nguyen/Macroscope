"""Tests that every action the engine runs can actually be reached from the editor.

`stop` was in the editor's field table and in no picker row, so the picker never
offered it and the only way to add one was to hand-edit the JSON — in a tool whose
whole claim is that you do not have to. Both shipped pack macros depend on it.

The check is structural rather than about `stop`, because the defect is structural:
`CLAUDE.md`'s "Adding a new action type" lists registering the type in `_GROUPS` as a
step, and a step in a document is not a guard.
"""

import pytest

from engine import action_runner as ar
from engine.macro_engine import _REQUIRED_ACTION_FIELDS
from gui import editor

pytestmark = pytest.mark.unit


def _picker_types():
    return [t for _group, types in editor._GROUPS for t in types]


def test_every_editable_action_is_offered_by_the_picker():
    offered = set(_picker_types())
    missing = sorted(set(editor._F) - offered)
    assert not missing, (
        f"in the editor's field table but in no picker row, so unreachable "
        f"without editing JSON: {missing}")


def test_the_picker_offers_nothing_the_editor_cannot_edit():
    unknown = sorted(set(_picker_types()) - set(editor._F))
    assert not unknown, f"picker offers types with no fields defined: {unknown}"


def test_no_action_is_offered_twice():
    types = _picker_types()
    assert len(types) == len(set(types)), "an action appears in two picker rows"


def test_the_picker_only_offers_actions_the_engine_can_run():
    handlers = set(_REQUIRED_ACTION_FIELDS)
    unknown = sorted(set(_picker_types()) - handlers)
    assert not unknown, f"picker offers types the engine would reject: {unknown}"


def test_stop_is_reachable():
    """The specific case, kept as its own line so a regression names itself."""
    assert "stop" in _picker_types()


# ── scroll means the same thing in both modes ────────────────────────────────

def test_scroll_amount_is_wheel_notches_in_background_mode(monkeypatch):
    seen = {}
    monkeypatch.setattr(ar.bg, "post_scroll",
                        lambda h, x, y, amount: seen.update(amount=amount))
    ar._scroll({"x": 10, "y": 20, "amount": 3}, {"background": True, "hwnd": 1})
    assert seen["amount"] == 3          # background_input multiplies by 120 itself


def test_scroll_amount_is_wheel_notches_in_foreground_mode_too(monkeypatch):
    """pyautogui hands `clicks` straight to mouse_event as dwData, and Windows counts
    120 per notch — so passing 3 through asked for 3/120 of a notch and nothing moved.
    The same macro scrolled three notches in background mode and not at all here, and
    the editor's default of 3 was exactly the value that did nothing."""
    seen = {}
    monkeypatch.setattr(ar.pyautogui, "scroll",
                        lambda clicks, **kw: seen.update(clicks=clicks, **kw))
    ar._scroll({"x": 10, "y": 20, "amount": 3}, None)
    assert seen["clicks"] == 3 * 120
    assert (seen["x"], seen["y"]) == (10, 20)


def test_a_negative_scroll_still_goes_the_other_way(monkeypatch):
    seen = {}
    monkeypatch.setattr(ar.pyautogui, "scroll",
                        lambda clicks, **kw: seen.update(clicks=clicks))
    ar._scroll({"amount": -2}, None)
    assert seen["clicks"] == -240
