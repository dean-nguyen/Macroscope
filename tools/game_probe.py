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

def find_window(title_substring: str, position=None):
    """A visible top-level window whose title contains *title_substring*.

    Two clients of one game share a title exactly, and EnumWindows order is not
    something to rely on — so with more than one match this refuses to guess unless
    *position* says which, counting left to right then top to bottom. That is the same
    ordering `target_position` uses in a macro, deliberately: a probe that measured the
    other account would be worse than one that stopped.
    """
    hits = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            text = win32gui.GetWindowText(hwnd)
            if title_substring.lower() in text.lower():
                hits.append((hwnd, text))

    win32gui.EnumWindows(cb, None)
    if not hits:
        sys.exit(f"No visible window matching {title_substring!r}")

    if position is not None:
        from engine.background_input import by_screen_position
        ordered = by_screen_position(hits)
        if not 0 <= position < len(ordered):
            sys.exit(f"--position {position} but only {len(ordered)} window(s) match")
        return ordered[position]
    if len(hits) > 1:
        from engine.background_input import by_screen_position
        listing = chr(10).join(
            f"    --position {i}  hwnd {h}  {win32gui.GetWindowRect(h)[:2]}"
            for i, (h, _t) in enumerate(by_screen_position(hits)))
        sys.exit(f"{len(hits)} windows match {title_substring!r}; say which:"
                 + chr(10) + listing)
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
    hwnd, _ = find_window(args.title, args.position)
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


def cmd_settle(args):
    """Click somewhere, then time how long a template takes to appear.

    This is the measurement behind every settle constant in a pack, and the pack has
    already been burned by *guessing* one: a 600 ms wait was added on a theory about
    panel animation, could not be confirmed, and was removed. Guessing the other way is
    just as expensive — `try_cells` waits up to 1500 ms per cell for a target panel, and
    a cell that is already defeated opens nothing, so it pays the whole budget. Nine
    dead cells is 13.5 s of a 16.0 s tick, every tick, because the chain has no memory
    of which cells it already found dead.

    Two things this got wrong first, both of which made the probe answer about itself
    rather than about the game:

    **It must not run under `unrationed_discovery()`.** That switch is for the template
    report, and CLAUDE.md says a macro must never turn it on — so a probe measuring what
    a macro experiences must not either. With it on, every poll ran a full ~2.7 s scale
    search for a button that was not on screen, so a 2 s budget took exactly one sample.

    **The scale cache has to be warmed with a template that is already visible.** A
    failed search caches nothing, so warming with the template being timed — which by
    definition is not there yet — leaves every later search paying full discovery.
    Measured at 1810x1020: 2797 ms. The cache is keyed by window size as well as by
    template, so any visible template teaches the window's scale to the rest.

    "never" is a real answer, and it is what a defeated cell looks like: the budget was
    spent finding nothing.
    """
    from engine import background_input as bi, image_matcher as im
    hwnd, _ = find_window(args.title, args.position)
    ensure_shown(hwnd)

    ref = args.template if "/" in args.template else f"templates/{args.template}"
    warm_ref = args.warm_with or args.template
    if "/" not in warm_ref:
        warm_ref = f"templates/{warm_ref}"

    im.clear_scale_cache()
    warm_start = time.time()
    warmed = im.find_template(warm_ref, hwnd=hwnd, threshold=args.threshold)
    warm_ms = (time.time() - warm_start) * 1000

    # The template must be ABSENT before the click, or there is nothing to time. Measured
    # the hard way: a second run with the previous target's panel still open reported
    # "appeared after 0 ms" — it had found the old panel, and a 0 ms settle is exactly the
    # kind of answer that gets believed.
    already = im.find_template(ref, hwnd=hwnd, threshold=args.threshold)
    if already and not args.allow_visible:
        sys.exit(f"{ref} is already on screen (score {already[2]:.3f}) — close it first, "
                 f"or there is nothing to time. --allow-visible overrides.")

    bi.post_click(hwnd, args.x, args.y)
    start = time.time()
    samples, first = [], None
    while (elapsed := time.time() - start) < args.budget:
        search_start = time.time()
        found = im.find_template(ref, hwnd=hwnd, threshold=args.threshold)
        samples.append((elapsed, (time.time() - search_start) * 1000,
                        found[2] if found else None))
        if found:
            first = elapsed
            break
        time.sleep(args.interval)

    print(f"clicked ({args.x},{args.y}), watching {ref} at threshold {args.threshold}")
    print(f"  warmed with {warm_ref}: {warm_ms:.0f} ms, "
          f"{'found it' if warmed else 'NOT FOUND'}")
    if not warmed:
        print("    nothing was cached — pass --warm-with a template that IS on screen, "
              "or every sample below pays full scale discovery")
    for elapsed, search_ms, score in samples:
        shown = "-" if score is None else f"{score:.3f}"
        mark = "MATCH" if score is not None else "     "
        print(f"  +{elapsed * 1000:6.0f} ms  {mark}  best {shown:>6}  "
              f"(search {search_ms:5.0f} ms)")
    if first is None:
        print(f"  never appeared within {args.budget:.1f}s, over {len(samples)} samples "
              f"— which is what a dead cell looks like, and the whole budget bought "
              f"nothing")
    else:
        print(f"  appeared after {first * 1000:.0f} ms, on sample {len(samples)}")


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
    parser.add_argument("--position", type=int, default=None,
                        help="which matching window, left to right then top to bottom "
                             "(same ordering as a macro's target_position). Required "
                             "when more than one window matches.")
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

    p = sub.add_parser("settle",
                       help="click, then time how long a template takes to appear")
    p.add_argument("x", type=int); p.add_argument("y", type=int)
    p.add_argument("template", help="e.g. onmyoji_realmraid_attack.png")
    p.add_argument("--threshold", type=float, default=0.8)
    p.add_argument("--interval", type=float, default=0.05)
    p.add_argument("--budget", type=float, default=3.0)
    p.add_argument("--allow-visible", action="store_true",
                   help="measure even though the template is already on screen "
                        "(the answer will be 0 ms and will mean nothing)")
    p.add_argument("--warm-with", default=None,
                   help="a template already on screen, used only to cache the window's "
                        "scale. Without it the first sample measures scale discovery.")
    p.set_defaults(fn=cmd_settle)

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
