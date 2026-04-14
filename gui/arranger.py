"""
Window Arranger — select windows and tile them in a grid on a chosen monitor.

Uses pywin32 exclusively for window management (no ctypes DWM hacks).
"""

import tkinter as tk
from tkinter import messagebox
from typing import Dict, List, Optional, Tuple

from PIL import ImageGrab, ImageTk, Image as PILImage

from gui import theme as T
from gui.widgets import Button

import win32api
import win32gui
import win32con


# ── helpers ──────────────────────────────────────────────────────────────────

def _list_windows() -> List[Tuple[int, str]]:
    """Return [(hwnd, title), …] for visible top-level windows."""
    windows = []

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                windows.append((hwnd, title))

    win32gui.EnumWindows(_cb, None)
    return sorted(windows, key=lambda x: x[1].lower())


def _get_monitors() -> List[Dict]:
    """Return list of {name, x, y, w, h, work, primary} for each monitor."""
    monitors = []
    for hmon, _, rect in win32api.EnumDisplayMonitors():
        x, y, x2, y2 = rect
        w, h = x2 - x, y2 - y
        primary = (x == 0 and y == 0)
        info = win32api.GetMonitorInfo(hmon)
        work = info["Work"]  # (left, top, right, bottom) excluding taskbar
        idx = len(monitors) + 1
        name = f"Monitor {idx} ({w}x{h})"
        if primary:
            name += " [Primary]"
        monitors.append({
            "name": name, "x": x, "y": y, "w": w, "h": h,
            "work": (work[0], work[1], work[2] - work[0], work[3] - work[1]),
            "primary": primary,
        })
    if not monitors:
        monitors.append({
            "name": "Monitor 1 [Primary]",
            "x": 0, "y": 0, "w": 1920, "h": 1080,
            "work": (0, 0, 1920, 1040),
            "primary": True,
        })
    return monitors


def _monitor_index_at(x: int, y: int, monitors: List[Dict]) -> int:
    """Return the index of the monitor containing (x, y), or 0."""
    for i, m in enumerate(monitors):
        if m["x"] <= x < m["x"] + m["w"] and m["y"] <= y < m["y"] + m["h"]:
            return i
    return 0


def get_monitor_at(x: int, y: int) -> Dict:
    """Return the monitor dict containing point (x, y)."""
    mons = _get_monitors()
    return mons[_monitor_index_at(x, y, mons)]


def _place_window(hwnd: int, x: int, y: int, w: int, h: int):
    """
    Move and resize a window to the target rect.

    Steps: restore → remove maximize style → move → repaint.
    """
    try:
        import time

        # 1. Restore from minimized / maximized
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.05)

        # 2. Strip WS_MAXIMIZE flag so MoveWindow actually resizes
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        if style & win32con.WS_MAXIMIZE:
            win32gui.SetWindowLong(
                hwnd, win32con.GWL_STYLE, style & ~win32con.WS_MAXIMIZE)

        # 3. Move and resize
        win32gui.SetWindowPos(
            hwnd, None, x, y, w, h,
            win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
            | win32con.SWP_FRAMECHANGED,
        )
    except Exception:
        pass


def _bind_wheel(widget, canvas):
    """Bind mousewheel scrolling recursively to a canvas."""
    def _scroll(e):
        canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
    widget.bind("<MouseWheel>", _scroll)
    for child in widget.winfo_children():
        _bind_wheel(child, canvas)


# ── Window Arranger dialog ───────────────────────────────────────────────────

