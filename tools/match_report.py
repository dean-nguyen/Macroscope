"""Score every captured template against a live window.

Answers the question users and pack authors actually ask: "why doesn't my
template match?" — by showing what each one scores right now, where it landed,
and whether the position is plausible.

    python tools/match_report.py --title Onmyoji
    python tools/match_report.py --title Onmyoji --threshold 0.85 --pattern "onmyoji_*"

Read the numbers with two things in mind:

* Scores are remapped. image_matcher._cv_match returns (raw + 1) / 2, so a raw
  correlation of 0 shows as 0.50 and unrelated content sits near 0.70 — a
  threshold of 0.80 is looser than it looks. Both forms are printed.
* When WGC captured the frame, matching subtracts _WGC_THRESHOLD_OFFSET, so the
  effective floor is lower than the threshold you pass.

Measured on a live 2840x1600 client: a template that IS on screen scored 0.962
(raw 0.924), while absent ones reached 0.737 (raw 0.473). If everything you own
scores in the 0.70s, nothing is actually matching.
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
    hits = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            text = win32gui.GetWindowText(hwnd)
            if title_substring.lower() in text.lower():
                hits.append((hwnd, text))

    win32gui.EnumWindows(cb, None)
    if not hits:
        sys.exit(f"No visible window matching {title_substring!r}")
    return hits[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", default="Onmyoji")
    parser.add_argument("--threshold", type=float, default=0.90)
    parser.add_argument("--pattern", default="*.png")
    args = parser.parse_args()

    import cv2
    import numpy as np

    import engine.image_matcher as im
    from engine.paths import TEMPLATES_DIR

    hwnd, title = find_window(args.title)
    if win32gui.IsIconic(hwnd):
        sys.exit(f"{title!r} is minimised — no frames are produced while it is, "
                 f"so every template would report 'no match'")

    haystack = im._grab_haystack(hwnd, None)
    if haystack is None:
        sys.exit("could not capture the window")
    print(f"target {title!r}  haystack {haystack.shape[1]}x{haystack.shape[0]}")
    print(f"threshold {args.threshold} "
          f"(effective {args.threshold - im._WGC_THRESHOLD_OFFSET:.2f} if WGC captured)\n")

    templates = sorted(TEMPLATES_DIR.glob(args.pattern))
    if not templates:
        sys.exit(f"no templates matching {args.pattern!r} in {TEMPLATES_DIR}")

    print(f"{'template':<36} {'std':>6} {'score':>7} {'raw':>7}  where")
    print("-" * 78)
    matched = 0
    for path in templates:
        std = float(cv2.imread(str(path)).std())
        try:
            result = im.find_template(f"templates/{path.name}", hwnd=hwnd,
                                      threshold=args.threshold)
        except im.TemplateUnusable as exc:
            print(f"{path.name:<36} {std:6.1f} {'—':>7} {'—':>7}  REFUSED: flat/featureless")
            continue
        except im.TemplateMissing:
            print(f"{path.name:<36} {'—':>6} {'—':>7} {'—':>7}  missing on disk")
            continue

        if result:
            cx, cy, score = result
            matched += 1
            print(f"{path.name:<36} {std:6.1f} {score:7.3f} {score * 2 - 1:7.3f}"
                  f"  ({cx},{cy})")
        else:
            print(f"{path.name:<36} {std:6.1f} {'-':>7} {'-':>7}  no match")

    print(f"\n{matched}/{len(templates)} matched on the screen that is up right now.")
    print("Only templates whose element is actually visible should match. If one "
          "matches while its element is off-screen, the crop is not distinctive "
          "enough — Onmyoji reuses one button chrome, and a plain 'OK' was "
          "measured scoring 0.91 against a completely different button.")


if __name__ == "__main__":
    main()
