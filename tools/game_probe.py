"""Inspect and drive a target window from the command line.

Built while getting the Onmyoji pack working, because the loop you actually need
is: look at the window, measure a button, crop it into a template, click
something, look again. Doing that by hand through the GUI is far slower.

    python tools/game_probe.py shot --title Onmyoji
    python tools/game_probe.py peek 2240 1300 420 130 --scale 2
    python tools/game_probe.py crop onmyoji_battle_ready.png 2240 1300 420 130
    python tools/game_probe.py click 853 868 --wait 3
    python tools/game_probe.py watch 12 --interval 5
    python tools/game_probe.py list packs/onmyoji/templates.spec.json

Frames land in .probe/ (git-ignored). Coordinates are always CLIENT coordinates
of the target window, which is also what macros use.

Two traps this encodes, both of which cost real time to find:

* Capture via WGC, not a screen grab. A screen grab photographs whatever is
  on top of the target rectangle — point it at a window behind your editor and
  you get the editor. WGC reads the window's own frames, so it works while the
  window is covered, and it is the same backend macros use at run time, so crops
  taken here match what matching sees.

* Restore before capturing. Some clients (Onmyoji among them) minimise
  themselves; a minimised window produces no WGC frames at all, and every image
  check then silently misses. ensure_shown handles it with SW_SHOWNOACTIVATE so
  your own focus is left alone.
"""

# DPI awareness must be set before anything reads window geometry, or win32 and
# PIL disagree about what a pixel is on a scaled display.
import ctypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor v2
except Exception:                                        # pragma: no cover
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import win32con
import win32gui

OUT_DIR = ROOT / ".probe"
FRAME = OUT_DIR / "frame.png"
META = OUT_DIR / "frame.json"


# ── window handling ───────────────────────────────────────────────────────────

def find_window(title_substring: str):
    """First visible top-level window whose title contains *title_substring*."""
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


def client_bbox(hwnd):
    x0, y0 = win32gui.ClientToScreen(hwnd, (0, 0))
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    return x0, y0, x0 + (right - left), y0 + (bottom - top)


def ensure_shown(hwnd, timeout: float = 6.0):
    """Un-minimise the window and wait for a real client rect."""
    deadline = time.time() + timeout
    while True:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        bbox = client_bbox(hwnd)
        if bbox[2] - bbox[0] > 0 and bbox[3] - bbox[1] > 0 and bbox[0] > -30000:
            return bbox
        if time.time() > deadline:
            sys.exit(f"Window stayed minimised or degenerate: rect={bbox}")
        time.sleep(0.3)


# ── capture ───────────────────────────────────────────────────────────────────

def capture(title: str, quiet: bool = False):
    """Capture the target's client area as a PIL image."""
    import cv2
    from PIL import Image, ImageGrab

    hwnd, window_title = find_window(title)
    bbox = ensure_shown(hwnd)

    backend, img = "wgc", None
    try:
        from engine import wgc_capture
        if wgc_capture.is_available():
            frame = wgc_capture.get_frame(hwnd)
            if frame is not None and frame.size:
                img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    except Exception as exc:
        print(f"WGC unavailable ({exc}) — falling back to a screen grab")

    if img is None:
        backend = "gdi"
        if win32gui.GetForegroundWindow() != hwnd:
            print("WARNING: screen-grab fallback while the target is NOT the "
                  "foreground window — the frame may show whatever covers it")
        # Grab the whole desktop and crop: a bbox that clips the desktop edge
        # makes PIL write a corrupt tile ("tile cannot extend outside image").
        full = ImageGrab.grab(all_screens=True)
        vx = ctypes.windll.user32.GetSystemMetrics(76)
        vy = ctypes.windll.user32.GetSystemMetrics(77)
        img = full.crop((bbox[0] - vx, bbox[1] - vy, bbox[2] - vx, bbox[3] - vy))
        img.load()

    OUT_DIR.mkdir(exist_ok=True)
    img.save(FRAME)
    META.write_text(json.dumps({"hwnd": hwnd, "title": window_title,
                                "bbox": bbox, "size": img.size,
                                "backend": backend}))
    if not quiet:
        print(f"hwnd={hwnd} title={window_title!r} backend={backend}")
        print(f"client {img.size[0]}x{img.size[1]} at {bbox[:2]} -> {FRAME.relative_to(ROOT)}")
    return img


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_shot(args):
    capture(args.title)


def cmd_peek(args):
    """Crop a candidate box out of the last frame WITHOUT saving a template, so
    the box can be checked and adjusted first."""
    from PIL import Image
    if not FRAME.exists():
        sys.exit("no frame yet — run `shot` first")
    with Image.open(FRAME) as img:
        out = img.crop((args.x, args.y, args.x + args.w, args.y + args.h))
        if args.scale != 1:
            out = out.resize((int(args.w * args.scale), int(args.h * args.scale)),
                             Image.LANCZOS)
        dest = OUT_DIR / "peek.png"
        out.save(dest)
    print(f"peek {args.w}x{args.h} at ({args.x},{args.y}) scale={args.scale} "
          f"-> {dest.relative_to(ROOT)}")


