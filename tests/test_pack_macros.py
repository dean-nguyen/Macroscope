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


def test_each_raid_gets_the_budget_its_own_panel_needs():
    """I wrote the opposite of this a few hours earlier.

    That test asserted both raids share one budget, on the reasoning that a number
    measured once should not drift into two by being written twice. The reasoning was
    fine; the premise was wrong. The 900 ms came from timing the *Individual* panel
    twice (506 and 512 ms) and applying it to both.

    Measured on a live guild list by watching the macro drive it, with no input of my
    own: the gap between one panel closing and the next being drawn ran 580, 627, 1100
    and 1197 ms. Two of four past 900 — and the failure was total, not partial: over 45 s
    the panels opened and closed, `guild_progress` never left the screen, and not one
    battle started. A guild member's panel loads another player's defence team; an
    Individual target is local.
    """
    budgets = {}
    for _name, macro in macros():
        for wait in _walk_image_waits(macro["actions"]):
            if "attack" in wait["template"]:
                budgets.setdefault(macro["name"], set()).add(
                    (wait["timeout_ms"], wait["poll_ms"]))

    for name, seen in budgets.items():
        assert len(seen) == 1, f"{name} uses more than one budget: {seen}"

    individual = budgets[_by_name("individual")["name"]].pop()
    guild = budgets[_by_name("guild")["name"]].pop()
    assert individual == (900, 100)
    assert guild == (1500, 100), "the guild panel is slower, and measurably so"


def test_a_panel_already_open_is_attacked_before_any_cell_is_clicked():
    """The bug this fixes made the macro attack from none of the panels it opened.

    A panel drawn later than its budget stays on screen for the rest of the tick and the
    loop delay — measured at 6-7 s — and the next tick's first cell click threw it away
    unseen. So the chain now opens with a look for Attack: one search, no click when
    there is nothing there, and a late panel becomes an attack on the next tick instead
    of a wasted one. It is the only part of this that does not depend on guessing a
    timeout correctly.
    """
    for _name, macro in macros():
        if "raid" not in macro["name"].lower():
            continue
        body = macro["actions"][-1]["on_found"]
        first = body[0]
        assert first["type"] == "find_and_click", (
            f"{macro['name']}: the cell chain should start by taking an open panel, "
            f"not with {first['type']}")
        assert first["template"].endswith("onmyoji_realmraid_attack.png")
        # And it must not click a cell to find that out.
        assert first.get("on_not_found"), "the cells belong in its on_not_found"


def _after_attack_chain(macro):
    """The branch that runs once an attack has taken: wait for the result, clear it."""
    def walk(actions):
        for a in actions:
            if (a["type"] == "image_check" and a.get("on_not_found")
                    and any(x["type"] == "image_wait" and "reward_confirm" in x["template"]
                            for x in a["on_not_found"])):
                return a["on_not_found"]
            for key in ("on_found", "on_not_found"):
                if a.get(key):
                    found = walk(a[key])
                    if found:
                        return found
        return None
    chain = walk(macro["actions"])
    assert chain, f"{macro['name']}: no post-attack chain found"
    return chain


def test_waiting_for_the_list_cannot_become_a_deadlock_again():
    """This chain already had one, at 180 s, and its fix left a smaller one at 30 s.

    The taps are a fixed number. If a win draws one more overlay than there are taps, the
    list *cannot* appear — and the final wait then sits out its whole timeout for a screen
    its own waiting is preventing, which is word for word the bug the 180 s version had.

    Measured on two real wins: the list came back 3.85 s and 4.1 s after the last tap. So
    8 s covers the good case twice over, and the bad case costs 8 s instead of 30. The
    real backstop is the next tick — `preamble` taps the line again every iteration — so
    an extra overlay should cost one loop delay, which is what the 30 s stopped from being
    true.
    """
    for _name, macro in macros():
        if "raid" not in macro["name"].lower():
            continue
        chain = _after_attack_chain(macro)
        list_waits = [a for a in chain
                      if a["type"] == "image_wait" and "reward_confirm" not in a["template"]]
        assert list_waits, f"{macro['name']}: nothing waits for the list to come back"
        for wait in list_waits:
            assert wait["timeout_ms"] <= 8000, (
                f"{macro['name']}: {wait['timeout_ms']} ms is long enough to feel like a "
                f"hang when a third overlay appears")

        # And the wait for the result itself must still outlast a battle: 14 s and 39 s
        # measured in one sitting, so this one is deliberately generous.
        result_waits = [a for a in chain
                        if a["type"] == "image_wait" and "reward_confirm" in a["template"]]
        assert all(a["timeout_ms"] >= 60000 for a in result_waits), result_waits


def test_the_gap_between_taps_matches_what_the_game_draws():
    """Measured on a live raid win: the second overlay was drawn 629 ms after the first
    tap. 1500 ms spent about 870 ms of every won battle looking at a screen that had
    already changed."""
    for _name, macro in macros():
        if "raid" not in macro["name"].lower():
            continue
        chain = _after_attack_chain(macro)
        taps = [a for a in chain
                if a["type"] == "find_and_click" and "reward_confirm" in a["template"]]
        assert len(taps) == 2, f"{macro['name']}: expected two taps, got {len(taps)}"
        first_gap = sum(x["ms"] for x in taps[0].get("on_found", [])
                        if x["type"] == "wait")
        assert 700 <= first_gap <= 1100, (
            f"{macro['name']}: {first_gap} ms between taps, against 629 ms measured")
