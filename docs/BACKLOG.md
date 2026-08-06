# Backlog

Epics and tasks for YuhunBot. One list, kept small on purpose — most items need
nothing more than the line they occupy. A task gets a PRD (`docs/prd/`) only when
someone could reasonably build the wrong thing, and a spec (`docs/specs/`) only when
the approach is non-obvious.

Status: `todo` · `doing` · `done` · `blocked` · `dropped`

---

## E1 — Ship a pack that works on a buyer's machine

The engine is in good shape; what is unproven is the pack running end to end on
someone else's screen. This epic is the launch gate.

| # | Task | Status | Notes |
|---|---|---|---|
| E1.1 | Engine survives a half-captured pack | done | Missing templates degrade to no-match and are listed per run |
| E1.2 | Matching survives a different window size | done | Two-stage scale search; verified 0.5x–2x on a live window |
| E1.3 | Thresholds and the WGC allowance set from measurement | done | Raw correlation; see `docs/prd/scoring-from-measurement.md` |
| E1.4 | **Run the pack against the live game, end to end** | todo | `docs/prd/pack-live-validation.md`. The largest remaining unknown |
| E1.5 | Capture the 9 outstanding Onmyoji templates | todo | `onmyoji_captcha.png` first — the anti-ban guard is inert without it |
| E1.6 | Decide what `signin_claim` should be | todo | Event-dependent; the button moves when events rotate |

## E2 — The app looks and behaves like a product

| # | Task | Status | Notes |
|---|---|---|---|
| E2.1 | Survive a high-DPI display | done | 6 screens verified by capture at 250% |
| E2.2 | Window Arranger tiles correctly across monitors | done | 8 defects; incl. per-monitor DPI and size-locked windows |
| E2.3 | Scale widget-option `padx`/`pady` (~41 sites) | todo | Inner padding renders at ~1/2.5 of intent. Cosmetic, no clipping |
| E2.4 | Fix `tools/README.md` — `--title` must precede the subcommand | todo | The documented example does not run |

## E3 — Know when something breaks

| # | Task | Status | Notes |
|---|---|---|---|
| E3.1 | Tests independent of the developer's environment | done | `tests/conftest.py` clears local overrides |
| E3.2 | CI on every push and PR | done | Before this, tests only ran on a release tag |
| E3.3 | Probe tooling kept in the repo | done | `tools/` — capture, match report, UI capture |
| E3.4 | Cover `_list_windows` and the arranger's Win32 paths | todo | Needs real window handles; a CI-safe approach is not obvious yet |

## E4 — Commercial launch

Owner-only; tracked in `GO-COMMERCIAL.md`. Not startable until E1 closes.

| # | Task | Status |
|---|---|---|
| E4.1 | KeyAuth, Sellix and Discord accounts | todo |
| E4.2 | GitHub repo secrets for the release build | todo |
| E4.3 | Tag `v1.0.0` | blocked — E1.5, the anti-ban guard is inert |
| E4.4 | Code-signing certificate | todo (optional) |

---

## Open questions

Things genuinely not known, kept here so they are not mistaken for settled.

- **Can PostMessage scroll a list in Onmyoji?** Unresolved. The Event sidebar did not
  move under either a wheel event or a drag; on the mailbox the input closed the
  panel instead, so that measurement was invalid. Matters for any workflow that
  needs to scroll.
- **Why do the two Onmyoji instances behave differently?** One accepts any window
  size, the other enforces an aspect ratio of ~1.71 and a maximum height. Same title,
  same game.