class WindowArranger(tk.Toplevel):

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Arrange Windows")
        self.configure(bg=T.BG)
        T.center_on_parent(self, parent, 780, 580)
        self.minsize(580, 420)
        self.transient(parent)

        self._monitors = _get_monitors()
        self._all_windows = _list_windows()
        self._selected: List[Tuple[int, str]] = []
        self._images = []  # keep refs to prevent GC

        # Detect which monitor parent is on
        cx = parent.winfo_x() + parent.winfo_width() // 2
        cy = parent.winfo_y() + parent.winfo_height() // 2
        default_mon = _monitor_index_at(cx, cy, self._monitors)

        self._monitor_var = tk.IntVar(value=default_mon)
        self._cols_var = tk.IntVar(value=2)
        self._gap_var = tk.IntVar(value=0)

        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._preview = None  # created in _build_footer, referenced by _draw_preview
        self._build_toolbar(self)
        self._build_body(self)
        self._build_footer(self)

    def _build_toolbar(self, parent):
        bar = tk.Frame(parent, bg=T.BG2)
        bar.grid(row=0, column=0, sticky="ew")
        inner = tk.Frame(bar, bg=T.BG2)
        inner.pack(fill=tk.X, padx=T.PAD, pady=10)

        # Monitor
        tk.Label(inner, text="Monitor", font=T.FONT, bg=T.BG2,
                 fg=T.FG).pack(side=tk.LEFT, padx=(0, 4))
        mon_menu = tk.OptionMenu(inner, self._monitor_var, 0)
        mon_menu.configure(bg=T.BG3, fg=T.FG, font=T.FONT,
                           activebackground=T.BG4, highlightthickness=0,
                           relief=tk.FLAT)
        mon_menu["menu"].configure(bg=T.BG3, fg=T.FG, font=T.FONT,
                                   activebackground=T.ACCENT)
        mon_menu["menu"].delete(0, tk.END)
        for i, m in enumerate(self._monitors):
            mon_menu["menu"].add_command(
                label=m["name"], command=lambda v=i: self._monitor_var.set(v))
        mon_menu.pack(side=tk.LEFT, padx=(0, 16))

        # Columns
        tk.Label(inner, text="Columns", font=T.FONT, bg=T.BG2,
                 fg=T.FG).pack(side=tk.LEFT, padx=(0, 4))
        tk.Spinbox(inner, from_=1, to=10, textvariable=self._cols_var,
                   width=3, bg=T.BG3, fg=T.FG, font=T.FONT,
                   buttonbackground=T.BG3, relief=tk.FLAT,
                   insertbackground=T.FG).pack(side=tk.LEFT, padx=(0, 16))

        # Gap
        tk.Label(inner, text="Gap", font=T.FONT, bg=T.BG2,
                 fg=T.FG).pack(side=tk.LEFT, padx=(0, 4))
        tk.Spinbox(inner, from_=0, to=50, textvariable=self._gap_var,
                   width=3, bg=T.BG3, fg=T.FG, font=T.FONT,
                   buttonbackground=T.BG3, relief=tk.FLAT,
                   insertbackground=T.FG).pack(side=tk.LEFT)

        # Refresh
        Button(inner, "Refresh", command=self._refresh,
               variant="ghost").pack(side=tk.RIGHT)

    def _build_body(self, parent):
        body = tk.Frame(parent, bg=T.BG)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0, minsize=200)
        body.grid_rowconfigure(0, weight=1)

        # ── Left: window list ─────────────────────────────────────────────────
        left = tk.Frame(body, bg=T.BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(10, 4), pady=6)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        lh = tk.Frame(left, bg=T.BG)
        lh.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        tk.Label(lh, text="WINDOWS", font=T.FONT_LABEL, bg=T.BG,
                 fg=T.FG_DIM).pack(side=tk.LEFT)
        self._sel_lbl = tk.Label(lh, text="0 selected", font=T.FONT_SMALL,
                                  bg=T.BG, fg=T.ACCENT)
        self._sel_lbl.pack(side=tk.RIGHT)

        lc = tk.Frame(left, bg=T.BG2)
        lc.grid(row=1, column=0, sticky="nsew")
        canvas = tk.Canvas(lc, bg=T.BG2, highlightthickness=0, bd=0)
        sb = tk.Scrollbar(lc, orient=tk.VERTICAL, command=canvas.yview)
        self._list_inner = tk.Frame(canvas, bg=T.BG2)
        self._list_inner.bind("<Configure>",
            lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._list_inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._list_canvas = canvas

        # ── Right: selected order ─────────────────────────────────────────────
        right = tk.Frame(body, bg=T.BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 10), pady=6)
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        rh = tk.Frame(right, bg=T.BG)
        rh.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        tk.Label(rh, text="ORDER", font=T.FONT_LABEL, bg=T.BG,
                 fg=T.FG_DIM).pack(side=tk.LEFT)
        tk.Label(rh, text="Clear", font=T.FONT_SMALL, bg=T.BG,
                 fg=T.DANGER, cursor="hand2").pack(side=tk.RIGHT)
        rh.winfo_children()[-1].bind("<Button-1>", lambda _: self._clear())

        rc = tk.Frame(right, bg=T.BG2)
        rc.grid(row=1, column=0, sticky="nsew")
        canvas2 = tk.Canvas(rc, bg=T.BG2, highlightthickness=0, bd=0)
        sb2 = tk.Scrollbar(rc, orient=tk.VERTICAL, command=canvas2.yview)
        self._order_inner = tk.Frame(canvas2, bg=T.BG2)
        self._order_inner.bind("<Configure>",
            lambda _: canvas2.configure(scrollregion=canvas2.bbox("all")))
        canvas2.create_window((0, 0), window=self._order_inner, anchor="nw")
        canvas2.configure(yscrollcommand=sb2.set)
        canvas2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self._order_canvas = canvas2

        self._populate()

    def _build_footer(self, parent):
        foot = tk.Frame(parent, bg=T.BG2)
        foot.grid(row=2, column=0, sticky="ew")
        inner = tk.Frame(foot, bg=T.BG2)
        inner.pack(fill=tk.X, padx=12, pady=8)

        # Preview
        self._preview = tk.Canvas(inner, bg="#111", width=280, height=100,
                                   highlightthickness=1,
                                   highlightbackground=T.BORDER)
        self._preview.pack(side=tk.LEFT, padx=(0, 12))

        # Buttons
        bf = tk.Frame(inner, bg=T.BG2)
        bf.pack(side=tk.RIGHT)
        Button(bf, "Arrange", command=self._apply,
               variant="success").pack(side=tk.RIGHT, padx=4)
        Button(bf, "Cancel", command=self.destroy,
               variant="ghost").pack(side=tk.RIGHT, padx=4)

        self._draw_preview()

    # ── Populate lists ────────────────────────────────────────────────────────

    def _populate(self):
        self._images.clear()
        self._populate_window_list()
        self._populate_order_list()
        self._draw_preview()

    def _populate_window_list(self):
        for w in self._list_inner.winfo_children():
            w.destroy()

        selected_hwnds = {h for h, _ in self._selected}

        for hwnd, title in self._all_windows:
            checked = hwnd in selected_hwnds
            row = tk.Frame(self._list_inner, bg=T.BG3)
            row.pack(fill=tk.X, padx=3, pady=1)

            # Checkbox
            var = tk.BooleanVar(value=checked)
            cb = tk.Checkbutton(
                row, variable=var, bg=T.BG3, fg=T.FG,
                selectcolor=T.BG2, activebackground=T.BG3,
                activeforeground=T.FG, highlightthickness=0,
                command=lambda h=hwnd, t=title, v=var: self._toggle(h, t, v),
            )
            cb.pack(side=tk.LEFT, padx=(6, 4), pady=4)

            # Thumbnail
            thumb = tk.Label(row, bg="#000", width=6, height=2)
            thumb.pack(side=tk.LEFT, padx=(0, 6), pady=3)
            self._set_thumb(thumb, hwnd, 64, 38)

            # Title
            lbl_fg = T.FG if not checked else T.ACCENT
            tk.Label(row, text=title[:42], font=T.FONT, bg=T.BG3,
                     fg=lbl_fg, anchor="w").pack(side=tk.LEFT, fill=tk.X,
                     expand=True, pady=4)

        _bind_wheel(self._list_inner, self._list_canvas)

    def _populate_order_list(self):
        for w in self._order_inner.winfo_children():
            w.destroy()

        self._sel_lbl.configure(text=f"{len(self._selected)} selected")

        if not self._selected:
            tk.Label(self._order_inner, text="Check windows\nto add",
                     font=T.FONT_SMALL, bg=T.BG2, fg=T.FG_DIM,
                     justify=tk.CENTER).pack(pady=20)
            return

        for idx, (hwnd, title) in enumerate(self._selected):
            row = tk.Frame(self._order_inner, bg=T.BG3)
            row.pack(fill=tk.X, padx=3, pady=1)

            # Number badge
            tk.Label(row, text=str(idx + 1), font=T.FONT_BOLD,
                     bg=T.ACCENT, fg=T.FG, width=2).pack(
                side=tk.LEFT, padx=(4, 6), pady=3)

            # Title
            tk.Label(row, text=title[:20], font=T.FONT_SMALL, bg=T.BG3,
                     fg=T.FG, anchor="w").pack(side=tk.LEFT, fill=tk.X,
                     expand=True)

            # Up / Down / Remove
            btns = tk.Frame(row, bg=T.BG3)
            btns.pack(side=tk.RIGHT, padx=4, pady=2)

            if idx > 0:
                b = tk.Label(btns, text="^", font=T.FONT_BOLD, bg=T.BG2,
                             fg=T.FG, padx=3, cursor="hand2")
                b.pack(side=tk.LEFT, padx=1)
                b.bind("<Button-1>", lambda _, i=idx: self._swap(i, i - 1))

            if idx < len(self._selected) - 1:
                b = tk.Label(btns, text="v", font=T.FONT_BOLD, bg=T.BG2,
                             fg=T.FG, padx=3, cursor="hand2")
                b.pack(side=tk.LEFT, padx=1)
                b.bind("<Button-1>", lambda _, i=idx: self._swap(i, i + 1))

            x = tk.Label(btns, text="x", font=T.FONT_BOLD, bg=T.DANGER,
                         fg=T.FG, padx=3, cursor="hand2")
            x.pack(side=tk.LEFT, padx=(2, 0))
            x.bind("<Button-1>", lambda _, i=idx: self._remove(i))

        _bind_wheel(self._order_inner, self._order_canvas)

    # ── Preview ──────────────────────────────────────────────────────────────

    def _draw_preview(self):
        if self._preview is None:
            return
        c = self._preview
        c.delete("all")
        cw, ch = 280, 100

        n = len(self._selected)
        if n == 0:
            c.create_text(cw // 2, ch // 2, text="No windows selected",
                          fill=T.FG_DIM, font=T.FONT_SMALL)
            return

        mon = self._monitors[self._monitor_var.get()]
        wa_x, wa_y, wa_w, wa_h = mon["work"]
        cols = max(1, self._cols_var.get())
        gap = self._gap_var.get()

        # Scale to fit preview
        margin = 6
        scale = min((cw - margin * 2) / wa_w, (ch - margin * 2) / wa_h)
        ox = (cw - wa_w * scale) / 2
        oy = (ch - wa_h * scale) / 2

        # Monitor outline
        c.create_rectangle(ox, oy, ox + wa_w * scale, oy + wa_h * scale,
                           outline=T.BORDER, width=1)

        # Draw columns — width split evenly, height = work area
        cell_w = (wa_w - gap * (cols + 1)) / cols

        for i in range(min(n, cols)):
            x = gap + i * (cell_w + gap)
            sx = ox + x * scale
            sy = oy + gap * scale
            sw = cell_w * scale
            sh = wa_h * scale - gap * scale * 2

            fill = T.ACCENT if i % 2 == 0 else T.SUCCESS
            c.create_rectangle(sx, sy, sx + sw, sy + sh,
                               fill=fill, outline="", stipple="gray50")
            if i < n:
                _, title = self._selected[i]
                c.create_text(sx + sw / 2, sy + sh / 2,
                              text=title[:10], fill=T.FG,
                              font=("Segoe UI", 7), width=max(sw - 4, 10))

        # Show overflow count if more windows than columns
        if n > cols:
            c.create_text(cw // 2, ch - 8,
                          text=f"+{n - cols} more below",
                          fill=T.FG_DIM, font=("Segoe UI", 7))

    # ── Actions ──────────────────────────────────────────────────────────────

    def _toggle(self, hwnd, title, var):
        if var.get():
            if not any(h == hwnd for h, _ in self._selected):
                self._selected.append((hwnd, title))
        else:
            self._selected = [(h, t) for h, t in self._selected if h != hwnd]
        self._populate_order_list()
        self._draw_preview()

    def _swap(self, i, j):
        self._selected[i], self._selected[j] = \
            self._selected[j], self._selected[i]
        self._populate_order_list()
        self._draw_preview()

    def _remove(self, idx):
        self._selected.pop(idx)
        self._populate()

    def _clear(self):
        self._selected.clear()
        self._populate()

    def _refresh(self):
        self._all_windows = _list_windows()
        self._populate()

    def _set_thumb(self, label, hwnd, tw, th):
        try:
            cx0, cy0 = win32gui.ClientToScreen(hwnd, (0, 0))
            r = win32gui.GetClientRect(hwnd)
            w, h = r[2] - r[0], r[3] - r[1]
            if w > 0 and h > 0:
                img = ImageGrab.grab(
                    bbox=(cx0, cy0, cx0 + w, cy0 + h), all_screens=True)
                img.thumbnail((tw, th), PILImage.LANCZOS)
                tk_img = ImageTk.PhotoImage(img)
                label.configure(image=tk_img)
                self._images.append(tk_img)
        except Exception:
            pass

    # ── Apply ────────────────────────────────────────────────────────────────

    def _apply(self):
        n = len(self._selected)
        if n == 0:
            messagebox.showinfo("Nothing selected",
                                "Check some windows first.", parent=self)
            return

        mon = self._monitors[self._monitor_var.get()]
        wa_x, wa_y, wa_w, wa_h = mon["work"]
        cols = max(1, self._cols_var.get())
        gap = self._gap_var.get()

        # Only split width by columns — keep each window's original height
        cell_w = int((wa_w - gap * (cols + 1)) / cols)

        for i, (hwnd, _) in enumerate(self._selected):
            col = i % cols
            row = i // cols
            x = wa_x + gap + col * (cell_w + gap)
            y = wa_y + gap + row * (wa_h + gap)

            # Keep original window height
            try:
                rect = win32gui.GetWindowRect(hwnd)
                orig_h = rect[3] - rect[1]
            except Exception:
                orig_h = wa_h

            _place_window(hwnd, x, y, cell_w, orig_h)

        self.destroy()
