# tools/

Developer probes. Not shipped, not imported by the app — they exist because the
things that break in this project only show up when you point a camera at a real
window, and doing that by hand is slow.

Output goes to `.probe/` at the repo root (git-ignored).

| Tool | What it is for |
|---|---|
| `import_check.py` | Import every `engine`/`gui` module and fail if any can't. The GUI has no test coverage, so this is what catches a stale import or syntax error there. Runs in CI. |
| `game_probe.py` | Look at a target window, measure a button, crop it into a template, click something, watch a sequence. The capture→crop→verify loop for authoring a pack. |
| `match_report.py` | Score every captured template against the window that is up right now. Answers "why doesn't my template match?". |
| `ui_probe.py` | Show one of the app's own windows and capture it, to check the UI renders. |
| `build_pack.py` | Assemble a pack's `.wmbpack` from `packs/<name>/` for people to download. `release.yml` runs it. |

## Quick start

`--title` belongs to `game_probe.py` itself, not to its subcommands, so it goes
**before** the subcommand. Put it after and argparse rejects the line.

```bash
python tools/import_check.py                                    # what CI runs
python tools/game_probe.py --title Onmyoji shot                 # -> .probe/frame.png
python tools/game_probe.py --title Onmyoji peek 2240 1300 420 130 --scale 2
python tools/game_probe.py --title Onmyoji crop onmyoji_battle_ready.png 2240 1300 420 130
python tools/game_probe.py list packs/onmyoji/templates.spec.json
python tools/match_report.py --title Onmyoji                    # --title is its own here
python tools/ui_probe.py app editor wizard
python tools/build_pack.py onmyoji                              # -> .probe/Onmyoji.wmbpack
python tools/build_pack.py onmyoji --templates templates        # from a capture session
```

`build_pack.py` is the exception to "not shipped": `release.yml` runs it, so its exit
codes are a contract. **3** means the pack has no captured images yet — not a failure,
but nothing worth publishing, so the release skips it. Anything else non-zero stops the
release.

## Things these encode, learned the hard way

Each of these cost real debugging time, so they are worth knowing before you
write your own probe.

**Capture with WGC, never a screen grab.** A screen grab photographs whatever is
on top of the target rectangle. Aim it at a window sitting behind your editor and
you get a perfectly plausible screenshot — of your editor. WGC reads the window's
own frames, so occlusion does not matter, and it is the backend macros use at run
time, so crops match what matching sees.

**A minimised window produces no frames.** Some clients minimise themselves.
WGC then returns nothing, every image check silently misses, and a macro loops
forever doing nothing. `game_probe.ensure_shown` restores with
`SW_SHOWNOACTIVATE` so your focus is not stolen.

**Set DPI awareness before reading any geometry.** Otherwise win32 and PIL
disagree about what a pixel is on a scaled display, and every coordinate is
subtly wrong.

**A big pixel diff is not proof of what you think.** Measuring "did the list
scroll?" by frame difference reported a large change — which turned out to be the
panel *closing*. Check *what* changed, not just that something did.

**Flat crops match everywhere.** `TM_CCOEFF_NORMED` divides by the template's
standard deviation, so a crop of an empty panel or a solid button fill correlates
perfectly with anything. `game_probe crop` warns when a crop is too flat, and the
matcher refuses such templates outright.

**Match scores are remapped.** `(raw + 1) / 2`, so raw 0 reads as 0.50 and
unrelated content sits near 0.70. A threshold of `0.80` is far looser than it
looks. `match_report.py` prints both forms.

**Similar chrome beats short text.** Onmyoji reuses one button style everywhere;
a crop of the plain `OK` button scored **0.91 against a completely different
button**. Crop distinctive content — words, banners, icons — never a bare button.
