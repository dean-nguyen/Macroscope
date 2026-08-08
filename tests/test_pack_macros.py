"""Structural checks on the shipped pack macros.

Two of these were audits run by hand while the macros were being written, each after
a real defect. A check that only exists as something someone remembers to run is not
a check.
"""

import json
import pathlib

import pytest

PACK = pathlib.Path(__file__).resolve().parents[1] / "packs" / "onmyoji"
BRANCHES = ("on_found", "on_not_found", "on_match", "on_no_match")
INPUT_ACTIONS = {"click", "double_click", "right_click", "scroll", "drag",
                 "key", "type", "move"}
# An action whose on_found branch runs only because something was recognised.
GUARDS = {"image_check", "find_and_click", "image_wait", "pixel_check",
          "find_rects_and_click", "find_all_and_click"}

pytestmark = pytest.mark.unit


def macros():
    for path in sorted(PACK.glob("*.macro.json")):
        yield path.name, json.loads(path.read_text(encoding="utf-8"))


def walk(actions, guarded=False, path="actions"):
    """Every action, with whether a recognition guard is above it.

    The path carries each step's *template*, not just its type, because what matters
    about a nested click is which check let it run.
    """
    for i, action in enumerate(actions):
        template = pathlib.Path(action.get("template", "")).stem
        here = f"{path}[{i}]:{action.get('type')}" + (f"({template})" if template
                                                     else "")
        yield action, guarded, here
        for key in BRANCHES:
            nested = action.get(key)
            if not isinstance(nested, list):
                continue
            # Only a *positive* branch means something was recognised. on_not_found
            # runs precisely when it was not.
            deeper = guarded or (action.get("type") in GUARDS
                                 and key in ("on_found", "on_match"))
            yield from walk(nested, deeper, f"{here}.{key}")


def test_no_input_action_runs_without_something_being_recognised():
    """A tick that starts on a battle, a loading screen or an unanswered dialog must
    not fire coordinate clicks into it. Three actions were unguarded when this was
    first audited by hand, one of them a click posted before the captcha check that
    exists to prevent exactly that."""
    for name, macro in macros():
        unguarded = [where for action, guarded, where in walk(macro["actions"])
                     if action.get("type") in INPUT_ACTIONS and not guarded]
        assert not unguarded, f"{name}: unguarded input actions: {unguarded}"


def test_the_confirm_scroll_is_only_pressed_where_a_confirm_was_raised():
    """`dialog_ok` is the game's standard OK. Pressing it on a screen that merely
    happens to show one is how a macro accepts something it meant to dismiss — the
    reason the Wanted Quest invitation is handled by its own decline button and not
    by the generic dismiss path."""
    for name, macro in macros():
        for action, _guarded, where in walk(macro["actions"]):
            if action.get("template", "").endswith("onmyoji_dialog_ok.png"):
                assert "onmyoji_realmraid_refresh" in where or "level_up" in where \
                    or "defeat" in where, \
                    f"{name}: dialog_ok pressed somewhere unexpected: {where}"


def test_an_invitation_is_declined_by_its_own_button():
    """Accepting a Wanted Quest takes the client somewhere these macros do not
    navigate back from, and on an invitation the standard confirm button is *accept*.
    So the invite is cleared by clicking a template that is positively the decline —
    an uncaptured template then means nothing is pressed, rather than the wrong thing.
    """
    for name, macro in macros():
        declines = [action for action, _g, _w in walk(macro["actions"])
                    if action.get("template", "")
                    .endswith("onmyoji_wanted_quest_decline.png")]
        assert declines, f"{name}: nothing handles a Wanted Quest invitation"
        for action in declines:
            assert action["type"] == "find_and_click", \
                f"{name}: the invite must be dismissed by finding its decline button"


def test_the_invitation_is_cleared_before_the_macro_starts_clicking():
    """It can arrive over any screen, so it has to be dealt with in the preamble —
    ahead of the list check that gates every click."""
    for name, macro in macros():
        types = [a.get("template", "") for a in macro["actions"]]
        decline = next(i for i, t in enumerate(types)
                       if t.endswith("onmyoji_wanted_quest_decline.png"))
        gate = next(i for i, t in enumerate(types)
                    if t.endswith(("onmyoji_realmraid_refresh.png",
                                   "onmyoji_realmraid_guild_progress.png"))
                    and i > decline)
        assert decline < gate, f"{name}: the invite is handled too late"


def test_every_template_a_macro_uses_is_in_the_spec():
    from engine import template_store as ts

    spec = json.loads((PACK / "templates.spec.json").read_text(encoding="utf-8"))
    listed = {t["name"] for t in spec["templates"]}
    used = set()
    for _name, macro in macros():
        used |= {ts.basename_of(r) for r in ts.iter_refs(macro.get("actions", []))}

    assert used - listed == set(), f"used but not in the spec: {sorted(used - listed)}"
    assert listed - used == set(), f"in the spec but unused: {sorted(listed - used)}"


def test_the_macros_match_what_the_generator_produces(tmp_path):
    """The JSON is generated. A hand-edit would be silently overwritten next time
    anyone runs the generator, so it must not be possible to have one."""
    import subprocess
    import sys

    before = {p.name: p.read_text(encoding="utf-8") for p in PACK.glob("*.macro.json")}
    subprocess.run([sys.executable, str(PACK / "build_macros.py")], check=True,
                   capture_output=True)
    after = {p.name: p.read_text(encoding="utf-8") for p in PACK.glob("*.macro.json")}
    assert before == after, "a shipped macro differs from what the generator produces"
