"""
Macro editor – interactive visual form editor.

Each action is a card with inline form fields.
Branch actions (on_match, on_found…) open a JSON sub-editor.
"""

import json
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, filedialog
from typing import Callable, Dict, List, Optional

from engine.paths import TEMPLATES_DIR
from engine import template_store as ts
from gui import theme as T
from gui.widgets import Button, SectionLabel, prompt_text
from gui.picker import PixelPicker


# ── utilities ─────────────────────────────────────────────────────────────────

def _bind_wheel_recursive(widget, handler):
    widget.bind("<MouseWheel>", handler)
    for child in widget.winfo_children():
        _bind_wheel_recursive(child, handler)


# ── Action field definitions ──────────────────────────────────────────────────
# Each tuple: (field_name, field_type, default_value)
# field_type: "int" | "float" | "str" | "bool"
#            | "choice:a,b,c" | "keys" | "color" | "template" | "actions"

_F: Dict[str, list] = {
    "wait":          [("ms",              "int",                   500)],
    "stop":          [],
    "click":         [("x",               "int",                     0),
                      ("y",               "int",                     0),
                      ("button",          "choice:left,right,middle", "left"),
                      ("clicks",          "int",                     1)],
    "right_click":   [("x",               "int",                     0),
                      ("y",               "int",                     0)],
    "double_click":  [("x",               "int",                     0),
                      ("y",               "int",                     0)],
    "move":          [("x",               "int",                     0),
                      ("y",               "int",                     0),
                      ("duration",        "float",                  0.1)],
    "drag":          [("x",               "int",                     0),
                      ("y",               "int",                     0),
                      ("x2",              "int",                   100),
                      ("y2",              "int",                   100),
                      ("duration",        "float",                  0.2),
                      ("button",          "choice:left,right,middle", "left")],
    "scroll":        [("x",               "int",                     0),
                      ("y",               "int",                     0),
                      ("amount",          "int",                     3)],
    "key":           [("keys",            "keys",         ["ctrl", "c"])],
    "type":          [("text",            "str",               "hello"),
                      ("interval",        "float",              0.02)],
    "pixel_wait":    [("x",               "int",                     0),
                      ("y",               "int",                     0),
                      ("color",           "color",        [255, 0, 0]),
                      ("tolerance",       "int",                    10),
                      ("timeout_ms",      "int",                  5000),
                      ("fail_on_timeout", "bool",                False)],
    "pixel_check":   [("x",               "int",                     0),
                      ("y",               "int",                     0),
                      ("color",           "color",        [255, 0, 0]),
                      ("tolerance",       "int",                    10),
                      ("on_match",        "actions",                []),
                      ("on_no_match",     "actions",                [])],
    "find_and_click":[("template",        "template",               ""),
                      ("button",          "choice:left,right,middle", "left"),
                      ("threshold",       "float",                0.80),
                      ("on_found",        "actions",                []),
                      ("on_not_found",    "actions",                [])],
    "image_wait":    [("template",        "template",               ""),
                      ("threshold",       "float",                0.80),
                      ("timeout_ms",      "int",                  5000),
                      ("poll_ms",         "int",                   500),
                      ("fail_on_timeout", "bool",                False)],
    "image_check":   [("template",        "template",               ""),
                      ("threshold",       "float",                0.80),
                      ("on_found",        "actions",                []),
                      ("on_not_found",    "actions",                [])],
    "find_rects_and_click":
                     [("index",           "str",                   "0"),
                      ("min_w",           "int",                    40),
                      ("min_h",           "int",                    40),
                      ("max_w",           "int",                   800),
                      ("max_h",           "int",                   800),
                      ("button",          "choice:left,right,middle", "left"),
                      ("click_delay",     "int",                   500),
                      ("on_found",        "actions",                []),
                      ("on_not_found",    "actions",                [])],
    "find_all_and_click":
                     [("template",        "template",               ""),
                      ("threshold",       "float",                0.70),
                      ("button",          "choice:left,right,middle", "left"),
                      ("click_delay",     "int",                   500),
                      ("order",           "choice:top_left,score",  "top_left"),
                      ("on_found",        "actions",                []),
                      ("on_not_found",    "actions",                [])],
}

_COLOR = {
    "wait":           "#3a3a5a",
    "click":          "#1b5e38",
    "right_click":    "#1b5e38",
    "double_click":   "#1b5e38",
    "move":           "#1a3d5c",
    "drag":           "#1a3d5c",
    "scroll":         "#1a3d5c",
    "key":            "#5c3a1a",
    "type":           "#5c3a1a",
    "pixel_wait":     "#5c1e1e",
    "pixel_check":    "#5c1e1e",
    "find_and_click": "#3a1a5c",
    "image_wait":     "#3a1a5c",
    "image_check":    "#3a1a5c",
    "find_rects_and_click": "#2a4a2a",
    "find_all_and_click":   "#2a3a5c",
}

_ICON = {
    "wait":           "⏱  wait",
    "click":          "🖱  click",
    "right_click":    "🖱  right_click",
    "double_click":   "🖱  double_click",
    "move":           "↗  move",
    "drag":           "↔  drag",
    "scroll":         "↕  scroll",
    "key":            "⌨  key",
    "type":           "T  type",
    "pixel_wait":     "👁  pixel_wait",
    "pixel_check":    "👁  pixel_check",
    "find_and_click": "🔍 find_and_click",
    "image_wait":     "🔍 image_wait",
    "image_check":    "🔍 image_check",
    "find_rects_and_click": "▢  find_rects",
    "find_all_and_click":   "🔎 find_all",
}

_GROUPS = [
    ("Mouse",    ["click", "right_click", "double_click", "move", "drag", "scroll"]),
    ("Keyboard", ["key", "type"]),
    ("Timing",   ["wait", "pixel_wait"]),
    ("Branch",   ["pixel_check", "image_check"]),
    ("Image",    ["find_and_click", "find_all_and_click", "image_wait"]),
    ("Detect",   ["find_rects_and_click"]),
]


def _build_type_picker_body(popup: tk.Toplevel, title: str,
                             on_pick: Callable[[str], None]) -> None:
    """Build a scrollable, resizable action-type picker inside *popup*.

    Each action sits on its own row (full-width button) so it always stays
    readable regardless of popup size. The body scrolls vertically when the
    content is taller than the window.
    """
    # Title bar
    tk.Label(popup, text=title, font=T.FONT_TITLE,
             bg=T.BG, fg=T.FG).pack(anchor="w", padx=14, pady=(12, 6))

    # Scrollable container
    wrap = tk.Frame(popup, bg=T.BG)
    wrap.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 8))
    wrap.rowconfigure(0, weight=1)
    wrap.columnconfigure(0, weight=1)

    canvas = tk.Canvas(wrap, bg=T.BG, highlightthickness=0, bd=0)
    vsb = tk.Scrollbar(wrap, orient=tk.VERTICAL, command=canvas.yview,
                       bg=T.BG3, troughcolor=T.BG2, width=10)
    canvas.configure(yscrollcommand=vsb.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")

    inner = tk.Frame(canvas, bg=T.BG)
    window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
               lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",
                lambda e: canvas.itemconfig(window_id, width=e.width))

    # Mousewheel scroll
    def _wheel(e):
        canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
    canvas.bind("<Enter>", lambda _: canvas.bind_all("<MouseWheel>", _wheel))
    canvas.bind("<Leave>", lambda _: canvas.unbind_all("<MouseWheel>"))

    # Build groups — one action per row, full-width button with hover.
    for group_name, types in _GROUPS:
        tk.Label(inner, text=group_name.upper(),
                 font=T.FONT_LABEL, bg=T.BG, fg=T.FG_DIM).pack(
            anchor="w", padx=12, pady=(12, 4))
        for t in types:
            accent = _COLOR.get(t, T.BG3)
            def _pick(atype=t):
                on_pick(atype)
            label = _ICON.get(t, t)
            btn = tk.Button(
                inner, text=label, command=_pick,
                bg=T.BG3, fg=T.FG,
                activebackground=accent, activeforeground="#ffffff",
                relief=tk.FLAT, cursor="hand2",
                font=T.FONT, padx=10, pady=7, bd=0,
                anchor="w",
            )
            btn.pack(fill=tk.X, padx=12, pady=1)
            btn.bind("<Enter>", lambda e, c=accent: e.widget.config(bg=c, fg="#fff"))
            btn.bind("<Leave>", lambda e: e.widget.config(bg=T.BG3, fg=T.FG))


