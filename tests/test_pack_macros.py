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
    ahead of the check that gates every click.

    The gate is found structurally rather than by name. It used to be a tuple of the two
    raid markers, which meant adding a third macro raised StopIteration instead of
    saying what was wrong — and a per-macro list of marker names has to be edited by
    whoever adds a macro, which is exactly the person who will not think to.

    What is actually invariant: every pack macro ends with one `image_check` whose
    `on_found` holds everything that clicks. That is the gate, wherever its marker came
    from.
    """
    for name, macro in macros():
        gate = macro["actions"][-1]
        assert gate["type"] == "image_check" and gate.get("on_found"), (
            f"{name}: the last action should be the screen check that gates the body")

        types = [a.get("template", "") for a in macro["actions"]]
        decline = next(i for i, t in enumerate(types)
                       if t.endswith("onmyoji_wanted_quest_decline.png"))
        assert decline < len(types) - 1, f"{name}: the invite is handled too late"


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


# ── what is true of the Guild macro and nothing else ──────────────────────────

def _by_name(fragment):
    for name, macro in macros():
        if fragment.lower() in macro["name"].lower():
            return macro
    raise AssertionError(f"no pack macro named like {fragment!r}")


def test_the_guild_run_ends_on_its_own_clock():
    """The Guild list has no Refresh and no reliable "no wins left" popup.

    After 09:00 Vietnam time the guild raid stops *counting* wins — the crest reads
    "Raided", the counter stops moving, and you keep attacking until nothing is left. So
    `guild_no_wins` may never appear, and "no member offers an Attack button" is what
    finished actually looks like. The stall guard's condition is clicking without
    recognising anything, which is exactly that state, so the guard is the end of the run
    here rather than a symptom — and five minutes of it is four minutes of sitting still.
    """
    guild = _by_name("guild")
    assert guild["stall_timeout_ms"] == 120000
    from engine.macro_engine import _validate
    _validate(guild)          # checked at load, so a typo must fail here too

    individual = _by_name("individual")
    assert "stall_timeout_ms" not in individual, (
        "the Individual list has Refresh and a real no-attempts popup, so it has a "
        "cheaper end condition and should keep the default")


def test_the_exhausted_branch_waits_for_nothing():
    """It is paid on exactly the ticks that feel slowest.

    A tick where no member offers an Attack button has nothing to settle — no panel
    opened, no transition started. The 1200 ms that used to sit here was 1.2 s of the
    6.6 s such a tick spent blocking, and the loop delay already separates the ticks.
    """
    guild = _by_name("guild")

    def exhausted_waits(actions):
        """The deepest `on_not_found` chain is the "tried every cell" path."""
        total = 0
        for a in actions:
            if a["type"] == "wait":
                total += a["ms"]
            if a.get("on_not_found"):
                total += exhausted_waits(a["on_not_found"])
        return total

    body = guild["actions"][-1]["on_found"]
    waits = exhausted_waits(body)
    budget = sum(a["timeout_ms"] for a in _walk_image_waits(body))
    assert waits == 0, (
        f"a fully-raided list should block only on its panel budget ({budget} ms), "
        f"not on {waits} ms of fixed sleeps")


def _walk_image_waits(actions):
    for a in actions:
        if a["type"] == "image_wait":
            yield a
        for key in ("on_found", "on_not_found"):
            if a.get(key):
                yield from _walk_image_waits(a[key])


def test_both_raids_share_one_panel_budget():
    """They are the same `try_cells`, and a number measured once should not drift into
    two numbers by being written twice."""
    budgets = set()
    for name, macro in macros():
        for wait in _walk_image_waits(macro["actions"]):
            if "attack" in wait["template"]:
                budgets.add((wait["timeout_ms"], wait["poll_ms"]))
    assert budgets == {(900, 100)}, budgets


def test_the_guild_list_covers_every_row_the_panel_draws():
    """It covered three rows of four for as long as it existed.

    The generator said "the fourth is clipped by the panel edge", and that was simply
    wrong: drawn onto a live guild list at 1810x1020, all four rows sit fully inside the
    panel and the fourth row's members are ordinary targets. Two of the eight visible
    members were being skipped on every sweep.
    """
    guild = _by_name("guild")

    def cell_clicks(actions):
        out = []
        for a in actions:
            if a["type"] == "click" and "xp" in a and "yp" in a:
                out.append((round(a["xp"], 4), round(a["yp"], 4)))
            for key in ("on_found", "on_not_found"):
                if a.get(key):
                    out.extend(cell_clicks(a[key]))
        return out

    body = guild["actions"][-1]["on_found"]
    cells = cell_clicks(body)
    assert len(cells) == 8, f"expected two columns of four, got {len(cells)}: {cells}"

    columns = sorted({x for x, _ in cells})
    rows = sorted({y for _, y in cells})
    assert len(columns) == 2 and len(rows) == 4, (columns, rows)

    # Evenly pitched, because the fourth row is the pitch projected once rather than a
    # separate reading — if that ever stops holding, the projection was wrong.
    gaps = [round(b - a, 4) for a, b in zip(rows, rows[1:])]
    assert max(gaps) - min(gaps) < 0.002, f"rows are not evenly spaced: {gaps}"
