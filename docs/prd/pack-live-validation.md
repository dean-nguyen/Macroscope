# PRD — Run the Onmyoji pack against the live game

**Backlog:** E1.4 · **Status:** todo · **Blocks:** E4.3 (the `v1.0.0` tag)

## Why this exists

Every part of the pack has been verified in isolation and none of it has been
verified together. That gap is the largest remaining risk to launch, and it is the
kind of gap that has already produced two hard defects in this project:
`realm-raid` could never raid at all — it looked for the Attack button on a screen
where that button does not exist — and the whole pack would have died on its first
action for any buyer who had not captured all 14 templates. Both were invisible to
reading the code and obvious within a minute of running it.

## What has been verified, and what has not

| Verified | How |
|---|---|
| All 9 macros pass `_validate` | `engine.macro_engine._validate` over the pack |
| Templates referenced == the spec, exactly | `tests/test_pack_store.py` |
| Each captured template matches at the right position | `tools/match_report.py` on a live window |
| A macro loop runs, logs missing templates once each, issues no clicks, stops | Ran `soul-farming` for 4 ticks against a window with nothing to match; clicks intercepted and suppressed |
| Scale search recovers 0.5x–2x | Positive control on a live frame: 0.9902–1.0000 |

| Not verified | Why it matters |
|---|---|
| Realm Raid's nested `on_not_found` target selection | Four levels deep; picks a grid cell, then attacks. Never executed |
| Proportional (`xp`/`yp`) clicks inside a real macro run | Verified only through a hand-built ctx, not through `MacroEngine` |
| The Refresh → confirm-dialog sequence | The dialog exists; the macro's answer to it has not run |
| Any macro completing a full battle cycle | Reward screen, loading transition, return to the activity screen |
| Behaviour when the anti-ban guard fires | `onmyoji_captcha.png` is uncaptured, so the guard is inert |

## Done means

1. `realm-raid` completes at least two full cycles unattended: selects a target,
   attacks, clears the result screen, returns to the list, and repeats — with the log
   showing each step and no click landing anywhere unintended.
2. One AP-based farming macro (`soul-farming` or `exploration`) completes at least
   two battle cycles the same way.
3. A stop-guard is observed firing for real — ideally `out_of_stamina` by running a
   farm until AP is gone. The macro must stop on its own, not be stopped by hand.
4. Every unintended click observed during the above is either fixed or written down
   here with the reason it is acceptable.
5. `docs/BACKLOG.md` updated with whatever this uncovers.

Two cycles rather than one: the second cycle is what proves the macro returns to a
state it can loop from, which is exactly where `realm-raid` failed before.

## How it will be run

Driven from a real `MacroEngine`, not by calling helpers — the point is to exercise
the path the app uses. `tools/game_probe.py watch` records the sequence so the run
can be reviewed afterwards rather than watched live.

Clicks are **not** intercepted this time. Suppressing them is what made the earlier
safety run safe, and also what stopped it proving anything about the game.

## Cost and consent

This spends real in-game resources on the owner's account: raid attempts (30 per
day) and AP. Roughly 4 raid tickets and a few dozen AP for the minimum above.
Nothing is irreversible and nothing spends currency. The owner must be present and
must start the game on the correct screen — the macros do not navigate menus.

## Known constraints going in

- **Start on the activity screen.** The macros repeat a battle; they do not navigate.
- **~3 s of client latency.** Buttons stay drawn after being pressed, which is why
  the pack polls at 2500 ms with a settle wait after each click. A faster poll
  clicked the same button several times.
- **A window at a size other than the capture size costs one scale search.** ~6.9 s
  on a 2560x1380 window, once per window size per 20 s. Expect the first ticks of a
  run to be slow if the game is not at 2840x1600.
- **The two Onmyoji instances behave differently** — one accepts any window size, the
  other enforces an aspect ratio. Unexplained; see the open questions in the backlog.

## Explicitly out of scope

- Capturing the outstanding templates (E1.5) beyond any that this run happens to
  surface.
- Multi-instance or parallel runs. One window, one macro, until this passes.
