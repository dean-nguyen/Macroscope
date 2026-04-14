"""Shared color/font constants for the dark UI theme.

Design goals:
  - Clean, modern productivity-app feel (Linear / Notion / Raycast inspired)
  - Generous spacing: 12-16px padding, 8px gaps
  - Minimal chrome: flat surfaces, subtle separators, no heavy borders
  - Single accent color for interactive elements
"""

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


def center_on_parent(child, parent, width: int, height: int):
    """Position *child* window centred over *parent*, on the same monitor."""
    px = parent.winfo_x() + parent.winfo_width()  // 2
    py = parent.winfo_y() + parent.winfo_height() // 2
    x  = px - width  // 2
    y  = py - height // 2
    child.geometry(f"{width}x{height}+{x}+{y}")
