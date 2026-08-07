# Macroscope

**Windows UI automation that watches the screen and drives a window.** Point it at an
application, tell it what to look for, and it clicks — optionally without ever moving
your mouse or bringing the window to the front.

Written in Python, MIT licensed, Windows only.

```bash
pip install -r requirements.txt
python main.py
```

---

## What it actually does

A macro is a list of actions in JSON. Actions can move and click, type, wait — or
look at the screen and branch on what they find:

```json
{
  "name": "Claim the daily reward",
  "background": true,
  "target_window": "Some Game",
  "loop": true,
  "loop_delay_ms": 2500,
  "actions": [
    { "type": "image_check", "template": "templates/captcha.png",
      "threshold": 0.70, "on_found": [ { "type": "stop" } ] },
    { "type": "find_and_click", "template": "templates/claim.png",
      "threshold": 0.80, "on_found": [ { "type": "wait", "ms": 1200 } ] },
    { "type": "click", "xp": 0.5, "yp": 0.9 }
  ]
}
```

`templates/claim.png` is a screenshot of the button, cropped in the app. The engine
finds it on screen and clicks inside it.

## What makes it more than a click recorder

Six things this handles that a naive image-matching macro tool does not. Most were
found by measuring on a live application, and those measurements are written down in
`CLAUDE.md`.

**It survives the window being resized.** A template captured at 2840×1600 still
matches at 1280×720. The engine searches for the scale factor once — coarse ladder for
the neighbourhood, fine pass for the value — then caches it per window size. A single
ladder fine enough to satisfy matching would need ~75 full comparisons and stall for
19 seconds; the two-stage search needs ~21.

**It captures windows that are covered.** Screen-grabbing photographs whatever is on
top, which produces plausible screenshots of the wrong window. `wgc_capture.py` reads
the window's own frames through Windows.Graphics.Capture, so the target can sit behind
your editor, and it works on DirectX applications and Android emulators.

**It types and clicks without taking over your machine.** In background mode,
`background_input.py` posts input to the window with `PostMessage` — the real cursor
never moves and you keep using the PC. (This cannot reach applications that read raw
input or DirectInput; `CLAUDE.md` says where the line falls and why.)

**One screenshot per iteration, not one per check.** Every image check in a tick shares
a single capture. That is cheaper, but mostly it is *correct*: on an animated screen
two captures taken milliseconds apart are not the same image, and checks that
disagreed about what was on screen produced real bugs.

**It stops when it is clicking at a screen it cannot read.** If a looping macro spends
five minutes sending input without recognising anything it looks for, it stops and says
so. That is deliberately generic: it catches a verification prompt, a disconnect,
maintenance downtime *and* the application changing its UI — none of which needs a
template, and the last of which no template could have anticipated. A macro that
recognises nothing but also clicks nothing is a watcher waiting for something to
appear, and is left alone.

**It tells you a capture is bad while you can still fix it.** When you crop a
template, it is checked before it is saved — against the same screen grab it came
from, and against every template you have already captured. A featureless crop is
refused outright, because normalised correlation divides by the variation in the
image and a flat crop matches anywhere. A crop that appears more than once on its own
screen is flagged, because `find_and_click` clicks the single best match and which of
five identical buttons that is is not something the macro controls. And a crop that
scores above 0.80 against a template you already have is flagged, because at the
threshold macros click at, the engine cannot tell them apart however different they
look to you — a plain `OK` button was measured at 0.91 against a completely different
button on the same screen.

An uncaptured template degrades to "not found" and is listed at the start of every
run, instead of aborting the macro.

Timing and click positions are scattered rather than identical: `wait` delays and the
loop delay vary by ±15%, and a click lands a few pixels off the centre of the matched
element rather than always on the exact centre pixel — bounded by the size the element
*matched* at, and clamped so it cannot leave the window. Set `"humanize": false` on a
macro that must hit an exact pixel. Other intervals — keystroke gaps, poll periods —
are used exactly as written; see `docs/SCHEMA.md`.

## Getting a macro working

1. **Pick the window.** The editor's window picker shows a live preview of each one.
2. **Capture what to look for.** Editor → Capture Region, or Images → Guided capture…
   to walk a whole list. Crop tightly, and crop *distinctive* content. Both paths
   check the crop before saving it and say what is wrong, so you do not have to know
   this in advance.
3. **Write the actions,** or start from a pack.
4. **Run it.** The log shows every check, its score, and where it matched.

Diagnosing a template that will not match:

```bash
python tools/match_report.py --title "Some Game"
```

It scores every template you have captured against the window as it is right now. A
present template scores around 0.92; absent ones reach about 0.47. If everything you
own scores in the 0.40s, nothing is matching.

## Packs

A pack is a folder of macros plus the list of templates they need, exportable as a
single `.wmbpack` file — how you share a working setup with someone else. Templates
themselves are per-machine, so a pack ships the *spec* and the recipient captures
their own; the Guided Capture wizard walks that list.

`packs/onmyoji/` is the worked example the engine was developed against.

## Layout

```
engine/
  image_matcher.py     template matching, scale search, per-tick frame sharing
  action_runner.py     one function per action type
  macro_engine.py      loads, validates and runs macros on background threads
  background_input.py  PostMessage input — no cursor movement
  wgc_capture.py       Windows.Graphics.Capture — reads occluded windows
  rect_detector.py     contour-based rectangle detection
  pack_store.py        .wmbpack import / export
  template_check.py    judges a crop before it is saved
gui/                   tkinter app: macro list, editor, capture wizard, arranger
tools/                 developer probes — see tools/README.md
docs/SCHEMA.md         every macro field and action, with its real default
docs/                  backlog and PRDs
CLAUDE.md              engine behaviour, and the measurements behind it
```

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest tests/          # 120 tests
python tools/import_check.py     # what CI also runs
```

`tools/` holds the probes this was built with: capture a window, crop a template,
score every template against a live screen, capture the app's own UI. `tools/README.md`
records the traps they encode — most of them cost real debugging time to find.

**Read `CLAUDE.md` before changing the matcher.** It documents why the constants are
what they are, and two approaches that were tried, measured and removed. In
particular: do not add a downscaling pre-filter. One was, and it silently vetoed real
matches, because shrinking both images only works when the element happens to sit on
the sampling grid.

## Using this responsibly

This automates input to other people's software. Some of that software forbids it, and
some publishers ban accounts for it. Automating a game you play is your decision and
your risk — but a few things are not judgement calls:

- It will not defeat kernel anti-cheat (Vanguard, EAC, BattlEye). Posted input does not
  reach those, and attempting it risks the account of whoever runs it.
- Timing and click positions are scattered, but **that is not the same as being
  undetectable** and nothing here should be read as claiming it. It removes the
  trivially obvious signature — a perfect metronome hitting one pixel — and no more.
- The stall guard stops a macro that has lost track of the screen, but it is a
  backstop, not supervision. Automating something unattended for hours is your risk.
- If an application shows you a verification prompt, stop. Do not automate through it.

## License

MIT — see [LICENSE](LICENSE).
