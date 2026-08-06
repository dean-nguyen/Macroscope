"""Show one of the app's own windows and capture it, to check the UI renders.

Nothing in the test suite looks at the UI, so a layout defect is only visible by
opening the window and looking. This makes that a command:

    python tools/ui_probe.py app
    python tools/ui_probe.py editor
    python tools/ui_probe.py wizard templates arranger license

Each window is shown in a child process with a real mainloop, captured via WGC,
and closed again. Images land in .probe/ (git-ignored).

Why a child process with a mainloop: a Toplevel built in the same process and
pumped by hand does not get composited properly, and WGC then returns nothing —
falling back to a screen grab at that point captures whatever window happens to
be in front instead, which is worse than no picture because it looks plausible.

Why this matters: on a 250% display the app used to render clipped everywhere
(the header lost buttons, panels cut text mid-word). Sizes reported here should
be the logical size times the display scale — 1060x680 becomes 2653x1702 at
250% — and `white=` should be 0%: anything else usually means the window was
placed partly off-screen.
"""

import ctypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:                                        # pragma: no cover
    pass

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import win32gui

OUT_DIR = ROOT / ".probe"

# name -> (window title to look for, how to build it)
WINDOWS = {
    "app":       "Macroscope",
    "editor":    "New Macro",
    "wizard":    "Guided Capture",
    "templates": "Template Library",
    "arranger":  "Arrange Windows",
}


def _serve_source(which: str) -> str:
    """Source of the child process that shows the requested window."""
    return f'''
import ctypes, json, sys
ctypes.windll.shcore.SetProcessDpiAwareness(2)
sys.path.insert(0, {str(ROOT)!r})
import tkinter as tk
from pathlib import Path
from gui import theme as T

which = {which!r}
if which == "app":
    from gui.app import App
    App().mainloop()
    raise SystemExit

root = tk.Tk()
T.init_scaling(root)
root.title("ui-probe")
root.geometry("160x60+40+40")

if which == "editor":
    from gui.editor import MacroEditor
    MacroEditor(root, save_callback=lambda m: None)
elif which == "wizard":
    from gui.capture_wizard import CaptureWizard
    spec = json.loads((Path({str(ROOT)!r}) / "packs/onmyoji/templates.spec.json")
                      .read_text(encoding="utf-8"))["templates"]
    CaptureWizard(root, spec)
elif which == "templates":
    from engine.macro_engine import MacroEngine
    from gui.template_manager import TemplateManager
    TemplateManager(root, MacroEngine(log_fn=lambda *a: None))
elif which == "arranger":
    from gui.arranger import WindowArranger
    WindowArranger(root)
root.mainloop()
'''


def expected_title(which: str) -> str:
    return WINDOWS[which]


def find(title: str):
    hits = []
    win32gui.EnumWindows(
        lambda h, _: hits.append(h)
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) == title
        else None, None)
    return hits[0] if hits else None


def shoot(which: str) -> bool:
    import cv2
    import numpy as np
    from PIL import Image

    from engine import wgc_capture

    title = expected_title(which)
    proc = subprocess.Popen([sys.executable, "-c", _serve_source(which)], cwd=ROOT)
    try:
        hwnd = None
        for _ in range(40):
            hwnd = find(title)
            if hwnd:
                break
            time.sleep(0.5)
        if hwnd is None:
            print(f"  {which:<11} FAILED: no window titled {title!r}")
            return False

        time.sleep(2.0)
        wgc_capture.get_frame(hwnd)          # opens the capture session
        time.sleep(2.0)                      # let it deliver a frame
        frame = wgc_capture.get_frame(hwnd)
        if frame is None or not frame.size:
            print(f"  {which:<11} FAILED: WGC produced no frame")
            return False

        OUT_DIR.mkdir(exist_ok=True)
        dest = OUT_DIR / f"ui_{which}.png"
        Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).save(dest)
        white = float((frame > 240).all(axis=2).mean()) * 100
        rect = win32gui.GetWindowRect(hwnd)
        print(f"  {which:<11} {frame.shape[1]}x{frame.shape[0]}  at {rect[:2]}  "
              f"white={white:4.1f}%  -> {dest.relative_to(ROOT)}")
        return True
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:    # pragma: no cover
            proc.kill()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("windows", nargs="*", default=["app"],
                       help=f"any of: {', '.join(WINDOWS)} (default: app)")
    args = parser.parse_args()

    unknown = [w for w in args.windows if w not in WINDOWS]
    if unknown:
        sys.exit(f"unknown window(s): {', '.join(unknown)} — "
                 f"choose from {', '.join(WINDOWS)}")

    print(f"capturing: {', '.join(args.windows)}\n")
    ok = all(shoot(w) for w in args.windows)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
