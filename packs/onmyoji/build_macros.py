"""Generate the pack's two Realm Raid macros.

A generator rather than two hand-written files, because the target-selection chain
nests one level per grid cell: the schema has no "for each cell" action, so nine cells
means nine nested `on_not_found` branches, twelve levels deep. Hand-editing that is how
you get a branch that silently never runs, which is the defect `realm-raid` shipped
with before — it looked for the Attack button on a screen where that button does not
exist. It also keeps the shared guard chain in one place.

The pack deliberately covers only Realm Raid. It used to carry nine more macros, six of
which were byte-identical in structure apart from one line choosing which limit to stop
on, and none of which navigated anywhere — so the file name was documentation of which
screen to open first, and a "pack" of them was a pack of one macro with nine labels.
These two are here because they are the ones that have been **run against the live game
end to end**, and because they are genuinely different from each other: a fixed 3x3
grid with a Refresh button, versus a scrolling two-column member list with its own
`Win(s)` counter and no Refresh.

Every coordinate below was read off a live 1236x696 client area and converted to a
fraction, so the macros survive a window resize. Buttons are found by template, never
by coordinate, wherever a template exists for them.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

W, H = 1236, 696
PACK = ROOT / "packs" / "onmyoji"


# "Tap to continue" is a thin translucent line over whatever screen it is on, so it
# scores over a wide band: measured 0.940 and 0.918 on raid reward overlays, 0.776 on a
# defeat screen and 0.737 on a battle-victory screen — all four on a live window. The
# pack's usual 0.76 sat inside that band and only worked because a WGC capture subtracts
# 0.08; a user on the GDI fallback would have missed the two low ones and left the macro
# stuck on a result screen. Absent templates measure ~0.47 on this game, so 0.70 keeps a
# 0.23 gap while clearing the lowest real score by 0.04.
TAP_THRESHOLD = 0.70


# How long a cell click is given to open its target panel, and the single number that
# decides how fast a raid tick is.
#
# MEASURED on a live 1810x1020 client, `game_probe settle`:
#
#   a live cell's Attack button appears after 506 ms and 512 ms (scores 0.961, 0.971)
#   a defeated cell (KO stamp) never opens one — the whole budget buys nothing
#   one failing full-frame search costs ~200 ms at this size; a succeeding one ~100 ms
#
# The poll loop is `search then sleep(poll_ms)`, so a cycle is search + poll, not poll.
# At poll=200 the screen is sampled at ~0, 400, 800, 1200 ms: the 400 ms sample is too
# early for a 510 ms panel, so it was not found until ~800. At poll=100 the samples fall
# at ~0, 300, 600, 900 — so a live panel is found sooner *and* a dead cell stops sooner.
#
# 900 ms is 1.76x the slowest measured panel, with two samples after it. What it saves,
# from the same count that showed the problem:
#
#   Individual, 9 cells, all defeated: 13.5s -> 8.1s   tick 16.0s -> 10.6s
#   Guild,      6 cells, all defeated: 10.2s -> 6.6s   tick 12.7s ->  9.1s
#
# Guild keeps a 1.2s wait of its own for selecting the tab, which is why its blocking
# time is 6.6s and not 6 x 0.9s. Recounted from the generated JSON rather than reasoned
# about: the first version of this comment said 7.3s because it forgot that wait.
#
# A budget too short is recoverable and a budget too long is not: missing a live panel
# costs one more tick, while overpaying costs the full budget on every dead cell, every
# tick, forever. The chain has no memory, so a cell found dead is charged again next tick.
#
# Only two clean samples, and honestly so — the third was contaminated by the previous
# target's panel still being open and read "0 ms", which is why the probe now refuses to
# measure when the template is already on screen. The real fix is not a shorter wait but
# recognising the KO stamp, so a dead cell costs one match instead of a timeout; that
# needs `image_check` to accept a region, which it does not.
# 900 ms is right for the Individual list and WRONG for the Guild one, which is why
# this is a per-macro argument now and not one shared constant.
#
# Measured a second time, on a live guild list, by watching the macro drive it with no
# input of my own: the gap between one panel closing and the next being drawn ran 580,
# 627, 1100 and 1197 ms. Two of those four are past 900, and the failure is total rather
# than partial — every cell click dismisses the panel that was still drawing, so the
# macro never looks at a panel during the window it is open. Observed for 45 s straight:
# panels opening and closing, `guild_progress` never once leaving the screen, not one
# battle started. A plain posted click on that same Attack button started a battle
# immediately, which is what ruled out the template, the coordinate and the input method.
#
# The Individual panel is a local target; a guild member's is another player's defence
# team, and it shows. 1500 covers the slowest seen with a sample to spare at poll=100.
PANEL_BUDGET_INDIVIDUAL_MS = 900
PANEL_BUDGET_GUILD_MS = 1500
PANEL_POLL_MS = 100

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
    """A screen that just needs acknowledging (level-up, defeat).

    Cleared by clicking something the engine can *see* — the standard confirm scroll,
    or the "Tap to continue" line — never a guessed coordinate. Measured on a real
    defeat screen: the position this used to click blind, (733, 422), lands inside the
    "Get stronger via:" panel among three navigation buttons — one of which is "Challenge
    Again", i.e. spend another attempt on the fight you just lost. The screen's actual
    dismiss is the "Tap to continue" line that reward_confirm matches at 0.776. Neither
    find_and_click clicks anything when its template is absent, so a screen this does
    not understand is left alone rather than poked.
    """
    return {"type": "image_check", "template": f"templates/{template}",
            "threshold": threshold,
            "on_found": [
                find_click("onmyoji_dialog_ok.png", on_found=[wait(1200)]),
                find_click("onmyoji_reward_confirm.png", threshold=TAP_THRESHOLD,
                           on_found=[wait(1200)]),
            ]}


def find_click(template, threshold=0.8, on_found=None, on_not_found=None):
    return {"type": "find_and_click", "template": f"templates/{template}",
            "threshold": threshold,
            "on_found": on_found if on_found is not None else [wait(1200)],
            "on_not_found": on_not_found or []}


# The guards and housekeeping every tick starts with. Templates not captured yet
# degrade to "not found" and are listed once per run by the engine, so a guard whose
# template is missing costs nothing but also protects nothing.
def preamble(*limit_templates):
    return [
        stop_on("onmyoji_captcha.png"),
        stop_on("onmyoji_inventory_full.png"),
        *[stop_on(t) for t in limit_templates],
        find_click("onmyoji_reconnect_retry.png"),

        # An invitation from another player — a Wanted Quest bounty — can arrive over
        # any screen, and accepting one takes the client somewhere these macros do not
        # navigate back from.
        #
        # It is deliberately NOT routed through dismiss(), which clears a screen by
        # pressing the standard confirm scroll. On an invitation that button is
        # *accept*. This clicks one thing only: a button positively identified as the
        # decline, so an uncaptured template means nothing is pressed rather than the
        # wrong thing being pressed — the same trap as "Challenge Again" on the defeat
        # screen, which is how that one was found.
        find_click("onmyoji_wanted_quest_decline.png"),

        dismiss("onmyoji_level_up.png"),
        dismiss("onmyoji_defeat.png"),
        find_click("onmyoji_reward_confirm.png", threshold=TAP_THRESHOLD),
    ]


def after_attack(list_template):
    """Hold the tick until the battle is over, then clear the result screens.

    Wait for the **result** screen, not for the list. Waiting for the list deadlocked:
    the post-battle victory screen is fullscreen with "Tap to continue" at the bottom,
    the list is not behind it, and the only way to reach the list is to tap. The macro
    sat inside image_wait for the full 180 s timeout waiting for a screen that its own
    wait was preventing.

    That earlier version also opened with a 6 s settle, because an image_wait on the
    *list* template returned 0.2 s after the Attack click — the game keeps the previous
    screen drawn while it fades out. Waiting on the result instead makes that settle
    pointless, and it was costing 6 s of every raid: scored against 14 frames of a real
    run — the list, the attack panel, the battle, the transition — "Tap to continue"
    reaches only **0.32-0.44**, against **0.938** on the one frame where the result
    screen is genuinely up. There is nothing for a settle to protect. What remains is
    long enough for the click to register.

    Then tap twice. Clearing the fullscreen result returns to the list, where a second
    reward overlay is drawn over it — that one *does* leave the Refresh button visible,
    which is what made the first reading of this look like the list had come back.
    A third overlay, if there is one, is cleared by the next tick's own reward step, so
    a tap that goes too early costs one loop delay rather than the cycle.

    A defeat offers the same "Tap to continue" — observed on a real loss, where the
    "Failed" banner scored 0.997 and the tap line 0.776, so this chain clears a lost
    battle the same way it clears a won one.
    """
    tap = "onmyoji_reward_confirm.png"
    return [
        # Long enough to have left the list screen if the attack took.
        wait(2500),
        # And if it did not, say so cheaply. A posted click can be swallowed — a panel
        # still animating, a frame dropped — and then no battle starts and no result
        # ever appears. Waiting that out cost **180 seconds per failed attack**,
        # observed live with both game windows sitting idle on the target list. The
        # marker is only on the list, so seeing it here means the attack did not take:
        # do nothing, end the tick, and let the next one try again in one loop delay.
        {"type": "image_check", "template": f"templates/{list_template}",
         "threshold": 0.8,
         "on_not_found": [
             # Polled often enough that the granularity is not itself a delay. Each
             # poll costs ~110 ms of matching on a 1917x1080 window, so 750 ms is
             # about a seventh of the time.
             # 300 rather than 750: a poll costs ~200 ms of matching, so the cycle is
             # search + poll and 750 made the granularity ~950 ms of pure lateness in
             # noticing a screen that was already up. The 120 s timeout stays — it has
             # to outlast a battle, measured at 14 s and 39 s in one sitting.
             {"type": "image_wait", "template": f"templates/{tap}",
              "threshold": TAP_THRESHOLD, "timeout_ms": 120000, "poll_ms": 300},
             # 900, not 1500. Measured on a live raid win: the second overlay was drawn
             # **629 ms** after the first tap, so 1500 spent about 870 ms staring at a
             # screen that had already changed.
             find_click(tap, threshold=TAP_THRESHOLD, on_found=[wait(900)]),
             find_click(tap, threshold=TAP_THRESHOLD, on_found=[wait(1000)]),
             # 8 s, not 30. This is the same deadlock the 180 s version had, smaller:
             # if there is a third overlay the taps are spent, the list *cannot* appear,
             # and this waits out its whole timeout for a screen its own wait is
             # preventing. Measured on two real wins, the list came back 3.85 s and 4.1 s
             # after the last tap, so 8 s covers the good case twice over — and the bad
             # case is now 8 s instead of 30.
             #
             # The real backstop is the next tick: `preamble` taps the line again every
             # iteration, so an extra overlay costs one loop delay. That is what the
             # docstring above always claimed and what the 30 s stopped from being true.
             {"type": "image_wait", "template": f"templates/{list_template}",
              "threshold": 0.8, "timeout_ms": 8000, "poll_ms": 300},
         ]},
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


def try_cells(cells, exhausted, post_attack, budget_ms=PANEL_BUDGET_INDIVIDUAL_MS):
    """Click each cell in turn until one opens a panel with an Attack button.

    Built from the inside out, so `exhausted` runs only after every cell has been
    tried and none of them offered an attack. A cell that is already defeated opens
    nothing, so the attack template simply does not appear and the chain moves on.

    The settle after each click is an `image_wait` rather than a fixed `wait`, so a
    live target resolves as soon as its panel is drawn instead of always paying the
    full budget. That budget is what multiplies — nine dead cells were 13.5 s of a
    21.5 s tick.

    A live run then showed attacks that never started a battle, and a plausible
    explanation was that `image_wait` returns the instant the button is *visible* —
    possibly while its panel is still animating, so the click lands where the button
    no longer is. That was **not** confirmed: the measurement meant to catch it saw
    the panel not open at all, on a window another macro was driving at the same time.
    So no settle is added here on the strength of a guess. What `after_attack` does
    instead is notice quickly when an attack did not take, which is the right fix
    whatever the cause.
    """
    chain = exhausted
    for x, y in reversed(cells):
        chain = [
            click(x, y),
            {"type": "image_wait",
             "template": "templates/onmyoji_realmraid_attack.png",
             "threshold": 0.8, "timeout_ms": budget_ms,
             "poll_ms": PANEL_POLL_MS},
            find_click("onmyoji_realmraid_attack.png",
                       on_found=post_attack,
                       on_not_found=chain),
        ]
    # Take a panel that is already open before clicking anything.
    #
    # A panel drawn later than its budget stays on screen through the rest of the tick
    # and the loop delay — measured at 6-7 s — and the next tick's first cell click threw
    # it away unseen. So a run could open eight panels a tick and attack from none of
    # them. One search, no click when there is nothing there, and it turns a wasted tick
    # into an attack on the next one. It is also the only part of this that does not
    # depend on guessing a timeout correctly.
    return [find_click("onmyoji_realmraid_attack.png",
                       on_found=post_attack,
                       on_not_found=chain)]


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
# Four rows, not three. This said "the fourth is clipped by the panel edge" and that was
# simply wrong: measured against a live guild list at 1810x1020, all four rows are fully
# drawn inside the panel and the fourth row's members are ordinary attackable targets.
# The macro had been ignoring two of the eight visible members on every sweep.
#
# The fourth y is the existing pitch projected once (460 + 132.5), not a fresh reading:
# the three known rows are 132.5 apart in reference coords, so 592 is where the next one
# has to be — and drawn onto the live frame it lands squarely inside both cards. Keeping
# the first three untouched matters, because those are the ones live runs have validated;
# recentring them to look tidier would risk what already works.
#
# A fifth row would need a scroll, which this input method has not been shown to do in
# this game (see the open questions in docs/BACKLOG.md), and the panel's inner edge sits
# just below the fourth row anyway.
#
# The cost of the two extra cells is 1.8s on a tick where every member is already done
# (2 x PANEL_BUDGET_MS) and nothing when one of them is attackable. Coverage is the point
# of the macro, and the exhausted case now ends on a two-minute clock regardless.
MEMBER_Y = [195, 328, 460, 592]
GUILD_MEMBERS = [(x, y) for y in MEMBER_Y for x in MEMBER_X]

TAB_GUILD = (1193, 447)

guild = {
    "name": "Onmyoji - Realm Raid (Guild)",
    "description": (
        "Raid the Guild member list: selects the Guild tab, opens each visible member "
        "in turn and attacks the first that offers an Attack button, then clears the "
        "result. Covers the eight members visible without scrolling — the guild list "
        "scrolls and this input method has not been shown to scroll it. Ends when no "
        "member offers an Attack button for two minutes, which is what finished looks "
        "like here: after 09:00 Vietnam time the guild raid stops counting wins, the "
        "crest reads 'Raided', and you keep attacking until nothing is left. Also STOPS "
        "on a verification screen or a full inventory. Start it ON the Realm Raid screen."
    ),
    # Two minutes rather than the default five. The stall guard's condition — clicking
    # without recognising anything — is exactly what "every visible member is done" looks
    # like, so here it is not a symptom but the end of the run, and there is no cheaper
    # signal: `guild_no_wins` may never appear at all, because after 09:00 VN the counter
    # stops moving instead of blocking. Two minutes is about three exhausted ticks past
    # the point of doubt, and short enough not to sit there.
    "stall_timeout_ms": 120000,
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
            budget_ms=PANEL_BUDGET_GUILD_MS,
            # No Refresh here: every visible member is done. Say nothing and let the
            # next tick look again — a member's guardians are reset by other players'
            # progress, so one exhausted tick is not proof the run is over, which is why
            # this ends on the stall guard's clock rather than immediately.
            #
            # And nothing to wait for: the 1200 ms that used to sit here settled nothing
            # (there is no panel, no transition — the tick simply found nothing) while
            # being paid on exactly the ticks that feel slowest. It was 1.2 s of the 6.6 s
            # a fully-raided list spent blocking.
            exhausted=[],
            # The guild progress banner is on the list screen and nowhere else.
            post_attack=after_attack("onmyoji_realmraid_guild_progress.png"),
        ))
    ),
}

# ── Souls: one gate, one button, and the result screen the raids already clear ──
#
# Far simpler than either raid, and the simplicity is the point: there is no target
# grid, nothing to scroll, and no per-target popup. A tick either sees the gate screen
# and presses Challenge, or sees nothing it understands and presses nothing.
#
# Everything about clearing the aftermath is already in `preamble`: reward_confirm
# ("Tap to continue") ends a win and a loss alike, and dismiss() handles a level-up.
# So the body is one conditional click.
#
# The gate marker is the *selected* "Foolery" label, and it has to be the selected one.
# Unselected, the same word is pale text on the same parchment; selected, it sits on a
# red brush stroke. Only the selected state can tell "I am on Foolery" from "I am on
# Greed" — and Greed, Anger and Foolery all offer a Challenge button in the same place,
# so a marker that matched any of them would happily farm the wrong gate.

souls_foolery = {
    "name": "Onmyoji - Souls (Sougenbi, Foolery)",
    "description": (
        "Farm the Sougenbi Foolery soul gate: presses Challenge, lets the fight run, "
        "clears the result screen, repeats. Only acts while the Foolery gate is "
        "selected and on screen, so it cannot farm Greed or Anger by mistake. STOPS on "
        "a verification screen, a full inventory, or when stamina runs out. Start it ON "
        "the Souls screen with Sougenbi -> Foolery selected, your lineup deployed and "
        "Auto battle ON."
    ),
    "background": True,
    "target_window": "Onmyoji",
    "target_class": "Win32Window",
    "loop": True,
    "loop_delay_ms": 2500,
    "actions": preamble("onmyoji_no_stamina.png") + only_on_list(
        "onmyoji_souls_foolery.png",
        [
            # Pressing Challenge is the whole macro. It is inside the gate check, so a
            # tick that lands mid-battle or on an unanswered dialog presses nothing.
            #
            # The wait is long because it has to outlast a fight, and it costs nothing
            # to be generous: the tick that follows finds the result screen through
            # `preamble` whether it arrived early or late. A short wait would have the
            # macro press Challenge again while the previous fight is still resolving,
            # which is how a run spends two lots of stamina on one screen.
            find_click("onmyoji_souls_challenge.png",
                       on_found=[wait(12000)]),
        ],
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
                        (guild, "realm-raid-guild.macro.json"),
                        (souls_foolery, "souls-sougenbi-foolery.macro.json")):
    _validate(macro)                      # refuse to write something that will not load
    path = PACK / filename
    path.write_text(json.dumps(macro, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"{filename}: validates, {len(macro['actions'])} top-level actions, "
          f"nesting depth {depth(macro['actions'])}")
