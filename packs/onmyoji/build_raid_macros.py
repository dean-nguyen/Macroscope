"""Generate the two Realm Raid macros.

Written as a generator rather than by hand because the target-selection chain nests
one level per grid cell: the schema has no "for each cell" action, so trying nine
cells means nine nested on_not_found branches. Hand-editing that is how you get a
branch that silently never runs — which is exactly the defect realm-raid shipped with
before (it looked for the Attack button on a screen where that button does not exist).

Every coordinate below was read off a live 1236x696 client area and converted to a
fraction, so the macros survive a window resize. The Attack button is found by
template, never by coordinate, because the panel opens next to whichever card was
clicked and so has no fixed position.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

W, H = 1236, 696
PACK = ROOT / "packs" / "onmyoji"


def frac(x, y):
    return {"xp": round(x / W, 4), "yp": round(y / H, 4)}


def click(x, y):
    return {"type": "click", **frac(x, y)}


def wait(ms):
    return {"type": "wait", "ms": ms}


def stop_on(template, threshold=0.7):
    return {"type": "image_check", "template": f"templates/{template}",
            "threshold": threshold, "on_found": [{"type": "stop"}]}


def dismiss(template, threshold=0.8):
    """A screen that needs one click in the middle to clear (level-up, defeat)."""
    return {"type": "image_check", "template": f"templates/{template}",
            "threshold": threshold,
            "on_found": [click(733, 422), wait(1200)]}


def find_click(template, threshold=0.8, on_found=None, on_not_found=None):
    return {"type": "find_and_click", "template": f"templates/{template}",
            "threshold": threshold,
            "on_found": on_found if on_found is not None else [wait(1200)],
            "on_not_found": on_not_found or []}


# The guards and housekeeping every raid tick starts with. Templates not captured
# yet degrade to "not found" and are listed once per run by the engine.
def preamble(no_attempts_template):
    return [
        stop_on("onmyoji_captcha.png"),
        stop_on("onmyoji_inventory_full.png"),
        stop_on(no_attempts_template),
        find_click("onmyoji_reconnect_retry.png"),
        dismiss("onmyoji_level_up.png"),
        dismiss("onmyoji_defeat.png"),
        find_click("onmyoji_reward_confirm.png", threshold=0.76),
    ]


def after_attack(list_template):
    """Hold the tick until the battle is over, then clear the result screens.

    Three measured details, each of which replaced something that failed in a real run:

    The fixed wait first. The game keeps the previous screen fully drawn while it fades
    into the battle, so an image_wait on the list template returned 0.2 s after the
    Attack click and the macro spent the next 15 s clicking grid coordinates onto a
    battle screen. The PRD already recorded ~3 s of client latency for a button staying
    drawn after being pressed; a screen change costs the same.

    Then wait for the **result** screen, not for the list. Waiting for the list
    deadlocked: the post-battle victory screen is fullscreen with "Tap to continue" at
    the bottom, the list is not behind it, and the only way to reach the list is to tap.
    The macro sat inside image_wait for the full 180 s timeout waiting for a screen that
    its own wait was preventing.

    Then tap twice. Clearing the fullscreen result returns to the list, where a second
    reward overlay is drawn over it — that one *does* leave the Refresh button visible,
    which is what made the first reading of this look like the list had come back.
    A third overlay, if there is one, is cleared by the next tick's own reward step.

    A defeat is assumed to offer the same "Tap to continue". If it does not, the wait
    times out and the next tick recovers from whatever is on screen; that path has not
    been observed.
    """
    tap = "onmyoji_reward_confirm.png"
    return [
        wait(6000),
        {"type": "image_wait", "template": f"templates/{tap}",
         "threshold": 0.76, "timeout_ms": 180000, "poll_ms": 2000},
        find_click(tap, threshold=0.76, on_found=[wait(2500)]),
        find_click(tap, threshold=0.76, on_found=[wait(1500)]),
        {"type": "image_wait", "template": f"templates/{list_template}",
         "threshold": 0.8, "timeout_ms": 30000, "poll_ms": 1500},
    ]


def only_on_list(list_template, actions):
    """Run *actions* only when the target list is actually on screen.

    Without this the cell chain opens with an unconditional click, so a tick that
    starts on a battle, a loading screen or an unanswered dialog fires six or nine
    coordinate clicks into it. The list template is already in the spec as the "am I on
    the list screen" marker; this is what makes that true.

    It also gives the stall guard a recognition on every good tick, which is the signal
    it needs to tell a working macro from a blind one.

    The trade: on a tick where the check misses, the macro sends no input at all, and
    the stall guard's condition is *clicking* blind — so nothing stops it. That is the
    safe direction (no unintended clicks, and the log says so every tick) but it is a
    silent loop, filed as E2.6.
    """
    return [{"type": "image_check", "template": f"templates/{list_template}",
             "threshold": 0.8, "on_found": actions}]


def try_cells(cells, exhausted, post_attack):
    """Click each cell in turn until one opens a panel with an Attack button.

    Built from the inside out, so `exhausted` runs only after every cell has been
    tried and none of them offered an attack. A cell that is already defeated opens
    nothing, so the attack template simply does not appear and the chain moves on.
    """
    chain = exhausted
    for x, y in reversed(cells):
        chain = [
            click(x, y),
            wait(1500),
            find_click("onmyoji_realmraid_attack.png",
                       on_found=post_attack,
                       on_not_found=chain),
        ]
    return chain


# ── Individual: a fixed 3x3 grid, with a Refresh button when it is used up ─────

GRID_X = [291, 617, 941]
GRID_Y = [203, 333, 467]
INDIVIDUAL_CELLS = [(x, y) for y in GRID_Y for x in GRID_X]

individual = {
    "name": "Onmyoji - Realm Raid (Individual)",
    "description": (
        "Raid the Individual 3x3 target list: opens each target in turn, attacks the "
        "first one that offers an Attack button, clears the result, and refreshes the "
        "list when all nine are defeated. STOPS on a verification screen, a full "
        "inventory, or when attempts run out. Start it ON the Realm Raid screen with "
        "the Individual tab selected."
    ),
    "background": True,
    "target_window": "Onmyoji",
    "target_class": "Win32Window",
    "loop": True,
    "loop_delay_ms": 2500,
    "actions": preamble("onmyoji_no_attempts.png") + only_on_list(
        "onmyoji_realmraid_refresh.png", try_cells(
        INDIVIDUAL_CELLS,
        # Nothing raidable anywhere: refresh the list and answer the dialog that
        # refreshing raises — "Raid log progress will be reset if you refresh.
        # Continue?" with Cancel and OK. A run that clicked Refresh without answering
        # it pressed Refresh 23 times in 10 minutes and never refreshed anything.
        #
        # Everything is nested inside Refresh's own on_found, so nothing is clicked
        # when Refresh was not there. An earlier version clicked the OK position
        # unconditionally and fired it onto a battle screen.
        exhausted=[
            find_click("onmyoji_realmraid_refresh.png",
                       on_found=[
                           wait(1500),
                           find_click("onmyoji_dialog_ok.png",
                                      on_found=[wait(2500)]),
                           wait(1500),
                       ]),
        ],
        # Refresh only exists on the Individual list screen, so its reappearance is
        # the signal that the battle finished and the list is back.
        post_attack=after_attack("onmyoji_realmraid_refresh.png"),
    )),
}

# ── Guild: a scrolling two-column member list, no Refresh ─────────────────────

MEMBER_X = [560, 892]
# Only the three fully visible rows. The fourth is clipped by the panel edge, and
# reaching the rest of the list needs a scroll, which this input method has not been
# shown to do in this game (see the open questions in docs/BACKLOG.md).
MEMBER_Y = [195, 328, 460]
GUILD_MEMBERS = [(x, y) for y in MEMBER_Y for x in MEMBER_X]

TAB_GUILD = (1193, 447)

guild = {
    "name": "Onmyoji - Realm Raid (Guild)",
    "description": (
        "Raid the Guild member list: selects the Guild tab, opens each visible member "
        "in turn and attacks the first that offers an Attack button, then clears the "
        "result. Covers the six members visible without scrolling — the guild list "
        "scrolls and this input method has not been shown to scroll it. STOPS on a "
        "verification screen, a full inventory, or when the daily wins are used up."
    ),
    "background": True,
    "target_window": "Onmyoji",
    "target_class": "Win32Window",
    "loop": True,
    "loop_delay_ms": 2500,
    "actions": (
        # The guards come FIRST, before any click. An earlier version selected the tab
        # at the top of the tick, so a verification screen got one or two clicks posted
        # into it *before* the captcha check that exists to stop exactly that.
        preamble("onmyoji_guild_no_wins.png")
        + [
            # Select the Guild tab, unless the Guild list is already up — and only from
            # the Individual list, never from a battle or a loading screen. Measured: a
            # click that lands while a member panel is open only dismisses the panel, so
            # the tab is clicked, checked, and clicked again rather than trusted once.
            {"type": "image_check",
             "template": "templates/onmyoji_realmraid_guild_progress.png",
             "threshold": 0.8,
             "on_not_found": only_on_list("onmyoji_realmraid_refresh.png", [
                 click(*TAB_GUILD),
                 wait(1200),
                 {"type": "image_check",
                  "template": "templates/onmyoji_realmraid_guild_progress.png",
                  "threshold": 0.8,
                  "on_not_found": [click(*TAB_GUILD), wait(1200)]},
             ])},
        ]
        + only_on_list("onmyoji_realmraid_guild_progress.png", try_cells(
            GUILD_MEMBERS,
            # No Refresh here: every visible member is done. Say nothing and let the
            # next tick look again — a member's guardians are reset by other players'
            # progress, and the stall guard stops a run that stays blind.
            exhausted=[wait(1200)],
            # The guild progress banner is on the list screen and nowhere else.
            post_attack=after_attack("onmyoji_realmraid_guild_progress.png"),
        ))
    ),
}


def depth(actions, level=0):
    """How deep the nesting goes, so the cost of the chain is visible."""
    best = level
    for a in actions:
        for key in ("on_found", "on_not_found", "on_match", "on_no_match"):
            if isinstance(a.get(key), list) and a[key]:
                best = max(best, depth(a[key], level + 1))
    return best


from engine.macro_engine import _validate

for macro, filename in ((individual, "realm-raid-individual.macro.json"),
                        (guild, "realm-raid-guild.macro.json")):
    _validate(macro)                      # refuse to write something that will not load
    path = PACK / filename
    path.write_text(json.dumps(macro, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"{filename}: validates, {len(macro['actions'])} top-level actions, "
          f"nesting depth {depth(macro['actions'])}")
