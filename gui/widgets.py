"""Reusable themed widgets — clean, minimal style."""

import tkinter as tk
from gui import theme as T


# ── helpers ───────────────────────────────────────────────────────────────────

def recolor(widget, color: str):
    """Recursively set bg on a widget tree, skipping Buttons."""
    try:
        if not isinstance(widget, tk.Button):
            widget.config(bg=color)
    except tk.TclError:
        pass
    for child in widget.winfo_children():
        recolor(child, color)


# ── widgets ───────────────────────────────────────────────────────────────────

class Button(tk.Button):
    _COLORS = {
        "primary": (T.ACCENT,   T.ACCENT_LT),
        "danger":  (T.DANGER,   "#f87171"),
        "success": (T.SUCCESS,  "#4ade80"),
        "ghost":   (T.BG3,      T.BG4),
    }

    def __init__(self, parent, text="", command=None, variant="primary", **kw):
        bg, hover = self._COLORS.get(variant, self._COLORS["primary"])
        super().__init__(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=T.FG,
            activebackground=hover,
            activeforeground=T.FG,
            relief=tk.FLAT,
            cursor="hand2",
            font=T.FONT,
            padx=14,
            pady=6,
            bd=0,
            **kw,
        )
        self.bind("<Enter>", lambda _: self.configure(bg=hover))
        self.bind("<Leave>", lambda _: self.configure(bg=bg))


class IconButton(tk.Button):
    """Small square icon button with hover."""

    def __init__(self, parent, text, command, bg, hover_bg, fg=T.FG, **kw):
        super().__init__(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=hover_bg,
            activeforeground=fg,
            relief=tk.FLAT,
            cursor="hand2",
            font=T.FONT_BOLD,
            padx=7,
            pady=3,
            bd=0,
            **kw,
        )
        self._bg = bg
        self._hover = hover_bg
        self.bind("<Enter>", lambda _: self.configure(bg=self._hover))
        self.bind("<Leave>", lambda _: self.configure(bg=self._bg))


class Label(tk.Label):
    def __init__(self, parent, text="", dim=False, bold=False, **kw):
        font = T.FONT_BOLD if bold else T.FONT
        fg   = T.FG_DIM if dim else T.FG
        kw.setdefault("bg", T.BG)
        kw.setdefault("fg", fg)
        super().__init__(parent, text=text, font=font, **kw)


class Frame(tk.Frame):
    def __init__(self, parent, bg=None, **kw):
        super().__init__(parent, bg=bg or T.BG, **kw)


class Badge(tk.Label):
    """Pill-shaped colored label."""

    def __init__(self, parent, text, bg, fg="#ffffff", **kw):
        kw.setdefault("font", T.FONT_SMALL)
        kw.setdefault("padx", 6)
        kw.setdefault("pady", 1)
        super().__init__(parent, text=text, bg=bg, fg=fg, relief=tk.FLAT, **kw)


class SectionLabel(tk.Label):
    """ALL-CAPS muted section header."""

    def __init__(self, parent, text, bg=T.BG2, **kw):
        super().__init__(
            parent,
            text=text.upper(),
            font=T.FONT_LABEL,
            bg=bg,
            fg=T.FG_DIM,
            **kw,
        )


class ScrolledText(tk.Frame):
    """Text widget with vertical (and optional horizontal) scrollbar."""

    def __init__(self, parent, horizontal=False, **kw):
        super().__init__(parent, bg=T.BG)
        self.text = tk.Text(
            self,
            bg=T.BG2,
            fg=T.FG,
            insertbackground=T.FG,
            font=T.FONT_MONO,
            relief=tk.FLAT,
            wrap=tk.NONE,
            padx=8,
            pady=6,
            **kw,
        )
        vsb = tk.Scrollbar(self, command=self.text.yview, bg=T.BG3,
                           troughcolor=T.BG2, width=6)
        self.text.configure(yscrollcommand=vsb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        if horizontal:
            xsb = tk.Scrollbar(
                self, orient=tk.HORIZONTAL, command=self.text.xview,
                bg=T.BG3, troughcolor=T.BG2, width=6,
            )
            self.text.configure(xscrollcommand=xsb.set)
            xsb.grid(row=1, column=0, sticky="ew")

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

    def get(self, *a, **kw):        return self.text.get(*a, **kw)
    def insert(self, *a, **kw):     return self.text.insert(*a, **kw)
    def delete(self, *a, **kw):     return self.text.delete(*a, **kw)
    def configure(self, **kw):      self.text.configure(**kw)
    def see(self, index):           self.text.see(index)
