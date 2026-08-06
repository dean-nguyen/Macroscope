# Project Handoff / Status

Snapshot of where this project stands and how to continue — so a fresh machine
(or a fresh Claude session) has full context from a `git pull`.

_Last updated: 2026-08-06._

## What this project is

A **Windows UI-automation engine** — image/pixel matching, background input via
PostMessage, DPI-correct window capture via WGC — with per-application macro packs
layered on top. Onmyoji is the example pack it was developed against.

**Direction as of 2026-08-06: two editions, open source first.**

- The **engine is fully open source** (MIT). Every feature works: background mode,
  image/pixel/rect detection, loops, multi-window parallel runs. There is no tier.
- The **paid side is maintained per-game packs and support** — a pack is a
  `.wmbpack` file, which `engine/pack_store.py` already imports and exports, so
  selling one needs no code. Recurring revenue matches the recurring cost, which is
  re-capturing templates whenever a game patches its UI.
- Releasing the open-source edition comes first; revenue is a later concern.

This supersedes the freemium plan. The licensing, entitlement and KeyAuth machinery
was removed on 2026-08-06 — about 1550 lines, plus 33 tests — along with
`GO-COMMERCIAL.md`, `marketing/` and `legal/`. All of it is recoverable from git
history if the split ever moves to paid *features* instead of paid packs.

The one part of that material worth keeping was not commercial at all: **where this
input method architecturally cannot work.** It now lives in `CLAUDE.md`.

## Where things live

| Area | Path |
|------|------|
| Engine | `engine/` — `image_matcher`, `action_runner`, `macro_engine`, `wgc_capture`, `background_input` |
| Macro packs | `engine/pack_store.py`, `packs/` |
| Onmyoji pack | `packs/onmyoji/` (macros + `templates.spec.json` + `CAPTURE-GUIDE.md`) |
| Guided capture | `gui/capture_wizard.py` |
| Developer probes | `tools/` — capture a window, score templates, capture the UI |
| Engine behaviour notes | `CLAUDE.md` — read this before touching the matcher |
| Backlog and PRDs | `docs/` |

## Remaining work

Tracked in `docs/BACKLOG.md`; the two that matter most:

1. **Randomised timing and click jitter.** There is none — every delay is a fixed
   constant and every click lands on the exact template centre.
2. **Capture-time validation in the UI.** Score a new template against the screen
   *and against existing templates*, so a bad crop is caught while it is being made.
   A plain `OK` button was measured scoring 0.91 against a different button.

Owner tasks: capture the 9 outstanding Onmyoji templates, and run the pack against
the live game end to end (`docs/prd/pack-live-validation.md` — never done).

## Setting up on a new machine

```bash
pip install -r requirements-dev.txt      # runtime + test deps
python -m pytest tests/                   # sanity check (should be 102 passing)
python tools/import_check.py              # what CI also runs
python main.py                            # run the app
gh auth login                             # if using gh for PRs
```

- **No build secrets any more.** There is nothing to configure and no tier to
  unlock; run it from source or build it and everything works.
- **Captured templates** live next to the code (`templates/`) when running from
  source, and in `%APPDATA%/Macroscope/templates/` in a packaged build.
  Either way they are per-machine and do **not** travel with git — re-capture, or
  copy the folder across. `python tools/game_probe.py list <spec>` shows what is
  captured.

## Note on Claude context

Claude's auto-memory lives under `~/.claude/projects/.../memory/` and does **not**
travel with `git pull`. The durable context is this file, `CLAUDE.md` (engine
behaviour, and the measurement traps that produced it), `docs/`, and the commit
history — the commit messages deliberately record *why*, including theories that
measurement disproved. Point a fresh session at this file first.
