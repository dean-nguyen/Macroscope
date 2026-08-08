# Packs

Ready-made macros plus the template images they match against, so there is nothing to
capture before the first run.

**[Download from the latest release](https://github.com/dean-nguyen/Macroscope/releases/latest)** —
grab the `.wmbpack`, open Macroscope, and click **Import** in the sidebar.

| Pack | Game | Macros | Templates | Size |
|---|---|---|---|---|
| `Onmyoji.wmbpack` | Onmyoji (English Steam client) | Realm Raid (Individual), Realm Raid (Guild) | 6 of 13 | 89 KB |

The packs are release assets rather than files in this repository, so a pack can grow
with its template set without every image landing in the history twice — the images are
already versioned under `packs/<name>/templates/`, which is what the release builds
from.

Importing never overwrites: a macro or image whose name is already taken is imported
under a new one, and the macro's references are rewritten to match.

## Read this before you trust the images

**The templates may not match on your client, and it is not a matter of tuning.**

Measured on two clients of this game running on one machine, differing only in their
in-game graphics settings: the second rendered about 35% softer, and that alone took a
marker template from **1.000** on one client to **0.697** on the other — below the
0.72 the macro needs. Same coordinates, same content. Neither brightness nor a
one-pixel size difference explained it, and cropping a bigger region made it *worse*.

Window **size** is not the problem — matching is scale-aware, and a template captured
at 2840×1600 has been verified matching at 0.44×. Rendering is.

So treat the shipped images as a starting point, and check them:

**In the app:** Images → the match report tab scores every template against the window
that is up right now.

**From source:** `python tools/match_report.py --title Onmyoji` — it names the window
it scored, which matters when you run two clients.

A template whose element is on screen scores **~0.92–0.99**. Absent ones reach about
**0.47**. If everything scores in the 0.40s, nothing is matching — re-capture with
Images → **Guided capture…**, which walks the same list and checks each crop as you
take it.

## What this pack does not include

Seven of the thirteen templates are states that cannot be summoned on demand — a
CAPTCHA, a disconnect, a full inventory — so nobody has a clean capture of them to
ship:

`onmyoji_captcha.png` · `onmyoji_guild_no_wins.png` · `onmyoji_inventory_full.png` ·
`onmyoji_level_up.png` · `onmyoji_no_attempts.png` · `onmyoji_reconnect_retry.png` ·
`onmyoji_wanted_quest_decline.png`

The macros run without them. Each one is a **stop-guard or an interruption handler**,
so what you lose is the macro stopping for that specific reason — not the raid itself.
The log lists what is missing at the start of every run, and the engine's stall guard
still stops a macro that clicks without recognising anything for five minutes.

Grab them with Guided capture the first time you ever see one. `onmyoji_captcha.png`
is the one worth waiting for.

## Building a pack yourself

```bash
python tools/build_pack.py onmyoji                          # -> .probe/Onmyoji.wmbpack
python tools/build_pack.py onmyoji --templates templates    # from a capture session
```

It builds from `packs/onmyoji/*.macro.json` and `packs/onmyoji/templates/` — the
versioned source, which is also what `release.yml` runs against. Your own `templates/`
is git-ignored, so a CI checkout has no images unless they live in the pack.

It deliberately does **not** export your own library. Macros you have been running
carry `target_hwnd` and `target_position`, which name a window on *your* machine.
`target_position` is the dangerous one: the engine checks it before anything else, so
it would silently point someone else's macro at whichever of their windows sits in that
spot. The builder strips both and fails if either survives into the zip.

Exit **3** means the pack has no captured images yet — not a failure, but nothing worth
publishing, so the release skips it and deletes the file. That is the state
`summoners-war` is in: without it, a release would carry a 0.8 KB pack that does
nothing on import.

## Publishing a new pack version

Push a `v*` tag. `release.yml` runs the tests, builds the `.exe`, then builds every
pack that has captured images and attaches them to the release.

To update just the images, re-capture into `packs/<name>/templates/` and tag again.
