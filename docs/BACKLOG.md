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

## E2 — Behave safely by default

Unattended input automation can lose someone their account. These are the mechanisms
that make the tool honest about that, and they are generic rather than per-game.

| # | Task | Status | Notes |
|---|---|---|---|
| E2.1 | **Randomise timing and click position** | todo | There is **none**: every delay is a fixed constant (`wait 1200` appears 50 times) and every click lands on the exact template centre. Metronomic and pixel-identical |
| E2.2 | **Stop on an unexpected screen** | todo | If a macro expects progress and nothing expected matches for N ticks, stop. Template-free, so it catches verification prompts, maintenance, disconnects *and* a UI change — where a per-game CAPTCHA template catches one of those and only if the user could capture it |
| E2.3 | Session limits and breaks | todo | Cap unattended run length; pause rather than grind forever |
| E2.4 | Document where the input method cannot work | done | `CLAUDE.md` — raw input, DirectInput, kernel anti-cheat |

## E3 — The project reads as a project

For an open-source repository the README is the product.

| # | Task | Status | Notes |
|---|---|---|---|
| E3.1 | Decide the project name | todo | `YuhunBot` is the old game-specific brand; "Bot" also carries the wrong connotation |
| E3.2 | Rewrite `README.md` around the engine | blocked on E3.1 | Currently reads as a sales page |
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
| E5.1 | Capture the 9 outstanding templates | todo | `onmyoji_captcha.png` first — the anti-ban guard is inert without it. Superseded in part by E2.2 |
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
