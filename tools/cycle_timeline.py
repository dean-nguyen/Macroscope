"""Post one click, then log which templates are visible over time.

Built for the question "why is the wait after a win so long?". The post-attack chain
carries three settles — 2500 ms before checking whether the attack took, then 1500 ms
and 1000 ms between the taps that clear the result — and not one of them was ever
measured. Its own docstring says only "long enough for the click to register".

Measuring them one at a time would cost one raid attempt each. This costs one: click
Attack, then watch every marker at once and read the phases off the timeline —
when the list marker disappears (the attack took), when "Tap to continue" appears
(the battle ended), how long after a tap the next overlay draws, when the list returns.

    python tools/cycle_timeline.py --position 0 --seconds 90 \
        --click 296,742 onmyoji_realmraid_refresh.png onmyoji_reward_confirm.png:0.70

Sampling is honest about its own cost: each full-frame search is ~200 ms at 1810x1020,
so N templates per sample means the interval cannot be shorter than N x 200 ms, and the
printed timeline says what it actually achieved rather than what was asked for.

Nothing is clicked except the one coordinate given, and --click may be omitted to watch
a cycle someone else is driving.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.game_probe import ensure_shown, find_window   # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("templates", nargs="+", help="markers to watch")
    ap.add_argument("--title", default="Onmyoji")
    ap.add_argument("--position", type=int, default=None,
                    help="which matching window, left to right (two clients share a title)")
    ap.add_argument("--click", default=None, metavar="X,Y",
                    help="client coords to click once before watching; omit to observe only")
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--interval", type=float, default=0.0,
                    help="target seconds between samples (0 = as fast as searching allows)")
    ap.add_argument("--threshold", type=float, default=0.8,
                    help="default for templates given without one")
    args = ap.parse_args(argv)

    from engine import background_input as bi, image_matcher as im

    hwnd, _title = find_window(args.title, args.position)
    ensure_shown(hwnd)
    # Per template, because one threshold for all of them is wrong and produces a
    # plausible answer. Measured: watching the raid list marker at 0.70 -- the number the
    # pack uses for the *tap line* -- reported the list as back for one sample on a screen
    # that was not the list at all. Unrelated content sits near 0.70 on this game, which is
    # exactly why `_clamp_score` stopped remapping scores.
    refs, thresholds = [], []
    for spec in args.templates:
        name, _, thr = spec.partition(":")
        refs.append(name if "/" in name else f"templates/{name}")
        thresholds.append(float(thr) if thr else args.threshold)
    labels = [f"{Path(r).stem.replace('onmyoji_', '')}@{th:g}"
              for r, th in zip(refs, thresholds)]

    # Warm the window's scale on a marker that is on screen now, or the first samples
    # measure scale discovery (~2.8 s at this size) instead of the game. See
    # game_probe.cmd_settle, which learned this the hard way.
    im.clear_scale_cache()
    warm = time.time()
    warmed = [l for l, r, th in zip(labels, refs, thresholds)
              if im.find_template(r, hwnd=hwnd, threshold=th)]
    print(f"warmed in {(time.time() - warm) * 1000:.0f} ms; visible now: "
          f"{', '.join(warmed) or 'none'}")
    if not warmed:
        print("  nothing was visible, so nothing cached — the first samples will be slow")

    if args.click:
        x, y = (int(v) for v in args.click.split(","))
        bi.post_click(hwnd, x, y)
        print(f"clicked ({x},{y})")

    start = time.time()
    rows, previous = [], None
    while (elapsed := time.time() - start) < args.seconds:
        state = tuple(bool(im.find_template(r, hwnd=hwnd, threshold=th))
                      for r, th in zip(refs, thresholds))
        if state != previous:
            rows.append((elapsed, state, time.time() - start - elapsed))
            previous = state
        if args.interval:
            time.sleep(max(0.0, args.interval - (time.time() - start - elapsed)))

    width = max(len(l) for l in labels)
    print(f"\n{'t (ms)':>9}  " + "  ".join(l.rjust(width) for l in labels))
    print(f"{'':>9}  " + "  ".join("-" * width for _ in labels))
    for elapsed, state, _cost in rows:
        cells = ["YES".rjust(width) if v else ".".rjust(width) for v in state]
        print(f"{elapsed * 1000:9.0f}  " + "  ".join(cells))
    print(f"\n{len(rows)} state changes over {args.seconds:.0f}s. Every row is a phase "
          f"boundary; the gaps between them are what the settles have to cover.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
