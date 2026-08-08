"""The editor must round-trip the safety fields, not just show them.

`humanize` and `stall_timeout_ms` were deleted on save once already, because the form
built its dict from scratch and dropped every key it did not know (E1.10). They are
now in the form itself — so the risk shifts from dropping them to *inventing* them:
opening an untouched macro and pressing Save must not add fields it never had, and
must not flatten a hand-tuned `{"click_px": 6}` into a bare `true`.

Driven through the real methods with a stub, so no Tk window is needed.
"""

from types import SimpleNamespace

import pytest

from gui.editor import MacroEditor, _ms_text, _ms_value

pytestmark = pytest.mark.unit


class _Var:
    def __init__(self, value=""):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


def _form():
    """Enough of the editor to run _load_macro and _collect_macro."""
    return SimpleNamespace(
        _name_var=_Var("m"), _desc_var=_Var(""), _hotkey_var=_Var(""),
        _loop_var=_Var(False), _loop_delay_var=_Var("0"), _bg_var=_Var(False),
        _target_var=_Var(""), _humanize_var=_Var(True),
        _stall_var=_Var(""), _idle_var=_Var(""),
        _humanize_detail=None, _target_hwnd=None, _target_class=None,
        _carried={}, _action_rows=[],
        _sync_rows=lambda: None, _collect_actions=lambda: [],
        _rebuild_list=lambda: None,
        _FORM_KEYS=MacroEditor._FORM_KEYS,
    )


def _round_trip(macro):
    form = _form()
    MacroEditor._load_macro(form, macro)
    return MacroEditor._collect_macro(form)


# ── nothing is invented ───────────────────────────────────────────────────────

def test_a_macro_that_sets_none_of_them_gains_none_of_them():
    """Opening and saving must not decorate a macro with defaults it never chose."""
    saved = _round_trip({"name": "m", "actions": []})
    for field in ("humanize", "stall_timeout_ms", "idle_timeout_ms"):
        assert field not in saved, f"{field} appeared from nowhere"


@pytest.mark.parametrize("field,value", [
    ("stall_timeout_ms", 0),
    ("stall_timeout_ms", 60000),
    ("idle_timeout_ms", 0),
    ("idle_timeout_ms", 900000),
    ("humanize", False),
])
def test_a_value_survives_a_round_trip(field, value):
    saved = _round_trip({"name": "m", "actions": [], field: value})
    assert saved[field] == value


def test_a_tuned_humanize_is_not_flattened_to_true():
    """The checkbox turns jitter off and back on; it does not redefine it."""
    tuned = {"timing_pct": 0.25, "click_px": 6}
    saved = _round_trip({"name": "m", "actions": [], "humanize": tuned})
    assert saved["humanize"] == tuned


def test_turning_jitter_off_writes_false():
    form = _form()
    MacroEditor._load_macro(form, {"name": "m", "actions": []})
    form._humanize_var.set(False)
    assert MacroEditor._collect_macro(form)["humanize"] is False


def test_turning_jitter_back_on_restores_what_was_tuned():
    tuned = {"click_px": 6}
    form = _form()
    MacroEditor._load_macro(form, {"name": "m", "actions": [], "humanize": tuned})
    form._humanize_var.set(False)
    assert MacroEditor._collect_macro(form)["humanize"] is False
    form._humanize_var.set(True)
    assert MacroEditor._collect_macro(form)["humanize"] == tuned


# ── what the form shows ───────────────────────────────────────────────────────

def test_the_checkbox_reflects_how_the_macro_reads():
    for value, expected in ((True, True), (False, False), (0, False),
                            ({"click_px": 2}, True)):
        form = _form()
        MacroEditor._load_macro(form, {"name": "m", "actions": [],
                                       "humanize": value})
        assert form._humanize_var.get() is expected, value


def test_an_unset_timeout_shows_blank_not_a_number():
    """Blank is what the engine reads as "use the default", and showing 300000 would
    make the user think the macro had chosen it."""
    form = _form()
    MacroEditor._load_macro(form, {"name": "m", "actions": []})
    assert form._stall_var.get() == ""
    assert form._idle_var.get() == ""


def test_zero_shows_as_zero_because_zero_means_off():
    form = _form()
    MacroEditor._load_macro(form, {"name": "m", "actions": [],
                                   "stall_timeout_ms": 0})
    assert form._stall_var.get() == "0"


# ── typing something unusable ─────────────────────────────────────────────────

def test_nonsense_in_a_timeout_box_leaves_the_field_out():
    """The engine rejects a non-number at load, and a macro that will not load is a
    worse outcome than a field reverting to its default."""
    form = _form()
    MacroEditor._load_macro(form, {"name": "m", "actions": []})
    form._stall_var.set("soon")
    assert "stall_timeout_ms" not in MacroEditor._collect_macro(form)


def test_what_the_boxes_accept():
    assert _ms_value("") is None
    assert _ms_value("   ") is None
    assert _ms_value("soon") is None
    assert _ms_value("0") == 0
    assert _ms_value("-5") == 0            # negatives are rejected at load
    assert _ms_value("60000") == 60000
    assert _ms_value("6e4") == 60000
    assert _ms_text(None) == ""
    assert _ms_text(0) == "0"
    assert _ms_text(900000) == "900000"


def test_the_form_owns_these_keys():
    """Or _collect_macro would carry a stale copy through alongside the new one."""
    for field in ("humanize", "stall_timeout_ms", "idle_timeout_ms"):
        assert field in MacroEditor._FORM_KEYS


def test_a_saved_macro_still_validates():
    from engine.macro_engine import _validate

    for value in (0, 60000, 900000):
        saved = _round_trip({"name": "m", "actions": [], "stall_timeout_ms": value})
        _validate(saved)
    _validate(_round_trip({"name": "m", "actions": [], "humanize": False}))
