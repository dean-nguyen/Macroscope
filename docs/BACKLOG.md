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
| E1.2 | Matching survives a different window size | done | Two-stage scale search; verified 0.5x–2x on a live window |
| E1.3 | Thresholds and the WGC allowance set from measurement | done | `docs/prd/scoring-from-measurement.md` |
| E1.4 | All features work with no licence or tier | done | ~1550 lines of licensing removed |
| E1.5 | **Validate a template at capture time** | todo | Score it against the screen *and against existing templates*, in the wizard. Would have caught a plain `OK` scoring 0.91 against a different button. The single highest-value UX item |
| E1.6 | **Warn on a crop that cannot work** | todo | Flat crops already raise `TemplateUnusable` in the engine — the wizard must say so while the user is still cropping |
| E1.7 | Author macros without editing JSON | todo | The main barrier for a non-technical user. A recorder ("do it once, replay it") is the conventional answer |
| E1.8 | An onboarding path per application | todo | Pick window → record or capture → test → run |
| E1.9 | Move `match_report` into the app | todo | "Why doesn't my template match?" is currently answerable only from a CLI in `tools/` |
| E1.10 | The editor silently dropped `humanize` and `stall_timeout_ms` | done | `_collect_macro` built the dict from scratch, so any macro-level key the form does not show was deleted on save. It now carries through everything outside `_FORM_KEYS`. Giving the two fields their own controls is E1.13 |
| E1.13 | Controls for `humanize` and `stall_timeout_ms` in the editor | todo | They round-trip now (E1.10) but are still hand-edited. Worth a row in the form once the wording is settled |
| E1.11 | `stop` is unreachable from the action picker | todo | It is in `_F` but not in any `_GROUPS` row, so it never renders. Every shipped pack uses it, but a user writing their own macro cannot add it without editing JSON |
| E1.12 | `scroll` `amount` means different things in the two modes | todo | Background posts `amount * WHEEL_DELTA` (3 = three notches); foreground hands `amount` to `pyautogui.scroll`, which passes it to `mouse_event` as a raw delta where a notch is 120 — so the editor's default of `3` is 3/120 of a notch and does nothing. Read from the code, not yet measured against an application |

## E2 — Behave safely by default

Unattended input automation can lose someone their account. These are the mechanisms
that make the tool honest about that, and they are generic rather than per-game.

| # | Task | Status | Notes |
|---|---|---|---|
| E2.1 | **Randomise timing and click position** | done | `engine/humanize.py`, covered by `tests/test_humanize.py`. Delays scatter by a *fraction* (±15%) rather than a fixed offset, so a short settle and a 2500 ms poll both stay sensible; clicks scatter by 3 px, capped at a quarter of the smaller side of the element **as matched** (`image_matcher.Match` carries that size — the file's size is wrong, since matching is scale-aware) and clamped inside the client area, because 3 px on a click at `xp: 0.999` left a 1280×720 client area 39 times out of 60. On by default — `"humanize": false` opts out. Scope is narrower than "timing": only `wait.ms` and `loop_delay_ms`, not `type.interval`, `poll_ms` or `click_delay`. Does **not** make automation undetectable; it removes the trivially obvious signature |
| E2.2 | **Stop on an unexpected screen** | done | A looping macro that spends `stall_timeout_ms` (default 5 min, `0` disables) *sending input* without recognising anything stops and logs why. Template-free, so it also catches disconnects, maintenance and a changed UI. The condition is "clicking blind", not "matching nothing": a macro that recognises nothing and clicks nothing is a watcher and is left alone, any kind of recognition counts (template, pixel, rect), and a macro with no recognising action is never guarded. Covered by `tests/test_humanize.py` |
| E2.3 | Session limits and breaks | todo | Cap unattended run length; pause rather than grind forever |
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
| E5.1 | Capture the 9 outstanding templates | todo | `onmyoji_captcha.png` no longer gates safety — E2.2 stops on an unrecognised screen without it. Capture it for the *specific* log line, not as the only backstop |
| E5.2 | Run the pack against the live game, end to end | todo | `docs/prd/pack-live-validation.md`. Never done |
| E5.3 | Decide what `signin_claim` should be | todo | Event-dependent; the button moves when events rotate |

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
