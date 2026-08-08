# PRD — Run the Onmyoji pack against the live game

**Backlog:** E5.2 · **Status:** both Realm Raid modes done, AP farms outstanding ·
**Blocks:** the `v1.0.0` tag

## Results — Realm Raid, 2026-08-07

Run through a real `MacroEngine` against a live 1236x696 client, clicks not
intercepted, five raid tickets spent. **Six defects, four of them in the engine**, and
every one of them was invisible to reading the code — which is what this document
predicted.

| # | What broke | Where it is fixed |
|---|---|---|
| 1 | **The pack could only ever work at exactly the capture size.** Scale discovery was rationed per window size, so the first template to miss spent the interval and every template after it was refused. Every macro checks absent guards first, so the one template actually on screen never got a search. Measured: five templates scored in a row all read "no match"; the one whose button was plainly visible scored **0.94** when given a search of its own | `image_matcher._may_sweep` — a template that has never searched at this window size gets its own turn, floored by what the last search cost |
| 2 | **`"target_window": "Onmyoji"` resolved to a YouTube tab** titled "(176) Onmyoji - … - YouTube" and posted a click into the browser | `background_input.find_all_windows` ranks candidates and accepts a `target_class`; the picker records it |
| 3 | **The macro clicked grid coordinates onto a battle screen** for 15 s. `image_wait` on the list template returned 0.2 s after the Attack click, because the game keeps the old screen drawn while it fades out | A fixed settle before the wait, then wait for the *result* screen |
| 4 | **Waiting for the list after a battle deadlocked.** The post-battle screen is fullscreen with "Tap to continue"; the list is not behind it and the only way back is to tap. The macro sat in `image_wait` for the full 180 s timeout waiting for a screen its own wait prevented | Wait for `reward_confirm`, tap it, tap the second overlay |
| 5 | **Refresh was pressed 23 times in 10 minutes and refreshed nothing.** It raises "Raid log progress will be reset if you refresh. Continue?" and the macro never answered | `onmyoji_dialog_ok.png`, clicked inside Refresh's own `on_found` so it cannot fire onto a battle screen |
| 6 | **The capture-time collision check missed a real duplicate.** Two crops of the same element at different window sizes scored 0.31 as stored; the same button captured from a 2840x1600 and a 1236x696 window is the same button. The check compared crops as stored, and then only on the coarse ladder | `template_check._cross_score` runs the matcher's own two-stage search, in both directions |

**Verified working.** Two full cycles unattended, then a third after a refresh:
target selected → Attack (0.981, 0.916, 0.927) → battle → result cleared → list back →
next target. Tickets 16/30 → 11/30, Weekly 62 → 70, Rank 1883 → 1674, raid log 4 → 8,
and the raided targets carry KO stamps. Proportional `xp`/`yp` clicks landed on the
right grid cells through a real run. Jitter moved every click a few pixels inside the
matched button and none of them missed.

## Results — Guild Raid and the defeat path, 2026-08-08

`Win(s): n/6` counts wins **remaining**, not used, which is the opposite of how the
first pass read it — the reason this was recorded as blocked. Five guild attempts spent.

**Verified working.** Four full cycles. The macro selected the Guild tab from the
Individual list on its own (`guild_progress` 1.000 after the switch), opened a member,
attacked (0.989, 0.945, 0.989), waited out battles of 25-47 s, cleared the result and
returned to the list, twice per run. The result needs **two** taps — the fullscreen
victory screen, then a second overlay drawn over the list — and both fired (0.871,
0.872). `Win(s)` 6/6 → 5/6 and Raid Progress 19.41% → 23.53% confirm the wins landed.

**The defeat path is verified too**, by losing one. The `Failed` banner scores 0.997 and
the screen's "Tap to continue" 0.776, so the same chain clears a lost battle as a won
one. It also exposed a defect: `dismiss()` cleared level-up and defeat screens by
clicking (733, 422) blind, which on the defeat screen lands inside the "Get stronger
via:" panel — **one of whose three buttons is "Challenge Again"**, i.e. spend another
attempt on the fight just lost. Both screens are now cleared by clicking something the
engine can see, and nothing is clicked when neither template matches.

**One threshold was quietly wrong.** `reward_confirm` is a thin translucent line and
scores over a wide band: 0.940 and 0.918 on raid overlays, 0.776 on the defeat screen,
0.737 on a battle-victory screen. The pack used 0.76, *inside* that band, and only
worked because a WGC capture subtracts 0.08 — a user on the GDI fallback would have
missed the two low ones and left the macro stuck on a result screen. Now 0.70, which
clears the lowest real score by 0.04 and stays 0.23 above the ~0.47 an absent template
scores here.

**Also learned:** the Guild member list **re-sorts** as guardians are defeated, so fresh
targets rise into the visible six without scrolling. That does not answer whether
PostMessage can scroll it, but it makes the answer much less urgent.

**Not verified.** The `no_attempts` and `guild_no_wins` guards (neither limit reached),
the AP farms, and scrolling the Guild list.

**One limitation this exposed in the stall guard.** It did not fire during the 10
minutes of pressing Refresh, because `find_and_click` matched Refresh on every tick and
recognition resets the clock. The guard detects a macro that has lost the screen, not
one that recognises something and makes no progress. That is a real gap, not a bug in
the implementation, and it needs a different signal to close.

---

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