# ── Main editor window ────────────────────────────────────────────────────────

class MacroEditor(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Tk,
        save_callback: Callable[[dict], None],
        macro: Optional[dict] = None,
    ):
        super().__init__(parent)
        self.title("Edit Macro" if macro else "New Macro")
        self.configure(bg=T.BG)
        T.center_on_parent(self, parent, 1040, 720)
        self.minsize(760, 520)
        self.resizable(True, True)

        self._save_callback = save_callback
        self._picker = PixelPicker(parent, self._on_pixel_picked)
        self._action_rows: List[Dict] = []
        self._target_hwnd: Optional[int] = None  # exact hwnd from window picker

        # Macro meta vars
        self._name_var       = tk.StringVar()
        self._desc_var       = tk.StringVar()
        self._hotkey_var     = tk.StringVar()
        self._loop_var       = tk.BooleanVar()
        self._loop_delay_var = tk.StringVar(value="0")
        self._bg_var         = tk.BooleanVar()
        self._target_var     = tk.StringVar()

        self._build_ui()
        self._load_macro(macro or _default_macro())

    # ── layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # header
        hdr = tk.Frame(self, bg=T.BG2)
        hdr.grid(row=0, column=0, sticky="ew")
        self._build_header(hdr)
        tk.Frame(self, bg=T.SEP, height=1).grid(row=1, column=0, sticky="ew")

        # body
        body = tk.Frame(self, bg=T.BG)
        body.grid(row=2, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0, minsize=170)
        body.grid_rowconfigure(0, weight=1)
        self._build_actions_panel(body)
        self._build_sidebar(body)

        # footer
        tk.Frame(self, bg=T.SEP, height=1).grid(row=3, column=0, sticky="ew")
        foot = tk.Frame(self, bg=T.BG2)
        foot.grid(row=4, column=0, sticky="ew")
        inner = tk.Frame(foot, bg=T.BG2)
        inner.pack(fill=tk.X, padx=T.PAD, pady=10)
        Button(inner, "Save",   command=self._save,   variant="success").pack(side=tk.RIGHT, padx=4)
        Button(inner, "Cancel", command=self.destroy, variant="ghost"  ).pack(side=tk.RIGHT, padx=4)

    def _build_header(self, hdr):
        pad_x = T.PAD

        # ── Row 0: Name + Hotkey ───────────────────────────────────────────────
        r0 = tk.Frame(hdr, bg=T.BG2)
        r0.pack(fill=tk.X, padx=pad_x, pady=(12, 0))

        # Name field group
        ng = tk.Frame(r0, bg=T.BG2)
        ng.pack(side=tk.LEFT)
        tk.Label(ng, text="NAME", font=T.FONT_LABEL, bg=T.BG2,
                 fg=T.FG_DIM).pack(anchor="w")
        tk.Entry(ng, textvariable=self._name_var, bg=T.BG3, fg=T.FG,
                 insertbackground=T.FG, relief=tk.FLAT, font=T.FONT,
                 width=24).pack(ipady=3)

        # Hotkey field group
        hg = tk.Frame(r0, bg=T.BG2)
        hg.pack(side=tk.LEFT, padx=(20, 0))
        tk.Label(hg, text="HOTKEY", font=T.FONT_LABEL, bg=T.BG2,
                 fg=T.FG_DIM).pack(anchor="w")
        hk_row = tk.Frame(hg, bg=T.BG2)
        hk_row.pack()
        tk.Entry(hk_row, textvariable=self._hotkey_var, bg=T.BG3, fg=T.FG,
                 insertbackground=T.FG, relief=tk.FLAT, font=T.FONT,
                 width=16).pack(side=tk.LEFT, ipady=3)
        tk.Label(hk_row, text="e.g. ctrl, F1", font=T.FONT_SMALL,
                 bg=T.BG2, fg=T.FG_XDIM).pack(side=tk.LEFT, padx=(6, 0))

        # ── Row 1: Description ─────────────────────────────────────────────────
        r1 = tk.Frame(hdr, bg=T.BG2)
        r1.pack(fill=tk.X, padx=pad_x, pady=(8, 0))
        tk.Label(r1, text="DESCRIPTION", font=T.FONT_LABEL, bg=T.BG2,
                 fg=T.FG_DIM).pack(anchor="w")
        tk.Entry(r1, textvariable=self._desc_var, bg=T.BG3, fg=T.FG,
                 insertbackground=T.FG, relief=tk.FLAT, font=T.FONT).pack(
            fill=tk.X, ipady=3)

        # ── Row 2: Loop + Background ───────────────────────────────────────────
        r2 = tk.Frame(hdr, bg=T.BG2)
        r2.pack(fill=tk.X, padx=pad_x, pady=(10, 12))

        tk.Checkbutton(r2, text="Loop", variable=self._loop_var,
                        bg=T.BG2, fg=T.FG, selectcolor=T.BG3,
                        activebackground=T.BG2, activeforeground=T.FG,
                        font=T.FONT, highlightthickness=0).pack(side=tk.LEFT)
        tk.Label(r2, text="every", font=T.FONT_SMALL,
                 bg=T.BG2, fg=T.FG_DIM).pack(side=tk.LEFT, padx=(6, 2))
        tk.Entry(r2, textvariable=self._loop_delay_var, bg=T.BG3, fg=T.FG,
                 insertbackground=T.FG, relief=tk.FLAT, font=T.FONT,
                 width=6).pack(side=tk.LEFT, ipady=2)
        tk.Label(r2, text="ms", font=T.FONT_SMALL,
                 bg=T.BG2, fg=T.FG_DIM).pack(side=tk.LEFT, padx=(2, 24))

        tk.Checkbutton(r2, text="Background", variable=self._bg_var,
                        bg=T.BG2, fg=T.FG, selectcolor=T.BG3,
                        activebackground=T.BG2, activeforeground=T.FG,
                        font=T.FONT, highlightthickness=0).pack(side=tk.LEFT)
        tk.Label(r2, text="target", font=T.FONT_SMALL,
                 bg=T.BG2, fg=T.FG_DIM).pack(side=tk.LEFT, padx=(6, 2))
        tk.Entry(r2, textvariable=self._target_var, bg=T.BG3, fg=T.FG,
                 insertbackground=T.FG, relief=tk.FLAT, font=T.FONT,
                 width=22).pack(side=tk.LEFT, padx=(0, 4), ipady=2)
        self._small_btn(r2, "Pick window", self._pick_window).pack(side=tk.LEFT)

    def _build_actions_panel(self, body):
        panel = tk.Frame(body, bg=T.BG)
        panel.grid(row=0, column=0, sticky="nsew", padx=(T.PAD, 6), pady=T.PAD)
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        # section header row
        top = tk.Frame(panel, bg=T.BG)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        SectionLabel(top, "Actions", bg=T.BG).pack(side=tk.LEFT)
        self._count_lbl = tk.Label(top, text="0", font=T.FONT_SMALL, bg=T.BG, fg=T.FG_DIM)
        self._count_lbl.pack(side=tk.LEFT, padx=4)
        add_btn = tk.Button(top, text="+ Add Action",
                             command=self._show_type_picker,
                             bg=T.ACCENT, fg=T.FG,
                             activebackground=T.ACCENT_LT, activeforeground=T.FG,
                             relief=tk.FLAT, cursor="hand2",
                             font=T.FONT, padx=10, pady=3, bd=0)
        add_btn.bind("<Enter>", lambda _: add_btn.config(bg=T.ACCENT_LT))
        add_btn.bind("<Leave>", lambda _: add_btn.config(bg=T.ACCENT))
        add_btn.pack(side=tk.RIGHT)

        # scrollable list
        canvas = tk.Canvas(panel, bg=T.BG, highlightthickness=0)
        sb = tk.Scrollbar(panel, orient=tk.VERTICAL, command=canvas.yview,
                           bg=T.BG3, troughcolor=T.BG2, width=8)
        canvas.configure(yscrollcommand=sb.set)
        canvas.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")

        self._list_frame = tk.Frame(canvas, bg=T.BG)
        _win = canvas.create_window((0, 0), window=self._list_frame, anchor="nw")
        self._list_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(_win, width=e.width))

        def _wheel(e):
            try:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            except tk.TclError:
                pass

        canvas.bind("<MouseWheel>", _wheel)
        self._list_canvas   = canvas
        self._list_wheel_fn = _wheel

    def _build_sidebar(self, body):
        sb = tk.Frame(body, bg=T.BG2)
        sb.grid(row=0, column=1, sticky="nsew", padx=(0, T.PAD), pady=T.PAD)

        SectionLabel(sb, "Tools", bg=T.BG2).pack(anchor="w", padx=12, pady=(14, 8))
        self._sb_btn(sb, "Pick pixel",     self._pick_pixel    ).pack(fill=tk.X, padx=10, pady=2)
        self._sb_btn(sb, "Capture region", self._capture_region).pack(fill=tk.X, padx=10, pady=2)

        tk.Frame(sb, bg=T.BORDER, height=1).pack(fill=tk.X, padx=12, pady=12)

        SectionLabel(sb, "Tips", bg=T.BG2).pack(anchor="w", padx=12, pady=(0, 6))
        for tip in [
            "Drag to reorder actions",
            "Click type badge to change",
            "Branch opens sub-editor",
            "Keys: ctrl, shift, F1 ...",
        ]:
            tk.Label(sb, text=tip, font=T.FONT_SMALL, bg=T.BG2, fg=T.FG_XDIM,
                     justify=tk.LEFT, wraplength=145).pack(anchor="w", padx=12, pady=2)

    def _sb_btn(self, parent, text, command):
        bg, hov = T.BG3, T.BG4
        btn = tk.Button(parent, text=text, command=command,
                         bg=bg, fg=T.FG, activebackground=hov, activeforeground=T.FG,
                         relief=tk.FLAT, cursor="hand2", font=T.FONT,
                         anchor="w", padx=8, pady=5, bd=0)
        btn.bind("<Enter>", lambda _: btn.config(bg=hov))
        btn.bind("<Leave>", lambda _: btn.config(bg=bg))
        return btn

    def _small_btn(self, parent, text, command):
        bg, hov = T.BG3, T.BG4
        btn = tk.Button(parent, text=text, command=command,
                         bg=bg, fg=T.FG, activebackground=hov, activeforeground=T.FG,
                         relief=tk.FLAT, cursor="hand2", font=T.FONT_SMALL,
                         padx=6, pady=2, bd=0)
        btn.bind("<Enter>", lambda _: btn.config(bg=hov))
        btn.bind("<Leave>", lambda _: btn.config(bg=bg))
        return btn

    # ── action list management ─────────────────────────────────────────────────

    def _sync_rows(self):
        """Read current tk var values back into each row's vals dict."""
        for row in self._action_rows:
            tvars = row.get("tvars", {})
            if not tvars:
                continue
            atype = row["type"]
            for fname, ftype, _ in _F.get(atype, []):
                if ftype == "actions":
                    continue
                elif ftype == "color":
                    rv, gv, bv = tvars.get("color_r"), tvars.get("color_g"), tvars.get("color_b")
                    if rv is not None:
                        try:
                            row["vals"]["color"] = [
                                max(0, min(255, int(rv.get() or 0))),
                                max(0, min(255, int(gv.get() or 0))),
                                max(0, min(255, int(bv.get() or 0))),
                            ]
                        except (ValueError, TypeError):
                            pass
                elif ftype == "bool":
                    v = tvars.get(fname)
                    if v is not None:
                        row["vals"][fname] = bool(v.get())
                elif ftype == "int":
                    v = tvars.get(fname)
                    if v is not None:
                        try:
                            row["vals"][fname] = int(v.get())
                        except ValueError:
                            pass
                elif ftype == "float":
                    v = tvars.get(fname)
                    if v is not None:
                        try:
                            row["vals"][fname] = float(v.get())
                        except ValueError:
                            pass
                elif ftype == "keys":
                    v = tvars.get(fname)
                    if v is not None:
                        raw = v.get()
                        row["vals"][fname] = [k.strip() for k in raw.split(",") if k.strip()]
                else:  # str, choice:..., template
                    v = tvars.get(fname)
                    if v is not None:
                        row["vals"][fname] = v.get()

    def _rebuild_list(self):
        """Sync vars, destroy existing cards, rebuild from current _action_rows."""
        self._sync_rows()
        for w in self._list_frame.winfo_children():
            w.destroy()
        for row in self._action_rows:
            row["tvars"] = {}

        if not self._action_rows:
            tk.Label(
                self._list_frame,
                text="No actions yet.\nClick  ＋ Add Action  to get started.",
                font=T.FONT_SMALL, bg=T.BG, fg=T.FG_DIM, justify=tk.CENTER,
            ).pack(pady=40)
        else:
            for i in range(len(self._action_rows)):
                self._build_card(self._list_frame, i).pack(fill=tk.X, padx=2, pady=3)

        self._count_lbl.config(text=str(len(self._action_rows)))
        _bind_wheel_recursive(self._list_frame, self._list_wheel_fn)
        self._list_frame.update_idletasks()
        self._list_canvas.configure(scrollregion=self._list_canvas.bbox("all"))

    def _build_card(self, parent, index: int) -> tk.Frame:
        row   = self._action_rows[index]
        atype = row["type"]
        accent = _COLOR.get(atype, T.BG3)
        n = len(self._action_rows)

        outer = tk.Frame(parent, bg=T.BORDER, padx=1, pady=1)
        card  = tk.Frame(outer, bg=T.BG2)
        card.pack(fill=tk.BOTH, expand=True)

        # left colour stripe
        tk.Frame(card, bg=accent, width=5).pack(side=tk.LEFT, fill=tk.Y)

        body = tk.Frame(card, bg=T.BG2)
        body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=5)

        # ── header row: type badge  +  control buttons ─────────────────────────
        hdr = tk.Frame(body, bg=T.BG2)
        hdr.pack(fill=tk.X)

        # type badge – click to change type
        badge = tk.Button(
            hdr, text=_ICON.get(atype, atype),
            bg=accent, fg="#ffffff",
            activebackground=accent, activeforeground="#ffffff",
            relief=tk.FLAT, cursor="hand2",
            font=T.FONT_SMALL, padx=8, pady=2, bd=0,
        )
        badge.config(command=lambda i=index: self._change_type(i))
        badge.pack(side=tk.LEFT)

        # control buttons  ↑ ↓ ✕
        ctrl = tk.Frame(hdr, bg=T.BG2)
        ctrl.pack(side=tk.RIGHT)

        def _make_ctrl(txt, cmd, enabled):
            fg = T.FG if enabled else T.FG_DIM
            b = tk.Button(ctrl, text=txt,
                           command=cmd if enabled else lambda: None,
                           bg=T.BG2, fg=fg,
                           activebackground=T.BG3, activeforeground=T.FG,
                           relief=tk.FLAT,
                           cursor="hand2" if enabled else "arrow",
                           font=T.FONT_SMALL, padx=5, pady=1, bd=0)
            b.pack(side=tk.LEFT)

        _make_ctrl("↑", lambda i=index: self._move_action(i, -1), index > 0)
        _make_ctrl("↓", lambda i=index: self._move_action(i, 1),  index < n - 1)
        _make_ctrl("✕", lambda i=index: self._delete_action(i),   True)

        # ── fields row ─────────────────────────────────────────────────────────
        frow = tk.Frame(body, bg=T.BG2)
        frow.pack(fill=tk.X, pady=(4, 0))

        tvars = {}
        self._build_field_widgets(frow, row, atype, tvars, index)
        row["tvars"] = tvars

        return outer

    def _build_field_widgets(self, parent, row, atype, tvars, row_index):
        vals = row.get("vals", {})
        sub  = row.get("sub",  {})

        for fname, ftype, fdefault in _F.get(atype, []):
            current = vals.get(fname, fdefault)

            # ── branch (sub-action list) ────────────────────────────────────────
            if ftype == "actions":
                branch_list = sub.get(fname, [])
                count = len(branch_list)

                bf = tk.Frame(parent, bg=T.BG2)
                bf.pack(side=tk.LEFT, padx=(0, 8))

                # Branch button with count badge
                btn_text = fname.replace("_", " ")
                def _open(f=fname, i=row_index):
                    self._edit_sub_actions(i, f)

                btn = tk.Button(bf, text=btn_text, command=_open,
                                 bg=T.BG3, fg=T.ACCENT_LT,
                                 activebackground=T.BG4, activeforeground=T.ACCENT_LT,
                                 relief=tk.FLAT, cursor="hand2",
                                 font=T.FONT_SMALL, padx=8, pady=2, bd=0)
                btn.pack(side=tk.LEFT)

                # Count badge
                badge_bg = T.ACCENT if count > 0 else T.BG3
                badge_fg = T.FG if count > 0 else T.FG_DIM
                tk.Label(bf, text=str(count), font=T.FONT_SMALL,
                         bg=badge_bg, fg=badge_fg, padx=4).pack(side=tk.LEFT, padx=(2, 0))

                # Inline summary of actions
                if count > 0:
                    summary = ", ".join(a.get("type", "?") for a in branch_list[:4])
                    if count > 4:
                        summary += f" +{count - 4}"
                    tk.Label(bf, text=summary, font=T.FONT_SMALL,
                             bg=T.BG2, fg=T.FG_DIM).pack(side=tk.LEFT, padx=(4, 0))

                continue

            # field label
            tk.Label(parent, text=fname, font=T.FONT_SMALL,
                     bg=T.BG2, fg=T.FG_DIM).pack(side=tk.LEFT, padx=(0, 2))

            # ── int / float ─────────────────────────────────────────────────────
            if ftype in ("int", "float"):
                var = tk.StringVar(value=str(current))
                tk.Entry(parent, textvariable=var, bg=T.BG3, fg=T.FG,
                          insertbackground=T.FG, relief=tk.FLAT,
                          font=T.FONT, width=6).pack(side=tk.LEFT, padx=(0, 10))
                tvars[fname] = var

            # ── plain string ────────────────────────────────────────────────────
            elif ftype == "str":
                var = tk.StringVar(value=str(current))
                tk.Entry(parent, textvariable=var, bg=T.BG3, fg=T.FG,
                          insertbackground=T.FG, relief=tk.FLAT,
                          font=T.FONT, width=20).pack(side=tk.LEFT, padx=(0, 10))
                tvars[fname] = var

            # ── dropdown ────────────────────────────────────────────────────────
            elif ftype.startswith("choice:"):
                choices = ftype.split(":")[1].split(",")
                var = tk.StringVar(value=str(current))
                om = tk.OptionMenu(parent, var, *choices)
                om.config(bg=T.BG3, fg=T.FG,
                           activebackground=T.BG4, activeforeground=T.FG,
                           relief=tk.FLAT, font=T.FONT_SMALL, padx=4, pady=1,
                           highlightthickness=0, bd=0)
                om["menu"].config(bg=T.BG3, fg=T.FG, activebackground=T.ACCENT)
                om.pack(side=tk.LEFT, padx=(0, 10))
                tvars[fname] = var

            # ── checkbox ────────────────────────────────────────────────────────
            elif ftype == "bool":
                var = tk.BooleanVar(value=bool(current))
                tk.Checkbutton(parent, variable=var,
                                bg=T.BG2, fg=T.FG,
                                selectcolor=T.BG3,
                                activebackground=T.BG2, activeforeground=T.FG,
                                relief=tk.FLAT).pack(side=tk.LEFT, padx=(0, 10))
                tvars[fname] = var

            # ── comma-separated keys ────────────────────────────────────────────
            elif ftype == "keys":
                if isinstance(current, list):
                    current = ", ".join(current)
                var = tk.StringVar(value=str(current))
                tk.Entry(parent, textvariable=var, bg=T.BG3, fg=T.FG,
                          insertbackground=T.FG, relief=tk.FLAT,
                          font=T.FONT, width=16).pack(side=tk.LEFT, padx=(0, 10))
                tvars[fname] = var

            # ── RGB colour ──────────────────────────────────────────────────────
            elif ftype == "color":
                c = current if isinstance(current, (list, tuple)) and len(current) == 3 \
                    else [255, 0, 0]
                rv = tk.StringVar(value=str(c[0]))
                gv = tk.StringVar(value=str(c[1]))
                bv = tk.StringVar(value=str(c[2]))

                cf = tk.Frame(parent, bg=T.BG2)
                cf.pack(side=tk.LEFT, padx=(0, 10))
                for ch_lbl, ch_var in [("R", rv), ("G", gv), ("B", bv)]:
                    tk.Label(cf, text=ch_lbl, font=T.FONT_SMALL,
                             bg=T.BG2, fg=T.FG_DIM).pack(side=tk.LEFT)
                    tk.Entry(cf, textvariable=ch_var, bg=T.BG3, fg=T.FG,
                              insertbackground=T.FG, relief=tk.FLAT,
                              font=T.FONT, width=4).pack(side=tk.LEFT, padx=(1, 4))

                try:
                    hex_c = "#{:02x}{:02x}{:02x}".format(c[0], c[1], c[2])
                except Exception:
                    hex_c = "#ff0000"
                tk.Label(cf, bg=hex_c, width=2, relief=tk.FLAT).pack(side=tk.LEFT)

                tvars["color_r"] = rv
                tvars["color_g"] = gv
                tvars["color_b"] = bv

            # ── template file path ──────────────────────────────────────────────
            elif ftype == "template":
                var = tk.StringVar(value=str(current))
                tf = tk.Frame(parent, bg=T.BG2)
                tf.pack(side=tk.LEFT, padx=(0, 10))
                tk.Entry(tf, textvariable=var, bg=T.BG3, fg=T.FG,
                          insertbackground=T.FG, relief=tk.FLAT,
                          font=T.FONT, width=24).pack(side=tk.LEFT)

                def _browse(v=var):
                    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
                    f = filedialog.askopenfilename(
                        parent=self,
                        title="Select template image",
                        initialdir=str(TEMPLATES_DIR),
                        filetypes=[("PNG", "*.png"), ("Images", "*.png *.jpg *.bmp"), ("All", "*.*")],
                    )
                    if f:
                        try:
                            rel = Path(f).relative_to(root)
                            v.set(str(rel).replace("\\", "/"))
                        except ValueError:
                            v.set(f)

                browse_btn = tk.Button(tf, text="📁", command=_browse,
                                        bg=T.BG3, fg=T.FG,
                                        activebackground=T.BG4, activeforeground=T.FG,
                                        relief=tk.FLAT, cursor="hand2",
                                        font=T.FONT_SMALL, padx=5, pady=1, bd=0)
                browse_btn.pack(side=tk.LEFT, padx=(3, 0))
                tvars[fname] = var

    # ── action operations ──────────────────────────────────────────────────────

    def _show_type_picker(self, title="Add Action", on_select=None):
        """Show a grouped type-picker popup (resizable, scrollable)."""
        popup = tk.Toplevel(self)
        popup.title(title)
        popup.configure(bg=T.BG)
        popup.resizable(True, True)
        popup.minsize(360, 300)
        popup.transient(self)
        T.center_on_parent(popup, self, 460, 520)
        popup.grab_set()

        def _on_pick(t):
            popup.destroy()
            if on_select:
                on_select(t)
            else:
                self._add_action(t)

        _build_type_picker_body(popup, title, on_pick=_on_pick)

    def _add_action(self, atype: str):
        self._sync_rows()
        fields = _F.get(atype, [])
        vals, sub = {}, {}
        for fname, ftype, fdefault in fields:
            if ftype == "actions":
                sub[fname] = []
            else:
                vals[fname] = fdefault
        self._action_rows.append({"type": atype, "vals": vals, "sub": sub, "tvars": {}})
        self._rebuild_list()
        self._list_canvas.update_idletasks()
        self._list_canvas.yview_moveto(1.0)

    def _delete_action(self, index: int):
        self._sync_rows()
        self._action_rows.pop(index)
        self._rebuild_list()

    def _move_action(self, index: int, direction: int):
        self._sync_rows()
        r = self._action_rows
        new_i = index + direction
        if 0 <= new_i < len(r):
            r[index], r[new_i] = r[new_i], r[index]
        self._rebuild_list()

    def _change_type(self, index: int):
        def _apply(new_type):
            self._sync_rows()
            fields = _F.get(new_type, [])
            vals, sub = {}, {}
            for fname, ftype, fdefault in fields:
                if ftype == "actions":
                    sub[fname] = []
                else:
                    vals[fname] = fdefault
            self._action_rows[index] = {"type": new_type, "vals": vals, "sub": sub, "tvars": {}}
            self._rebuild_list()

        self._show_type_picker(title="Change Action Type", on_select=_apply)

    def _edit_sub_actions(self, row_index: int, branch_name: str):
        row       = self._action_rows[row_index]
        sub_list  = row.get("sub", {}).get(branch_name, [])
        SubActionsDialog(
            parent=self,
            title=f"{row['type']}  →  {branch_name}",
            actions=list(sub_list),
            on_save=lambda lst: self._on_sub_saved(row_index, branch_name, lst),
        )

    def _on_sub_saved(self, row_index: int, branch_name: str, new_list: list):
        self._sync_rows()
        self._action_rows[row_index].setdefault("sub", {})[branch_name] = new_list
        self._rebuild_list()

    # ── load / collect ─────────────────────────────────────────────────────────

    def _load_macro(self, macro: dict):
        self._name_var.set(macro.get("name", "my_macro"))
        self._desc_var.set(macro.get("description", ""))

        trigger = macro.get("trigger", {})
        self._hotkey_var.set(", ".join(trigger.get("keys", [])))
        self._loop_var.set(bool(macro.get("loop", False)))
        self._loop_delay_var.set(str(macro.get("loop_delay_ms", 0)))
        self._bg_var.set(bool(macro.get("background", False)))
        self._target_var.set(macro.get("target_window", ""))
        self._target_hwnd = macro.get("target_hwnd", None)

        self._action_rows = []
        for action in macro.get("actions", []):
            atype  = action.get("type", "wait")
            fields = _F.get(atype, [])
            vals, sub = {}, {}
            for fname, ftype, fdefault in fields:
                if ftype == "actions":
                    sub[fname] = action.get(fname, [])
                else:
                    vals[fname] = action.get(fname, fdefault)
            self._action_rows.append({"type": atype, "vals": vals, "sub": sub, "tvars": {}})
        self._rebuild_list()

    def _collect_macro(self) -> dict:
        self._sync_rows()

        macro: dict = {"name": self._name_var.get().strip() or "my_macro"}

        desc = self._desc_var.get().strip()
        if desc:
            macro["description"] = desc

        hotkey = self._hotkey_var.get().strip()
        if hotkey:
            keys = [k.strip() for k in hotkey.replace("+", ",").split(",") if k.strip()]
            if keys:
                macro["trigger"] = {"type": "hotkey", "keys": keys}

        macro["loop"] = self._loop_var.get()
        try:
            macro["loop_delay_ms"] = int(self._loop_delay_var.get())
        except ValueError:
            macro["loop_delay_ms"] = 0

        macro["background"] = self._bg_var.get()
        tgt = self._target_var.get().strip()
        if tgt:
            macro["target_window"] = tgt
        if self._target_hwnd is not None:
            macro["target_hwnd"] = self._target_hwnd

        macro["actions"] = self._collect_actions()
        return macro

    def _collect_actions(self) -> list:
        result = []
        for row in self._action_rows:
            atype  = row["type"]
            action = {"type": atype}
            for fname, ftype, _ in _F.get(atype, []):
                if ftype == "actions":
                    action[fname] = row.get("sub", {}).get(fname, [])
                else:
                    action[fname] = row["vals"].get(fname)
            result.append(action)
        return result

    # ── tools ─────────────────────────────────────────────────────────────────

    def _pick_pixel(self):
        self.withdraw()
        # When background mode is on and a target is set, resolve the hwnd so
        # the picker shows window-relative coords and returns client-space values.
        hwnd = self._resolve_target_hwnd()
        self._picker.start(hwnd=hwnd)

    def _on_pixel_picked(self, x, y, color):
        self.deiconify()
        if x is None:
            return
        r, g, b = color
        in_bg = bool(self._bg_var.get() and self._target_var.get().strip())
        coord_note = "window-relative (client)" if in_bg else "screen (absolute)"
        self._sync_rows()
        self._action_rows.append({
            "type": "pixel_check",
            "vals": {"x": x, "y": y, "color": [r, g, b], "tolerance": 10},
            "sub":  {"on_match": [], "on_no_match": []},
            "tvars": {},
        })
        self._rebuild_list()
        messagebox.showinfo(
            "Pixel picked",
            f"{coord_note}\nx={x}, y={y}   color=[{r}, {g}, {b}]\n\n"
            "Added as a pixel_check action.",
            parent=self,
        )

    def _resolve_target_hwnd(self) -> "Optional[int]":
        """Return the hwnd for the target window if background mode is on."""
        if not self._bg_var.get():
            return None
        # Prefer the exact hwnd from the window picker
        if self._target_hwnd is not None:
            from engine.background_input import is_window_valid
            if is_window_valid(self._target_hwnd):
                return self._target_hwnd
        # Fall back to title-based search
        target = self._target_var.get().strip()
        if not target:
            return None
        try:
            from engine.background_input import find_window
            hwnd = find_window(target)
            if hwnd is None:
                messagebox.showwarning(
                    "Window not found",
                    f"Could not find window matching  '{target}'.\n"
                    "Falling back to screen coordinates.\n\n"
                    "Make sure the target window is open and its title\n"
                    "is set correctly in the Background Mode field.",
                    parent=self,
                )
            return hwnd
        except Exception:
            return None

    def _capture_region(self):
        from gui.region_capture import RegionCapture
        self.withdraw()
        RegionCapture(self.master, self._on_region_captured).start()

    def _on_region_captured(self, img, x, y, w, h):
        self.deiconify()
        if img is None:
            return
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

        # Ask for a meaningful name so templates aren't anonymous timestamps.
        # Blank/cancel falls back to a timestamp (never blocks the capture).
        entered = prompt_text(
            self, "Name this template",
            "Template name (blank = auto):",
            ok_text="Save",
        )
        if entered:
            name = ts.unique_name(f"{ts.sanitize_stem(entered)}.png")
        else:
            name = f"region_{int(time.time())}.png"

        img.save(str(TEMPLATES_DIR / name))
        rel = f"templates/{name}"

        self._sync_rows()
        self._action_rows.append({
            "type": "find_and_click",
            "vals": {"template": rel, "button": "left", "threshold": 0.80},
            "sub":  {"on_found": [], "on_not_found": []},
            "tvars": {},
        })
        self._rebuild_list()
        messagebox.showinfo(
            "Region captured",
            f"Saved  {rel}\n\nAdded as a find_and_click action.",
            parent=self,
        )

    def _pick_window(self):
        from engine.background_input import list_windows
        windows = list_windows()
        if not windows:
            messagebox.showinfo("No Windows", "No visible windows found.", parent=self)
            return

        WindowPicker(self, windows, self._on_window_picked)

    def _on_window_picked(self, hwnd: int, title: str):
        """Called when user selects a window from the picker."""
        self._target_var.set(title)
        self._target_hwnd = hwnd
        self._bg_var.set(True)

    # ── save / close ───────────────────────────────────────────────────────────

    def _save(self):
        try:
            macro = self._collect_macro()
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)
            return
        try:
            self._save_callback(macro)
            self.destroy()
        except Exception as exc:
            messagebox.showerror("Save Error", str(exc), parent=self)

    def destroy(self):
        super().destroy()


