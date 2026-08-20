"""Run a pack macro against a saved frame and print exactly what it would click.

Real input is made impossible rather than merely unused: every `background_input.post_*`
records instead of sending, `pyautogui` raises on any attribute access, and a full-screen
grab raises too — because a *silent* full-screen grab is what went wrong the first time
this was written. A hand-made ctx without `background` sends `_search_hwnd` down the
no-window path, so the macro searched the developer's desktop, found nothing, and
reported the gate as absent. The frame was fine and the template was fine.

So the ctx comes from `MacroEngine._build_ctx`, the same one a run uses, and the
screen-grab path is wired to explode.

    python tools/dryrun_macro.py .probe/frame.png packs/onmyoji/souls-sougenbi-foolery.macro.json

What it answers: on *this* screen, which templates does the macro see, and what does it
press? Cross a frame against every macro in a pack and you find out whether two macros
would fight over one screen — which is the question a live test cannot ask safely.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2   # noqa: E402

from engine import action_runner as ar, background_input as bg, image_matcher as im  # noqa: E402
from engine.macro_engine import MacroEngine  # noqa: E402

FAKE_HWND = 12345


def _seal(frame):
    """Make every route to the real machine raise or record."""
    sent = []
    im._capture_hwnd_cv = lambda hwnd: frame.copy()

    def no_screen_grab(*_a, **_k):
        raise AssertionError(
            "a full-screen grab means the window was never resolved — the ctx is wrong, "
            "not the template")
    im._capture_screen_cv = no_screen_grab

    for name in ("post_click", "post_double_click", "post_right_click", "post_move",
                 "post_drag", "post_scroll", "post_key", "post_type"):
        setattr(bg, name, (lambda n: (lambda *a, **k: sent.append((n, a[1:]))))(name))

    class Blocked:
        def __getattr__(self, name):
            raise AssertionError(f"pyautogui.{name} would have moved the real cursor")

        @staticmethod
        def size():
            return (1920, 1080)

    ar.pyautogui = Blocked()
    return sent


def _trace():
    seen = []
    original = im.find_template

    def traced(path, **kw):
        result = original(path, **kw)
        seen.append((os.path.basename(str(path)), kw.get("threshold"), result))
        return result

    im.find_template = traced
    return seen


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("frame", type=Path, help="a saved screenshot of the target window")
    ap.add_argument("macro", type=Path, help="a *.macro.json to run against it")
    ap.add_argument("--quiet", action="store_true",
                    help="only the templates that matched, and the input")
    args = ap.parse_args(argv)

    frame = cv2.imread(str(args.frame))
    if frame is None:
        print(f"could not read {args.frame}", file=sys.stderr)
        return 2
    macro = json.loads(args.macro.read_text(encoding="utf-8"))

    sent = _seal(frame)
    seen = _trace()

    height, width = frame.shape[:2]
    ctx = MacroEngine(log_fn=lambda *a, **k: None)._build_ctx(macro)
    ctx.update({"hwnd": FAKE_HWND, "anchor_hwnd": FAKE_HWND,
                "client_w": width, "client_h": height,
                "offset_x": 0, "offset_y": 0, "humanize": False})

    def run_actions(actions):
        for action in actions:
            ar.run_action(action, run_actions, ctx)

    im.begin_frame_scope()
    try:
        run_actions(macro["actions"])
    finally:
        im.end_frame_scope()

    print(f"{args.frame.name} × {macro['name']}")
    print(f"  window {width}x{height}, background={ctx.get('background')}")
    for name, threshold, result in seen:
        if result:
            print(f"  {name:<40} thr {threshold}  MATCH ({result[0]},{result[1]}) "
                  f"score {result[2]:.3f}")
        elif not args.quiet:
            print(f"  {name:<40} thr {threshold}  no match")
    print(f"  input it would send: {len(sent)}")
    for name, params in sent:
        print(f"    {name}{params}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
