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
# The fix is to scale pixel distances by the same factor Tk uses for fonts.
# There are ~450 numeric padx/pady arguments across the GUI, so rather than
# annotate each one, init_scaling wraps the geometry managers — where padding is
# always in pixels — and does it centrally. Sizes that are pixels in a widget
# *option* (a Frame's width, a wraplength, a geometry string) are wrapped in
# px() at the call site, because the same option name means characters or lines
# on other widgets and must not be touched.

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
        _scale_geometry_managers()
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


def _scale_geometry_managers() -> None:
    """Patch pack/grid/place so their padding is in logical pixels."""
    global _patched
    if _patched:
        return
    _patched = True

    for cls, names in ((tk.Pack, ("pack", "pack_configure")),
                       (tk.Grid, ("grid", "grid_configure")),
                       (tk.Place, ("place", "place_configure"))):
        original = getattr(cls, names[1])

        def make(func):
            def wrapper(self, cnf={}, **kw):
                if cnf:
                    cnf = _scale_pad(dict(cnf))
                return func(self, cnf, **_scale_pad(kw))
            return wrapper

        wrapped = make(original)
        # `pack` and `pack_configure` are two names for one function, so both
        # have to be replaced or callers of the alias keep the unscaled version.
        for name in names:
            setattr(cls, name, wrapped)


def center_on_parent(child, parent, width: int, height: int):
    """Position *child* centred over *parent*. Size is in logical pixels.

    The result is clamped to the screen. This matters more than it looks: once
    sizes scale with DPI, a 1040x720 dialog becomes 2603x1802 on a 250% display,
    which is nearly the whole screen — centring that on a parent sitting near an
    edge used to place it at negative coordinates, leaving part of the dialog
    (including its buttons) off the display.
    """
    w, h = px(width), px(height)
    try:
        screen_w, screen_h = child.winfo_screenwidth(), child.winfo_screenheight()
    except Exception:
        screen_w = screen_h = 0

    cx = parent.winfo_x() + parent.winfo_width()  // 2
    cy = parent.winfo_y() + parent.winfo_height() // 2
    x, y = cx - w // 2, cy - h // 2

    if screen_w and screen_h:
        w, h = min(w, screen_w), min(h, screen_h)
        x = max(0, min(x, screen_w - w))
        y = max(0, min(y, screen_h - h))

    child.geometry(f"{w}x{h}+{x}+{y}")