# ── Sub-action editor (visual branch editor) ─────────────────────────────────

class SubActionsDialog(tk.Toplevel):
    """
    Visual editor for a branch action list (on_match, on_found, …).

    Shows the same card-based UI as the main editor, with Add/Delete/Reorder.
    OK saves the branch back to the parent; Cancel discards changes.
    """

    def __init__(self, parent, title: str, actions: list, on_save: Callable):
        super().__init__(parent)
        self.title(f"Branch: {title}")
        self.configure(bg=T.BG)
        T.center_on_parent(self, parent, 700, 500)
        self.transient(parent)
        self.grab_set()
        self._on_save = on_save
        self._rows: List[Dict] = []

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=T.BG2)
        hdr.pack(fill=tk.X)
        inner_h = tk.Frame(hdr, bg=T.BG2)
        inner_h.pack(fill=tk.X, padx=14, pady=8)
        tk.Label(inner_h, text=title, font=T.FONT_BOLD,
                 bg=T.BG2, fg=T.FG).pack(side=tk.LEFT)
        self._count_lbl = tk.Label(inner_h, text="0", font=T.FONT_SMALL,
                                    bg=T.ACCENT, fg=T.FG, padx=6)
        self._count_lbl.pack(side=tk.LEFT, padx=8)

        # Add + JSON toggle
        add_btn = tk.Button(
            inner_h, text="＋ Add", command=self._show_type_picker,
            bg=T.ACCENT, fg=T.FG, activebackground=T.ACCENT_LT,
            activeforeground=T.FG, relief=tk.FLAT, cursor="hand2",
            font=T.FONT, padx=8, pady=2, bd=0)
        add_btn.pack(side=tk.LEFT, padx=4)
        json_btn = tk.Button(
            inner_h, text="JSON", command=self._toggle_json,
            bg=T.BG3, fg=T.FG_DIM, activebackground=T.BG4,
            activeforeground=T.FG, relief=tk.FLAT, cursor="hand2",
            font=T.FONT_SMALL, padx=6, pady=2, bd=0)
        json_btn.pack(side=tk.LEFT, padx=2)

        tk.Frame(hdr, bg=T.SEP, height=1).pack(fill=tk.X, side=tk.BOTTOM)

        # ── Scrollable action list ────────────────────────────────────────────
        container = tk.Frame(self, bg=T.BG)
        container.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(container, bg=T.BG, highlightthickness=0, bd=0)
        sb = tk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        self._list_frame = tk.Frame(canvas, bg=T.BG)
        self._list_frame.bind("<Configure>",
            lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._list_frame, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas = canvas

        def _wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        self._wheel_fn = _wheel

        # ── JSON text area (hidden by default) ────────────────────────────────
        self._json_frame = tk.Frame(self, bg=T.BG)
        from gui.widgets import ScrolledText
        self._txt = ScrolledText(self._json_frame, width=72, height=14)
        self._txt.pack(fill=tk.BOTH, expand=True, padx=14, pady=4)
        self._json_visible = False

        # ── Footer ────────────────────────────────────────────────────────────
        tk.Frame(self, bg=T.SEP, height=1).pack(fill=tk.X)
        foot = tk.Frame(self, bg=T.BG2)
        foot.pack(fill=tk.X)
        inner_f = tk.Frame(foot, bg=T.BG2)
        inner_f.pack(fill=tk.X, padx=14, pady=8)
        Button(inner_f, "OK", command=self._ok, variant="success").pack(side=tk.RIGHT, padx=4)
        Button(inner_f, "Cancel", command=self.destroy, variant="ghost").pack(side=tk.RIGHT, padx=4)

        # ── Load actions ──────────────────────────────────────────────────────
        self._load_actions(actions)
        self._rebuild()

    # ── Load / Collect ────────────────────────────────────────────────────────

    def _load_actions(self, actions: list):
        self._rows = []
        for action in actions:
            atype = action.get("type", "wait")
            fields = _F.get(atype, [])
            vals, sub = {}, {}
            for fname, ftype, fdefault in fields:
                if ftype == "actions":
                    sub[fname] = action.get(fname, [])
                else:
                    vals[fname] = action.get(fname, fdefault)
            self._rows.append({"type": atype, "vals": vals, "sub": sub, "tvars": {}})

    def _collect_actions(self) -> list:
        self._sync_rows()
        result = []
        for row in self._rows:
            atype = row["type"]
            action = {"type": atype}
            for fname, ftype, _ in _F.get(atype, []):
                if ftype == "actions":
                    action[fname] = row.get("sub", {}).get(fname, [])
                else:
                    action[fname] = row["vals"].get(fname)
            result.append(action)
        return result

    def _sync_rows(self):
        for row in self._rows:
            tvars = row.get("tvars", {})
            if not tvars:
                continue
            atype = row["type"]
            for fname, ftype, _ in _F.get(atype, []):
                if ftype == "actions":
                    continue
                elif ftype == "color":
                    rv = tvars.get("color_r")
                    gv = tvars.get("color_g")
                    bv = tvars.get("color_b")
                    if rv is not None:
                        try:
                            row["vals"]["color"] = [
                                max(0, min(255, int(rv.get() or 0))),
                                max(0, min(255, int(gv.get() or 0))),
                                max(0, min(255, int(bv.get() or 0))),
                            ]
                        except (ValueError, TypeError):
                            pass
                elif ftype == "bool":
                    v = tvars.get(fname)
                    if v is not None:
                        row["vals"][fname] = v.get()
                elif ftype == "keys":
                    v = tvars.get(fname)
                    if v is not None:
                        row["vals"][fname] = [
                            k.strip() for k in v.get().replace("+", ",").split(",")
                            if k.strip()
                        ]
                else:
                    v = tvars.get(fname)
                    if v is None:
                        continue
                    raw = v.get()
                    if ftype == "int":
                        try: row["vals"][fname] = int(raw)
                        except: pass
                    elif ftype == "float":
                        try: row["vals"][fname] = float(raw)
                        except: pass
                    else:
                        row["vals"][fname] = raw

    # ── Rebuild visual list ───────────────────────────────────────────────────

    def _rebuild(self):
        for w in self._list_frame.winfo_children():
            w.destroy()
        self._count_lbl.config(text=str(len(self._rows)))

        if not self._rows:
            tk.Label(self._list_frame,
                     text="No actions. Click  ＋ Add  to create one.",
                     font=T.FONT_SMALL, bg=T.BG, fg=T.FG_DIM).pack(pady=20)
        else:
            for i in range(len(self._rows)):
                self._build_row(self._list_frame, i).pack(
                    fill=tk.X, padx=6, pady=2)

        _bind_wheel_recursive(self._list_frame, self._wheel_fn)
        self._list_frame.update_idletasks()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _build_row(self, parent, idx: int) -> tk.Frame:
        row   = self._rows[idx]
        atype = row["type"]
        accent = _COLOR.get(atype, T.BG3)
        n = len(self._rows)

        outer = tk.Frame(parent, bg=T.BORDER, padx=1, pady=1)
        card  = tk.Frame(outer, bg=T.BG2)
        card.pack(fill=tk.BOTH, expand=True)

        # Colour stripe
        tk.Frame(card, bg=accent, width=4).pack(side=tk.LEFT, fill=tk.Y)

        body = tk.Frame(card, bg=T.BG2)
        body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=4)

        # Header: type badge + controls
        hdr = tk.Frame(body, bg=T.BG2)
        hdr.pack(fill=tk.X)

        tk.Label(hdr, text=_ICON.get(atype, atype), font=T.FONT_SMALL,
                 bg=accent, fg="#fff", padx=6, pady=1).pack(side=tk.LEFT)

        ctrl = tk.Frame(hdr, bg=T.BG2)
        ctrl.pack(side=tk.RIGHT)

        if idx > 0:
            b = tk.Button(ctrl, text="↑", command=lambda i=idx: self._move(i, -1),
                          bg=T.BG2, fg=T.FG, activebackground=T.BG3,
                          relief=tk.FLAT, font=T.FONT_SMALL, padx=4, bd=0)
            b.pack(side=tk.LEFT)
        if idx < n - 1:
            b = tk.Button(ctrl, text="↓", command=lambda i=idx: self._move(i, 1),
                          bg=T.BG2, fg=T.FG, activebackground=T.BG3,
                          relief=tk.FLAT, font=T.FONT_SMALL, padx=4, bd=0)
            b.pack(side=tk.LEFT)
        b = tk.Button(ctrl, text="✕", command=lambda i=idx: self._delete(i),
                      bg=T.BG2, fg=T.DANGER, activebackground=T.BG3,
                      relief=tk.FLAT, font=T.FONT_SMALL, padx=4, bd=0)
        b.pack(side=tk.LEFT)

        # Fields
        frow = tk.Frame(body, bg=T.BG2)
        frow.pack(fill=tk.X, pady=(3, 0))

        tvars = {}
        vals = row.get("vals", {})
        sub  = row.get("sub", {})

        for fname, ftype, fdefault in _F.get(atype, []):
            current = vals.get(fname, fdefault)

            if ftype == "actions":
                # Nested branch — show as a button with count
                branch_list = sub.get(fname, [])
                count = len(branch_list)
                btn_text = fname.replace("_", " ")

                def _open_nested(f=fname, i=idx):
                    self._edit_nested(i, f)

                nbf = tk.Frame(frow, bg=T.BG2)
                nbf.pack(side=tk.LEFT, padx=(0, 6))
                nb = tk.Button(nbf, text=f"{btn_text} ({count})",
                               command=_open_nested,
                               bg=T.BG3, fg=T.ACCENT_LT,
                               activebackground=T.BG4,
                               relief=tk.FLAT, cursor="hand2",
                               font=T.FONT_SMALL, padx=6, pady=1, bd=0)
                nb.pack(side=tk.LEFT)
                continue

            # Simple field label
            tk.Label(frow, text=fname, font=T.FONT_SMALL,
                     bg=T.BG2, fg=T.FG_DIM).pack(side=tk.LEFT, padx=(0, 2))

            if ftype == "int":
                var = tk.StringVar(value=str(current))
                tk.Entry(frow, textvariable=var, bg=T.BG3, fg=T.FG,
                         insertbackground=T.FG, relief=tk.FLAT,
                         font=T.FONT, width=6).pack(side=tk.LEFT, padx=(0, 8))
                tvars[fname] = var
            elif ftype == "float":
                var = tk.StringVar(value=str(current))
                tk.Entry(frow, textvariable=var, bg=T.BG3, fg=T.FG,
                         insertbackground=T.FG, relief=tk.FLAT,
                         font=T.FONT, width=6).pack(side=tk.LEFT, padx=(0, 8))
                tvars[fname] = var
            elif ftype == "str":
                var = tk.StringVar(value=str(current))
                tk.Entry(frow, textvariable=var, bg=T.BG3, fg=T.FG,
                         insertbackground=T.FG, relief=tk.FLAT,
                         font=T.FONT, width=14).pack(side=tk.LEFT, padx=(0, 8))
                tvars[fname] = var
            elif ftype == "bool":
                var = tk.BooleanVar(value=bool(current))
                tk.Checkbutton(frow, variable=var, bg=T.BG2, fg=T.FG,
                               selectcolor=T.BG3, activebackground=T.BG2,
                               relief=tk.FLAT).pack(side=tk.LEFT, padx=(0, 8))
                tvars[fname] = var
            elif ftype.startswith("choice:"):
                options = ftype.split(":", 1)[1].split(",")
                var = tk.StringVar(value=str(current))
                om = tk.OptionMenu(frow, var, *options)
                om.configure(bg=T.BG3, fg=T.FG, activebackground=T.BG4,
                             relief=tk.FLAT, font=T.FONT_SMALL, padx=4,
                             highlightthickness=0, bd=0)
                om["menu"].config(bg=T.BG3, fg=T.FG, activebackground=T.ACCENT)
                om.pack(side=tk.LEFT, padx=(0, 8))
                tvars[fname] = var
            elif ftype == "keys":
                if isinstance(current, list):
                    current = ", ".join(current)
                var = tk.StringVar(value=str(current))
                tk.Entry(frow, textvariable=var, bg=T.BG3, fg=T.FG,
                         insertbackground=T.FG, relief=tk.FLAT,
                         font=T.FONT, width=14).pack(side=tk.LEFT, padx=(0, 8))
                tvars[fname] = var
            elif ftype == "template":
                var = tk.StringVar(value=str(current))
                tf = tk.Frame(frow, bg=T.BG2)
                tf.pack(side=tk.LEFT, padx=(0, 8))
                tk.Entry(tf, textvariable=var, bg=T.BG3, fg=T.FG,
                         insertbackground=T.FG, relief=tk.FLAT,
                         font=T.FONT, width=20).pack(side=tk.LEFT)

                def _browse(v=var):
                    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
                    f = filedialog.askopenfilename(
                        parent=self,
                        title="Select template image",
                        initialdir=str(TEMPLATES_DIR),
                        filetypes=[("PNG", "*.png"), ("Images", "*.png *.jpg *.bmp"), ("All", "*.*")],
                    )
                    if f:
                        try:
                            rel = Path(f).relative_to(root)
                            v.set(str(rel).replace("\\", "/"))
                        except ValueError:
                            v.set(f)

                tk.Button(tf, text="...", command=_browse,
                          bg=T.BG3, fg=T.FG, activebackground=T.BG4,
                          relief=tk.FLAT, cursor="hand2",
                          font=T.FONT_SMALL, padx=5, pady=1, bd=0
                          ).pack(side=tk.LEFT, padx=(3, 0))
                tvars[fname] = var
            elif ftype == "color":
                c = current if isinstance(current, (list, tuple)) and len(current) == 3 \
                    else [255, 0, 0]
                rv = tk.StringVar(value=str(c[0]))
                gv = tk.StringVar(value=str(c[1]))
                bv = tk.StringVar(value=str(c[2]))
                cf = tk.Frame(frow, bg=T.BG2)
                cf.pack(side=tk.LEFT, padx=(0, 8))
                for ch_lbl, ch_var in [("R", rv), ("G", gv), ("B", bv)]:
                    tk.Label(cf, text=ch_lbl, font=T.FONT_SMALL,
                             bg=T.BG2, fg=T.FG_DIM).pack(side=tk.LEFT)
                    tk.Entry(cf, textvariable=ch_var, bg=T.BG3, fg=T.FG,
                             insertbackground=T.FG, relief=tk.FLAT,
                             font=T.FONT, width=4).pack(side=tk.LEFT, padx=(1, 3))
                tvars["color_r"] = rv
                tvars["color_g"] = gv
                tvars["color_b"] = bv

        row["tvars"] = tvars
        return outer

    # ── Actions ───────────────────────────────────────────────────────────────

    def _show_type_picker(self):
        popup = tk.Toplevel(self)
        popup.title("Add Action")
        popup.configure(bg=T.BG)
        popup.resizable(True, True)
        popup.minsize(360, 300)
        popup.transient(self)
        T.center_on_parent(popup, self, 460, 520)
        popup.grab_set()

        def _on_pick(t):
            popup.destroy()
            self._add_action(t)

        _build_type_picker_body(popup, "Add Action", on_pick=_on_pick)

    def _add_action(self, atype: str):
        self._sync_rows()
        fields = _F.get(atype, [])
        vals, sub = {}, {}
        for fname, ftype, fdefault in fields:
            if ftype == "actions":
                sub[fname] = []
            else:
                vals[fname] = fdefault
        self._rows.append({"type": atype, "vals": vals, "sub": sub, "tvars": {}})
        self._rebuild()

    def _delete(self, idx: int):
        self._sync_rows()
        self._rows.pop(idx)
        self._rebuild()

    def _move(self, idx: int, direction: int):
        self._sync_rows()
        new_i = idx + direction
        if 0 <= new_i < len(self._rows):
            self._rows[idx], self._rows[new_i] = self._rows[new_i], self._rows[idx]
        self._rebuild()

    def _edit_nested(self, row_idx: int, branch_name: str):
        """Open another SubActionsDialog for deeply nested branches."""
        self._sync_rows()
        row = self._rows[row_idx]
        sub_list = row.get("sub", {}).get(branch_name, [])
        SubActionsDialog(
            parent=self,
            title=f"{row['type']}  →  {branch_name}",
            actions=list(sub_list),
            on_save=lambda lst: self._on_nested_saved(row_idx, branch_name, lst),
        )

    def _on_nested_saved(self, row_idx: int, branch_name: str, new_list: list):
        self._sync_rows()
        self._rows[row_idx].setdefault("sub", {})[branch_name] = new_list
        self._rebuild()

    # ── JSON toggle ───────────────────────────────────────────────────────────

    def _toggle_json(self):
        if self._json_visible:
            # Parse JSON back into visual rows
            raw = self._txt.get("1.0", tk.END).strip()
            try:
                data = json.loads(raw)
                if not isinstance(data, list):
                    raise ValueError("Must be a JSON array")
                self._load_actions(data)
            except (json.JSONDecodeError, ValueError) as exc:
                messagebox.showerror("JSON Error", str(exc), parent=self)
                return
            self._json_frame.pack_forget()
            self._canvas.master.pack(fill=tk.BOTH, expand=True)
            self._json_visible = False
            self._rebuild()
        else:
            # Sync visual → JSON
            actions = self._collect_actions()
            self._txt.delete("1.0", tk.END)
            self._txt.insert("1.0", json.dumps(actions, indent=2))
            self._canvas.master.pack_forget()
            self._json_frame.pack(fill=tk.BOTH, expand=True)
            self._json_visible = True

    # ── OK / Cancel ───────────────────────────────────────────────────────────

    def _ok(self):
        if self._json_visible:
            # Parse from JSON mode
            raw = self._txt.get("1.0", tk.END).strip()
            try:
                data = json.loads(raw)
                if not isinstance(data, list):
                    raise ValueError("Must be a JSON array")
            except (json.JSONDecodeError, ValueError) as exc:
                messagebox.showerror("JSON Error", str(exc), parent=self)
                return
            self._on_save(data)
        else:
            self._on_save(self._collect_actions())
        self.destroy()


