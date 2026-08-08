"""Shared color/font constants for the dark UI theme.

Design goals:
  - Clean, modern productivity-app feel (Linear / Notion / Raycast inspired)
  - Generous spacing: 12-16px padding, 8px gaps
  - Minimal chrome: flat surfaces, subtle separators, no heavy borders
  - Single accent color for interactive elements

All sizes here are **logical** pixels, i.e. what they should measure at 100%
display scaling. See ``init_scaling`` for how they reach the screen on a
high-DPI monitor.
"""

import tkinter as tk

# ── Surfaces ─────────────────────────────────────────────────────────────────
BG        = "#1a1a2e"   # window / deepest background
BG2       = "#222236"   # sidebar, panels
BG3       = "#2a2a42"   # cards, inputs, elevated surfaces
BG4       = "#333352"   # card hover, active states

# ── Brand / interactive ──────────────────────────────────────────────────────
ACCENT    = "#7c3aed"   # primary purple
ACCENT_LT = "#9d5ff5"   # hover / lighter shade

# ── Semantic ─────────────────────────────────────────────────────────────────
SUCCESS   = "#22c55e"
DANGER    = "#ef4444"
WARNING   = "#f59e0b"

# ── Text ─────────────────────────────────────────────────────────────────────
FG        = "#e2e8f0"   # primary text
FG_DIM    = "#64748b"   # secondary / muted text
FG_XDIM   = "#475569"   # very muted (placeholder, hint)

# ── Lines ────────────────────────────────────────────────────────────────────
BORDER    = "#3a3a58"
SEP       = "#2a2a42"

# ── Typography ───────────────────────────────────────────────────────────────
FONT       = ("Segoe UI", 10)
FONT_BOLD  = ("Segoe UI", 10, "bold")
FONT_MONO  = ("Consolas", 10)
FONT_TITLE = ("Segoe UI", 14, "bold")
FONT_SMALL = ("Segoe UI", 9)
FONT_LABEL = ("Segoe UI", 8, "bold")   # section headers (ALL CAPS)
FONT_H2    = ("Segoe UI", 11, "bold")  # sub-headings

# ── Spacing constants (px) ───────────────────────────────────────────────────
PAD       = 14      # standard page-level padding
PAD_SM    = 8       # tight inner padding (within cards)
GAP       = 6       # gap between list items / cards
SIDEBAR_W = 280     # sidebar width


# ── DPI scaling ───────────────────────────────────────────────────────────────
#
# main.py declares per-monitor DPI awareness, so on a scaled display Windows
# hands Tk a high-DPI window. Tk then sizes **fonts** for that DPI on its own,
# because font sizes are given in points — at 240 DPI (250% scaling) a 10pt font
# renders 2.5x larger. Pixel distances get no such treatment, so a layout built
# from raw pixel numbers stays at 100% while its text grows: text overflows,
# panels clip mid-word, header buttons fall off the edge.
#
# The fix is to scale pixel distances by the same factor Tk uses for fonts. There are
# ~250 numeric padx/pady arguments across the GUI, so rather than annotate each one,
# init_scaling patches tkinter.Misc._options — the one place a widget constructor, a
# geometry-manager call and configure() all pass through — and scales padding there.
#
# It used to patch the three geometry managers instead, which covered
# widget.pack(padx=10) and missed tk.Label(parent, padx=10): 41 constructor sites and
# 2 configure() calls whose inner padding rendered at 1/SCALE of its intent.
#
# Other pixel sizes in a widget *option* (a Frame's width, a wraplength, a geometry
# string) are still wrapped in px() at the call site, because the same option name
# means characters or lines on other widgets and must not be touched.

SCALE = 1.0


def px(n: float) -> int:
    """Convert a logical pixel size to this display's physical pixels."""
    return int(round(n * SCALE))


def init_scaling(root: tk.Misc) -> float:
    """Measure the display scale and make pixel padding follow it.

    The factor comes from Tk itself rather than from Win32, so it is by
    construction the same DPI Tk used to size the fonts. Safe to call once at
    startup; calling it again does not stack.
    """
    global SCALE
    try:
        SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)
    except Exception:
        SCALE = 1.0
    if SCALE != 1.0:
        _scale_pixel_options()
    return SCALE


