"""Show what is wrong with a crop, at the moment it can still be fixed.

The engine can already say a template *did not match*, in a log, later. What it
could not do was say "this crop will never work" while the game is still on screen
— which is the only moment the fix is free.

A blocker offers no way to save: the engine refuses flat templates outright, so
saving one produces a file whose every check silently reports "not found". Warnings
are advisory, because "this appears three times" is sometimes exactly what the
author wants (`find_all_and_click` is built on it).
"""

import threading
import tkinter as tk
from typing import List, Optional, Sequence

from engine import template_check as tc
from gui import theme as T
from gui.widgets import Button, Frame, Label, SectionLabel


def review_crop(
    parent,
    crop,
    screen=None,
    existing: Sequence = (),
    threshold: float = tc.DEFAULT_THRESHOLD,
) -> bool:
    """Check *crop* and, if anything is wrong, ask the user what to do.

    Returns True to save it. A clean crop returns True without a dialog — nobody wants
    a modal telling them their capture is fine.
    """
    findings = _inspect_with_progress(parent, crop, screen, existing, threshold)
    if not findings:
        return True
    # The check no longer blocks the UI thread, so the parent can be closed while it
    # runs. Reproduced: building the findings dialog on a destroyed parent raises
    # TclError out of here, into the capture callback, which then reports a second
    # cancelled capture and raises again from its own teardown.
    try:
        if not parent.winfo_exists():
            return True
    except tk.TclError:
        return True
    return _ask(parent, findings)


def _inspect_with_progress(parent, crop, screen, existing, threshold) -> List[tc.Finding]:
    """Run the check off the UI thread, behind a modal that says what is happening.

    It is not instant and it grows with the templates directory: measured on a real
    desktop, 0.7 s to scan a 6400x2400 screen plus ~40 ms per already-captured
    template, so 1.4 s for a small pack and ~5 s for a large one. Run inline that is a
    frozen, unpaintable window with no cursor change, right after the capture overlay
    has disappeared.
    """
    result: List = []
    done = threading.Event()

    def work():
        try:
            result.extend(tc.inspect_crop(crop, screen=screen, existing=existing,
                                          threshold=threshold))
        except Exception:
            pass          # a check that cannot run must never lose the capture
        finally:
            done.set()

    worker = threading.Thread(target=work, daemon=True, name="template-check")
    worker.start()

    # Nothing on screen for a check that finishes immediately; the flicker of a dialog
    # appearing and vanishing is worse than no dialog.
    if done.wait(0.35):
        return list(result)

    dlg = tk.Toplevel(parent)
    dlg.title("Checking")
    dlg.configure(bg=T.BG)
    T.center_on_parent(dlg, parent, 320, 96)
    dlg.resizable(False, False)
    dlg.transient(parent)
    dlg.grab_set()
    dlg.protocol("WM_DELETE_WINDOW", lambda: None)     # it ends when the check ends
    Label(dlg, text="Checking this capture…").pack(padx=20, pady=(24, 4), anchor="w")
    tk.Label(dlg, text="scoring it against the screen and your other templates",
             bg=T.BG, fg=T.FG_XDIM, font=T.FONT_SMALL).pack(padx=20, anchor="w")

    def poll():
        if done.is_set():
            dlg.destroy()
        else:
            dlg.after(80, poll)

    dlg.after(80, poll)
    parent.wait_window(dlg)
    return list(result)


def _ask(parent, findings: List[tc.Finding]) -> bool:
    blocked = any(f.blocks for f in findings)

    dlg = tk.Toplevel(parent)
    dlg.title("Check this capture")
    dlg.configure(bg=T.BG)
    height = 190 + 62 * len(findings)
    T.center_on_parent(dlg, parent, 460, min(height, 520))
    dlg.resizable(False, False)
    dlg.transient(parent)
    dlg.grab_set()

    SectionLabel(dlg, "This capture will not work" if blocked
                 else "This capture may not do what you expect",
                 bg=T.BG).pack(anchor="w", padx=20, pady=(18, 10))

    for finding in findings:
        row = tk.Frame(dlg, bg=T.BG3)
        row.pack(fill=tk.X, padx=20, pady=4)
        colour = T.DANGER if finding.blocks else T.WARNING
        tk.Label(row, text="■", bg=T.BG3, fg=colour, font=T.FONT_SMALL).pack(
            side=tk.LEFT, anchor="n", padx=(10, 6), pady=10)
        tk.Label(row, text=finding.message, bg=T.BG3, fg=T.FG_DIM, font=T.FONT_SMALL,
                 wraplength=T.px(370), justify="left", anchor="w").pack(
            side=tk.LEFT, fill=tk.X, expand=True, pady=10, padx=(0, 10))

    keep = {"value": False}

    def _save():
        keep["value"] = True
        dlg.destroy()

    row = Frame(dlg)
    row.pack(pady=14)
    if not blocked:
        Button(row, "Save anyway", command=_save, variant="success").pack(
            side=tk.LEFT, padx=4)
    # "Discard", not "Capture again": this dialog cannot start a capture, and a button
    # that only closes must not claim to.
    Button(row, "Discard", command=dlg.destroy, variant="ghost").pack(
        side=tk.LEFT, padx=4)

    dlg.bind("<Escape>", lambda _: dlg.destroy())
    parent.wait_window(dlg)
    return keep["value"]


def other_templates(templates_dir, exclude: Optional[str] = None) -> List:
    """Every captured template except *exclude*, for the collision check.

    Re-capturing a template must not be reported as colliding with the version it
    is replacing.
    """
    try:
        paths = sorted(p for p in templates_dir.glob("*.png") if p.is_file())
    except Exception:
        return []
    return [p for p in paths if exclude is None or p.name != exclude]
