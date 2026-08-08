"""Score every captured template against a live window, from the command line.

    python tools/match_report.py --title Onmyoji
    python tools/match_report.py --title Onmyoji --threshold 0.85 --pattern "onmyoji_*"

The scoring itself lives in `engine/match_report.py`, so this and the app's
Templates tab cannot drift apart — the CLI existing alone is what made this
diagnostic invisible to everyone who did not read the source.

Scores are raw TM_CCOEFF_NORMED with anticorrelation floored at 0, so the number
means what it says. Measured on a live game window: a template that IS on screen
scores ~0.92, and absent ones reach ~0.47. If everything you own scores in the
0.40s, nothing is actually matching.

One adjustment still applies: when WGC captured the frame, matching subtracts
_WGC_THRESHOLD_OFFSET to allow for the colour difference against a GDI-sourced
template, so the effective floor is a little below the threshold you pass.
"""

import ctypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:                                        # pragma: no cover
    pass

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import win32gui


def find_window(title_substring: str):
    from engine.background_input import find_all_windows

    hits = find_all_windows(title_substring)
    if not hits:
        sys.exit(f"No visible window matching {title_substring!r}")
    if len(hits) > 1:
        print(f"{len(hits)} windows match {title_substring!r}; using "
              f"{hits[0][1]!r}. Others: "
              + ", ".join(repr(t) for _h, t in hits[1:4]))
    return hits[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", default="Onmyoji")
    parser.add_argument("--threshold", type=float, default=0.80)
    parser.add_argument("--pattern", default="*.png")
    args = parser.parse_args()

    from engine import match_report as mr

    hwnd, title = find_window(args.title)
    try:
        report = mr.score_templates(hwnd, threshold=args.threshold,
                                    pattern=args.pattern, title=title)
    except mr.ReportError as exc:
        sys.exit(str(exc))

    print(f"target {report.title!r}  "
          f"haystack {report.haystack[0]}x{report.haystack[1]}")
    print(f"threshold {report.threshold} "
          f"(effective {report.effective:.2f} if WGC captured)\n")

    print(f"{'template':<36} {'std':>6} {'score':>7}  where")
    print("-" * 70)
    for row in report.rows:
        std = f"{row.std:6.1f}" if row.std is not None else f"{'—':>6}"
        if row.matched:
            print(f"{row.name:<36} {std} {row.score:7.3f}  ({row.at[0]},{row.at[1]})")
        elif row.status == mr.NO_MATCH:
            print(f"{row.name:<36} {std} {'-':>7}  no match")
        else:
            print(f"{row.name:<36} {std} {'—':>7}  {row.status.upper()}: {row.note}")

    print(f"\n{report.summary}.")
    print(mr.ADVICE)


if __name__ == "__main__":
    main()
