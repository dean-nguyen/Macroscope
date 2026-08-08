# Backlog

Epics and tasks. One list, kept small on purpose — most items need nothing more than
the line they occupy. A task gets a PRD (`docs/prd/`) only when someone could
reasonably build the wrong thing, and a spec (`docs/specs/`) only when the approach is
non-obvious.

Status: `todo` · `doing` · `done` · `blocked` · `dropped`

**Direction:** two editions. The **engine is fully open source** and unrestricted. The
**paid side is maintained per-game packs and support** — a pack is a `.wmbpack` file,
which `pack_store` already imports and exports, so selling one needs no code. The
open-source release comes first; revenue is a later concern.

---

## E1 — A stranger can configure this for their own application

The engine works. What is unproven is whether someone who did not write it can point
it at their own game or program and get a working macro. This is the epic that decides
whether the project is useful to anyone else, and everything a user touches lives here.

| # | Task | Status | Notes |
|---|---|---|---|
| E1.1 | Engine survives a half-captured pack | done | Missing templates degrade to no-match and are listed per run |
| E1.2 | Matching survives a different window size | done | Two-stage scale search; verified 0.5x–2x on a live window. Live use then showed the search was **never reached** in a real macro, because the ration was per window size and absent guard templates spent it first — fixed, and that is why the pack only ever worked at exactly the capture size |
| E1.3 | Thresholds and the WGC allowance set from measurement | done | `docs/prd/scoring-from-measurement.md` |
| E1.4 | All features work with no licence or tier | done | ~1550 lines of licensing removed |
| E1.5 | **Validate a template at capture time** | done | `engine/template_check.py`, shown by `gui/capture_review.py` from both capture paths. Counts the crop's matches on the screen it came from (measured, not guessed from its size) and cross-scores it against every template already captured at `0.80` — the threshold macros click at, so a reported collision is one the engine could actually make |
| E1.6 | **Warn on a crop that cannot work** | done | A crop below `im.MIN_NEEDLE_STD` is the one blocker: the dialog offers no way to save what the matcher will refuse. `tools/game_probe.py crop` prints the same findings, so the CLI is not held to a looser bar |
| E1.7 | Author macros without editing JSON | todo | The main barrier for a non-technical user. A recorder ("do it once, replay it") is the conventional answer |
| E1.8 | An onboarding path per application | todo | Pick window → record or capture → test → run |
| E1.9 | Move `match_report` into the app | done | The scoring moved to `engine/match_report.py` and the Inspector grew a **templates** tab, so the CLI and the app cannot drift. It is the project's most useful diagnostic — it found the discovery-ration bug, a threshold sitting inside its own template's score band, and two duplicate templates in three days — and it existed only for people who read the source. Scoring runs off the UI thread, and the diagnostics override is a context manager now so a report cannot leave macros paying for unlimited scale searches |
| E1.10 | The editor silently dropped `humanize` and `stall_timeout_ms` | done | `_collect_macro` built the dict from scratch, so any macro-level key the form does not show was deleted on save. It now carries through everything outside `_FORM_KEYS`. Giving the two fields their own controls is E1.13 |
| E1.11 | `stop` is unreachable from the action picker | done | It was in `_F` and in no `_GROUPS` row, so it never rendered — a control both pack macros depend on and a user could not add without editing JSON, in a tool whose claim is that you do not have to. `tests/test_editor_actions.py` now asserts every editable action is offered exactly once, so the whole class of defect is guarded rather than this one instance |
| E1.12 | `scroll` `amount` means different things in the two modes | done | Confirmed in `pyautogui._pyautogui_win._scroll`: it passes `clicks` to `mouse_event` as `dwData` unscaled, and Windows counts 120 per notch — so foreground `3` asked for 3/120 of a notch while background posted three real ones, and `3` was the editor's default. The runner multiplies for the foreground path; `amount` is notches everywhere now |
| E1.13 | Controls for `humanize` and `stall_timeout_ms` in the editor | todo | They round-trip now (E1.10) but are still hand-edited. Worth a row in the form once the wording is settled |
| E1.14 | `target_window` picked the wrong window | done | `"Onmyoji"` also matched a YouTube tab and a macro posted a click into the browser. Candidates are ranked now, and the picker records `target_class` because the class outlives the handle. Covered by `tests/test_window_resolution.py` |