_PAD_OPTS = ("padx", "pady", "ipadx", "ipady")
_patched = False


def _scale_pad(kw: dict) -> dict:
    """Scale any pixel padding in a geometry-manager call.

    Strings are left alone: those carry an explicit Tk unit suffix ("4p", "2m")
    and are already resolved against the display's DPI.
    """
    for opt in _PAD_OPTS:
        val = kw.get(opt)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            kw[opt] = px(val)
        elif isinstance(val, (tuple, list)):
            kw[opt] = tuple(px(v) if isinstance(v, (int, float))
                            and not isinstance(v, bool) else v for v in val)
    return kw


def _scale_pixel_options() -> None:
    """Patch ``tkinter.Misc._options`` so every pixel padding is in logical pixels.

    One hook, because everything funnels through it — measured: a widget
    constructor, a ``pack``/``grid``/``place`` call and ``configure()`` all reach
    ``Misc._options`` on the way to Tcl.

    This used to patch the three geometry managers instead, which covered
    ``widget.pack(padx=10)`` and missed ``tk.Label(parent, padx=10)`` entirely —
    43 sites across the GUI whose inner padding therefore rendered at 1/SCALE of
    its intent on a scaled display. Patching here rather than annotating each site
    with ``px()`` is the difference between one thing to get right and 43 things to
    remember. **Patch only one of the two**: pack goes through ``_options`` too, so
    keeping both would scale its padding twice.
    """
    global _patched
    if _patched:
        return
    _patched = True

    original = tk.Misc._options

    def wrapper(self, cnf, kw=None):
        # cnf is not always a mapping: a query like configure('padx') passes a
        # string, and _cnfmerge also accepts a sequence of dicts.
        if isinstance(cnf, dict):
            cnf = _scale_pad(dict(cnf))
        if isinstance(kw, dict):
            kw = _scale_pad(dict(kw))
        return original(self, cnf, kw)

    tk.Misc._options = wrapper


_MONITOR_DEFAULTTONEAREST = 2


def work_area_at(x: int, y: int, fallback_widget=None):
    """Usable bounds (l, t, r, b) of the monitor containing the point (x, y).

    "Usable" excludes the taskbar. Falls back to the primary screen only when the
    monitor cannot be determined.
    """
    try:
        import win32api
        monitor = win32api.MonitorFromPoint((int(x), int(y)),
                                            _MONITOR_DEFAULTTONEAREST)
        return tuple(win32api.GetMonitorInfo(monitor)["Work"])
    except Exception:
        if fallback_widget is not None:
            return (0, 0,
                    fallback_widget.winfo_screenwidth(),
                    fallback_widget.winfo_screenheight())
        return None


def center_on_parent(child, parent, width: int, height: int):
    """Position *child* centred over *parent*. Size is in logical pixels.

    Kept on the monitor the parent is on, and inside that monitor's work area.

    Both halves matter. Scaling makes a 1040x720 dialog 2603x1802 on a 250%
    display — nearly a whole screen — so centring it on a parent near an edge
    would otherwise land at negative coordinates and take the dialog's buttons off
    the display. But clamping against winfo_screenwidth/height is wrong too: those
    report the PRIMARY monitor only, so on a multi-monitor desktop a dialog
    belonging to a window on the second screen gets yanked across to the first
    (measured: 2888 px away). The bounds have to come from the parent's own
    monitor, which is what picker.py and arranger.py already do.
    """
    w, h = px(width), px(height)

    cx = parent.winfo_x() + parent.winfo_width()  // 2
    cy = parent.winfo_y() + parent.winfo_height() // 2
    x, y = cx - w // 2, cy - h // 2

    area = work_area_at(cx, cy, fallback_widget=child)
    if area:
        left, top, right, bottom = area
        w, h = min(w, right - left), min(h, bottom - top)
        x = max(left, min(x, right - w))
        y = max(top, min(y, bottom - h))

    child.geometry(f"{w}x{h}+{x}+{y}")