# ── Window picker with thumbnails ────────────────────────────────────────────

class WindowPicker(tk.Toplevel):
    """
    Shows all visible windows with thumbnail previews.
    Duplicate titles are distinguishable by their preview + hwnd.
    """

    THUMB_W = 180
    THUMB_H = 110

    def __init__(self, parent, windows, on_pick):
        """
        windows: [(hwnd, title), …]
        on_pick: callback(hwnd, title)
        """
        super().__init__(parent)
        self.title("Select Target Window")
        self.configure(bg=T.BG)
        T.center_on_parent(self, parent, 680, 520)
        self.minsize(500, 350)
        self.grab_set()
        self.transient(parent)

        self._windows = windows
        self._on_pick = on_pick
        self._selected_idx: Optional[int] = None
        self._thumb_images = []  # prevent GC

        tk.Label(self, text="Select the window this macro will control:",
                 font=T.FONT, bg=T.BG, fg=T.FG).pack(anchor="w", padx=14, pady=(12, 4))

        # ── Scrollable card grid ──────────────────────────────────────────────
        container = tk.Frame(self, bg=T.BG)
        container.pack(fill=tk.BOTH, expand=True, padx=14, pady=4)

        canvas = tk.Canvas(container, bg=T.BG, highlightthickness=0, borderwidth=0)
        sb = tk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        self._inner = tk.Frame(canvas, bg=T.BG)

        self._inner.bind("<Configure>", lambda _: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def _wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        _bind_wheel_recursive(canvas, _wheel)
        _bind_wheel_recursive(self._inner, _wheel)

        # ── Footer buttons ────────────────────────────────────────────────────
        foot = tk.Frame(self, bg=T.BG)
        foot.pack(fill=tk.X, padx=14, pady=8)
        self._refresh_btn = Button(foot, "Refresh", command=self._refresh, variant="ghost")
        self._refresh_btn.pack(side=tk.LEFT, padx=4)
        self._select_btn = Button(foot, "Select", command=self._confirm, variant="success")
        self._select_btn.pack(side=tk.RIGHT, padx=4)
        Button(foot, "Cancel", command=self.destroy, variant="ghost").pack(side=tk.RIGHT)

        self._populate()

    def _populate(self):
        from PIL import ImageGrab, ImageTk, Image as PILImage
        import win32gui

        # Clear old
        for w in self._inner.winfo_children():
            w.destroy()
        self._thumb_images.clear()
        self._cards = []
        self._selected_idx = None

        for idx, (hwnd, title) in enumerate(self._windows):
            card = tk.Frame(self._inner, bg=T.BG2, bd=1, relief=tk.FLAT,
                            highlightthickness=2, highlightbackground=T.BG2,
                            cursor="hand2")
            card.pack(fill=tk.X, padx=4, pady=3)
            self._cards.append(card)

            inner = tk.Frame(card, bg=T.BG2)
            inner.pack(fill=tk.X, padx=8, pady=6)

            # Thumbnail
            thumb_frame = tk.Frame(inner, bg="#000000", width=self.THUMB_W,
                                   height=self.THUMB_H)
            thumb_frame.pack(side=tk.LEFT, padx=(0, 10))
            thumb_frame.pack_propagate(False)

            thumb_lbl = tk.Label(thumb_frame, bg="#000000")
            thumb_lbl.pack(fill=tk.BOTH, expand=True)

            # Capture thumbnail
            try:
                cx0, cy0 = win32gui.ClientToScreen(hwnd, (0, 0))
                left, top, right, bottom = win32gui.GetClientRect(hwnd)
                w, h = right - left, bottom - top
                if w > 0 and h > 0:
                    img = ImageGrab.grab(bbox=(cx0, cy0, cx0 + w, cy0 + h), all_screens=True)
                    img.thumbnail((self.THUMB_W, self.THUMB_H), PILImage.LANCZOS)
                    tk_img = ImageTk.PhotoImage(img)
                    thumb_lbl.configure(image=tk_img)
                    self._thumb_images.append(tk_img)
                else:
                    thumb_lbl.configure(text="(no preview)", fg="#666666",
                                        font=T.FONT_SMALL)
            except Exception:
                thumb_lbl.configure(text="(no preview)", fg="#666666",
                                    font=T.FONT_SMALL)

            # Info
            info = tk.Frame(inner, bg=T.BG2)
            info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            tk.Label(info, text=title, font=T.FONT_BOLD, bg=T.BG2, fg=T.FG,
                     anchor="w", wraplength=350).pack(anchor="w")

            # Window details
            try:
                cx0, cy0 = win32gui.ClientToScreen(hwnd, (0, 0))
                left, top, right, bottom = win32gui.GetClientRect(hwnd)
                w, h = right - left, bottom - top
                detail = f"hwnd: {hwnd}   |   {w} x {h} px   |   pos: ({cx0}, {cy0})"
            except Exception:
                detail = f"hwnd: {hwnd}"

            tk.Label(info, text=detail, font=T.FONT_SMALL, bg=T.BG2,
                     fg=T.FG_DIM, anchor="w").pack(anchor="w", pady=(2, 0))

            # Duplicate indicator
            dup_count = sum(1 for _, t in self._windows if t == title)
            if dup_count > 1:
                tk.Label(info, text=f"({dup_count} windows with this name)",
                         font=T.FONT_SMALL, bg=T.BG2, fg="#e8a838",
                         anchor="w").pack(anchor="w", pady=(2, 0))

            # Click handlers
            def _select(i=idx):
                self._select_card(i)

            def _dblclick(i=idx):
                self._select_card(i)
                self._confirm()

            for widget in [card, inner, info, thumb_frame, thumb_lbl]:
                widget.bind("<Button-1>", lambda _, i=idx: _select(i))
                widget.bind("<Double-Button-1>", lambda _, i=idx: _dblclick(i))
            for child in info.winfo_children():
                child.bind("<Button-1>", lambda _, i=idx: _select(i))
                child.bind("<Double-Button-1>", lambda _, i=idx: _dblclick(i))

        _bind_wheel_recursive(self._inner,
                              lambda e: self._inner.master.yview_scroll(
                                  int(-1 * (e.delta / 120)), "units"))

    def _select_card(self, idx):
        # Deselect previous
        if self._selected_idx is not None and self._selected_idx < len(self._cards):
            self._cards[self._selected_idx].configure(highlightbackground=T.BG2)
        # Select new
        self._selected_idx = idx
        self._cards[idx].configure(highlightbackground=T.ACCENT)

    def _confirm(self):
        if self._selected_idx is None:
            return
        hwnd, title = self._windows[self._selected_idx]
        self.destroy()
        self._on_pick(hwnd, title)

    def _refresh(self):
        """Re-scan windows and rebuild the list."""
        from engine.background_input import list_windows
        self._windows = list_windows()
        self._populate()


# ── helpers ───────────────────────────────────────────────────────────────────

def _default_macro() -> dict:
    return {
        "name":          "my_macro",
        "description":   "",
        "trigger":       {"type": "hotkey", "keys": ["ctrl", "F1"]},
        "loop":          False,
        "loop_delay_ms": 0,
        "actions":       [],
    }