## E2 — Behave safely by default

Unattended input automation can lose someone their account. These are the mechanisms
that make the tool honest about that, and they are generic rather than per-game.

| # | Task | Status | Notes |
|---|---|---|---|
| E2.1 | **Randomise timing and click position** | done | `engine/humanize.py`, covered by `tests/test_humanize.py`. Delays scatter by a *fraction* (±15%) rather than a fixed offset, so a short settle and a 2500 ms poll both stay sensible; clicks scatter by 3 px, capped at a quarter of the smaller side of the element **as matched** (`image_matcher.Match` carries that size — the file's size is wrong, since matching is scale-aware) and clamped inside the client area, because 3 px on a click at `xp: 0.999` left a 1280×720 client area 39 times out of 60. On by default — `"humanize": false` opts out. Scope is narrower than "timing": only `wait.ms` and `loop_delay_ms`, not `type.interval`, `poll_ms` or `click_delay`. Does **not** make automation undetectable; it removes the trivially obvious signature |
| E2.2 | **Stop on an unexpected screen** | done | A looping macro that spends `stall_timeout_ms` (default 5 min, `0` disables) *sending input* without recognising anything stops and logs why. Template-free, so it also catches disconnects, maintenance and a changed UI. The condition is "clicking blind", not "matching nothing": a macro that recognises nothing and clicks nothing is a watcher and is left alone, any kind of recognition counts (template, pixel, rect), and a macro with no recognising action is never guarded. Covered by `tests/test_humanize.py` |
| E2.3 | Session limits and breaks | todo | Cap unattended run length; pause rather than grind forever |
| E2.5 | The stall guard cannot see "recognises something, makes no progress" | todo | Measured: a Realm Raid run pressed Refresh 23 times in 10 minutes without refreshing anything, and the guard never fired because `find_and_click` matched Refresh on every tick. A real gap in what the guard can detect, not a bug in it. Needs a different signal — perhaps "the same recognition, repeatedly, with nothing else changing" |
| E2.6 | A macro whose outer guard never matches is a silent no-op | todo | Both raid macros wrap their body in "am I on the list screen", so a tick that fails that check sends no input — and the stall guard's condition is *clicking* blind, so nothing stops it. Safe (no unintended clicks) and visible in the log, but it will loop forever without a word in the UI. Wants a "this macro has done nothing at all for N minutes" notice, distinct from the stall stop |
| E2.4 | Document where the input method cannot work | done | `CLAUDE.md` — raw input, DirectInput, kernel anti-cheat |

## E3 — The project reads as a project

For an open-source repository the README is the product.

| # | Task | Status | Notes |
|---|---|---|---|
| E3.1 | Decide the project name | done | **Macroscope**. Repo stays `window-macro` — renaming it would break links for no gain. The old `YuhunBot` was game-specific, and "Bot" carried the wrong connotation |
| E3.2 | Rewrite `README.md` around the engine | done | Leads with what it does, then the five things a naive image-matching tool gets wrong, the first four tied to a measurement |
| E3.3 | Survive a high-DPI display | done | 6 screens verified by capture at 250% |
| E3.4 | Window Arranger tiles correctly across monitors | done | 8 defects incl. per-monitor DPI and size-locked windows |
| E3.5 | Scale widget-option `padx`/`pady` (~41 sites) | todo | Inner padding renders at ~1/2.5 of intent. Cosmetic, no clipping |
| E3.6 | Fix `tools/README.md` — `--title` must precede the subcommand | todo | The documented example does not run |

## E4 — Know when something breaks

| # | Task | Status | Notes |
|---|---|---|---|
| E4.1 | Tests independent of the developer's environment | done | The dev-override vars they isolated no longer exist |
| E4.2 | CI on every push and PR | done | Before this, tests only ran on a release tag |
| E4.3 | Probe tooling kept in the repo | done | `tools/` — capture, match report, UI capture |
| E4.4 | Cover `_list_windows` and the arranger's Win32 paths | todo | Needs real window handles; a CI-safe approach is not obvious yet |

## E5 — The Onmyoji example pack

Stays in the public repo. It is the worked example that shows the engine doing
something real, and it is what the engine was developed against.

| # | Task | Status | Notes |
|---|---|---|---|
| E5.1 | Capture the outstanding templates | todo | 7 of 13 left: captcha, level_up, inventory_full, no_attempts, guild_no_wins, reconnect_retry, wanted_quest_decline — all opportunistic, and all either stop-guards or interruptions to clear. Until they exist the macros run, they just do not stop or clear for the reason named. `defeat` was captured by losing a raid on purpose (0.997). `onmyoji_captcha.png` no longer gates safety (E2.2 stops on an unrecognised screen without it), so capture it for the *specific* log line rather than as the only backstop |
| E5.10 | A Wanted Quest invitation could derail a raid | done | An invitation from another player arrives over any screen. Nothing handled it: if it covered the list marker the macro clicked nothing and stalled silently (E2.6), and if it did not, a grid click could land on it — which on an invitation means accepting, taking the client into an activity these macros do not navigate back from. Cleared now by clicking a template that is positively the **decline** button, deliberately not through the generic dismiss path, because that presses the standard confirm scroll and on an invitation the standard confirm is *accept* — the same trap as "Challenge Again" on the defeat screen. `tests/test_pack_macros.py` fails if anyone routes it back through `dismiss()` |
| E5.8 | Ten macros were six copies of one | done | `awakening`, `exploration`, `orochi`, `soul-farming`, `bounty-seals` and `demon-sealing` were byte-identical in structure apart from one line choosing `out_of_stamina` or `no_attempts`. None navigated anywhere, so the file name was documentation of which screen to open first, and a sequential folder run of them was meaningless — the second would start on whatever screen the first left |
| E5.9 | The pack is Realm Raid only | done | Two macros, and they are the two that have been run against the live game end to end. Everything else was dropped rather than shipped unvalidated: the activity macros are three actions anyone can write in the editor in a minute, and `daily-signin` depended on a template that moves every time an event rotates. Took the template list from 17 to 12 and the outstanding captures from 10 to 7, all of them stop-guards |
| E5.7 | An existing install never receives the new raid macros | todo | `paths.seed_starter_macros` is first-run-only behind `.starter_seeded`, so an install from before today keeps the deleted `Onmyoji - Realm Raid.json` — the version that looked for the Attack button on a screen where it does not exist — and gets neither replacement. Needs a re-seed path, or at least a log line naming pack macros that are newer than what is installed |
| E5.2 | Run the pack against the live game, end to end | done | `docs/prd/pack-live-validation.md`. Eight defects, five of them in the engine, then seven clean cycles across both raid modes including a deliberate loss. The pack is now only what has been validated: the AP farms were dropped rather than shipped unrun (E5.9) |
| E5.3 | Decide what `signin_claim` should be | todo | Event-dependent; the button moves when events rotate |
| E5.4 | Realm Raid is two macros now | done | The Individual list is a fixed 3x3 grid with a Refresh button; the Guild list is a scrolling two-column member list with its own `Win(s)` counter and no Refresh. Generated by `packs/onmyoji/build_raid_macros.py`, because the target-selection chain nests one level per cell and hand-editing eleven levels is how a branch silently never runs |
| E5.5 | Validate the Guild raid live | done | Four full cycles, including a deliberate loss. `Win(s): n/6` counts wins **remaining**, not used — misreading that is why this was first recorded as blocked. Found two defects: `dismiss()` cleared the defeat screen by clicking blind into a panel whose buttons include "Challenge Again", and `reward_confirm`'s 0.76 threshold sat inside that template's own measured score band (0.737-0.940), working only because WGC subtracts 0.08 |
| E5.6 | Reach Guild members below the sixth | todo | Less urgent than it looked: the list **re-sorts** as guardians are defeated, so fresh targets rise into the visible six on their own. Still unknown whether PostMessage can scroll it |

---

## Open questions

Things genuinely not known, kept here so they are not mistaken for settled.

- **Can PostMessage scroll a list in Onmyoji?** Unresolved. The Event sidebar did not
  move under either a wheel event or a drag; on the mailbox the input closed the panel
  instead, so that measurement was invalid. Matters for any workflow needing a scroll.
- **Why do two instances of the same game behave differently?** One accepts any window
  size; the other enforces an aspect ratio of ~1.71 and a maximum height.
- **Does a GDI-captured template matched against a WGC frame behave like the
  measurement?** The 0.08 allowance was measured by cropping both from live captures,
  not from a template saved by the wizard and matched days later. Believed sufficient,
  not proven.