def cmd_crop(args):
    """Save a region of the last frame as a real template."""
    from PIL import Image
    from engine.paths import TEMPLATES_DIR
    if not FRAME.exists():
        sys.exit("no frame yet — run `shot` first")
    with Image.open(FRAME) as img:
        W, H = img.size
        if (args.x < 0 or args.y < 0 or args.x + args.w > W
                or args.y + args.h > H or args.w <= 0 or args.h <= 0):
            sys.exit(f"box {(args.x, args.y, args.w, args.h)} outside frame {W}x{H}")
        out = img.crop((args.x, args.y, args.x + args.w, args.y + args.h))

        # The same checks the capture wizard runs, held to the same bar, so a template
        # cropped from here is not accepted on terms the GUI would refuse — which means
        # judging it BEFORE writing it. The frame is the screen this crop came from,
        # which is what makes the uniqueness check meaningful.
        from engine import template_check as tc
        findings = tc.inspect_crop(out, screen=img,
                                   existing=tc_existing(args.name))

    std = tc.contrast(out)
    for finding in findings:
        print(f"  {finding.level.upper()}: {finding.message}")
    if any(f.blocks for f in findings) and not args.force:
        sys.exit(f"NOT saved: {args.name} would be refused by the matcher "
                 f"(std={std:.1f}). Re-crop, or pass --force to write it anyway.")

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    dest = TEMPLATES_DIR / args.name
    out.save(dest)
    print(f"saved {args.name} {args.w}x{args.h} std={std:.1f} -> {dest}")


def tc_existing(exclude: str):
    """Templates already captured, minus the one being written."""
    from engine.paths import TEMPLATES_DIR
    if not TEMPLATES_DIR.exists():
        return []
    return [p for p in sorted(TEMPLATES_DIR.glob("*.png")) if p.name != exclude]


def cmd_click(args):
    """Post a click at client coordinates, then re-capture."""
    from engine import background_input as bi
    hwnd, _ = find_window(args.title)
    ensure_shown(hwnd)
    if args.hold:
        # Some UIs drop a press+release delivered in the same frame.
        lp = bi._lparam(args.x, args.y)
        win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lp)
        time.sleep(0.08)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
        time.sleep(args.hold)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)
    else:
        bi.post_click(hwnd, args.x, args.y)
    print(f"clicked ({args.x},{args.y}); waiting {args.wait}s")
    time.sleep(args.wait)
    capture(args.title)


def cmd_watch(args):
    """Capture a timed sequence and report how much each frame differs from the
    previous one — how to find a transient screen without eyeballing every frame."""
    import numpy as np
    from PIL import Image
    OUT_DIR.mkdir(exist_ok=True)
    prev = None
    for i in range(args.count):
        if i:
            time.sleep(args.interval)
        capture(args.title, quiet=True)
        with Image.open(FRAME) as img:
            small = img.convert("RGB").resize(
                (int(img.width * args.scale), int(img.height * args.scale)),
                Image.BILINEAR)
            small.save(OUT_DIR / f"seq_{i:02d}.png")
            arr = np.asarray(small, dtype=np.int16)
        diff = 0.0 if prev is None else float(np.abs(arr - prev).mean())
        prev = arr
        print(f"seq_{i:02d}.png  t=+{i * args.interval:5.1f}s  diff={diff:6.2f}")


def cmd_list(args):
    """Report which templates of a pack spec have been captured."""
    from PIL import Image
    from engine.paths import TEMPLATES_DIR
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))["templates"]
    done = 0
    for item in spec:
        path = TEMPLATES_DIR / item["name"]
        if path.exists():
            with Image.open(path) as im:
                print(f"  [x] {item['name']:<34} {im.size[0]}x{im.size[1]}")
            done += 1
        else:
            print(f"  [ ] {item['name']:<34} -")
    print(f"\n{done}/{len(spec)} captured   ({TEMPLATES_DIR})")


def build_parser():
    """The argument parser, separate from main so a test can check the README.

    `--title` belongs to this parser and not to the subcommands, so it has to come
    *before* the subcommand. The README documented it the other way round for months
    and every line in it was rejected by argparse.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", default="Onmyoji",
                        help="substring of the target window title "
                             "(default: Onmyoji; must precede the subcommand)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("shot", help="capture the target window").set_defaults(fn=cmd_shot)

    p = sub.add_parser("peek", help="crop a candidate box for inspection only")
    p.add_argument("x", type=int); p.add_argument("y", type=int)
    p.add_argument("w", type=int); p.add_argument("h", type=int)
    p.add_argument("--scale", type=float, default=2.0)
    p.set_defaults(fn=cmd_peek)

    p = sub.add_parser("crop", help="save a region as a template")
    p.add_argument("name"); p.add_argument("x", type=int); p.add_argument("y", type=int)
    p.add_argument("w", type=int); p.add_argument("h", type=int)
    p.add_argument("--force", action="store_true",
                   help="write it even if the matcher would refuse it")
    p.set_defaults(fn=cmd_crop)

    p = sub.add_parser("click", help="post a click at client coordinates")
    p.add_argument("x", type=int); p.add_argument("y", type=int)
    p.add_argument("--wait", type=float, default=2.0)
    p.add_argument("--hold", type=float, default=0.0,
                   help="hold the button this long (for UIs that drop instant clicks)")
    p.set_defaults(fn=cmd_click)

    p = sub.add_parser("watch", help="capture a timed sequence with change scores")
    p.add_argument("count", type=int, nargs="?", default=12)
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--scale", type=float, default=0.45)
    p.set_defaults(fn=cmd_watch)

    p = sub.add_parser("list", help="capture status against a pack spec")
    p.add_argument("spec")
    p.set_defaults(fn=cmd_list)

    return parser


def main():
    args = build_parser().parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
