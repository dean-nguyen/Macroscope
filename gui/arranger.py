"""
Window Arranger — select windows and tile them in a grid on a chosen monitor.

Window management goes through pywin32, with one exception: detecting a *cloaked*
window needs DwmGetWindowAttribute, which pywin32 does not expose, so that one
call is made via ctypes. It earns its place — suspended UWP apps stay "visible"
with a title and would otherwise be offered for arranging, then ignore every
request (this is why Settings used to appear in the list twice).
"""

import ctypes
import ctypes.wintypes
import tkinter as tk
from tkinter import messagebox
from typing import Dict, List, Optional, Tuple

from PIL import ImageGrab, ImageTk, Image as PILImage

from gui import theme as T
from gui.widgets import Button, Scrollbar

import win32api
import win32gui
import win32con


# ── helpers ──────────────────────────────────────────────────────────────────

def _ellipsize(text: str, limit: int) -> str:
    """Shorten *text* to *limit* characters, marking that it was cut.

    A bare slice reads as a rendering bug rather than a truncation: window titles
    ended mid-word flush against the row edge, which looked exactly like text
    being clipped by a too-narrow panel.
    """
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


_DWMWA_CLOAKED = 14


def _is_cloaked(hwnd: int) -> bool:
    """True for a window Windows is hiding without marking it invisible.

    Suspended UWP apps stay 'visible' with a title, which is why Settings used to
    appear twice in the list — one entry was a ghost that ignores every request.
    """
    try:
        cloaked = ctypes.c_int(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            ctypes.wintypes.HWND(hwnd), _DWMWA_CLOAKED,
            ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        return cloaked.value != 0
    except Exception:
        return False


def _is_arrangeable(hwnd: int) -> bool:
    """Whether *hwnd* is a real top-level app window worth offering to arrange.

    IsWindowVisible plus a non-empty title is far too loose: it also matches the
    desktop shell ("Program Manager"), the IME host ("Windows Input Experience"),
    tool windows like PowerToys' overlay, and cloaked UWP ghosts. None of those
    can be tiled — measured, they lack WS_THICKFRAME entirely — so offering them
    only lets the user pick something that then silently does nothing.
    """
    if not win32gui.IsWindowVisible(hwnd):
        return False
    if not win32gui.GetWindowText(hwnd):
        return False
    # pywin32 does not wrap GetShellWindow, so this goes through ctypes too.
    if hwnd == ctypes.windll.user32.GetShellWindow():
        return False
    if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
        return False                      # a dialog owned by another window
    if _is_cloaked(hwnd):
        return False
    try:
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        if ex_style & win32con.WS_EX_TOOLWINDOW:
            return False
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        if right - left <= 0 or bottom - top <= 0:
            return False
    except Exception:
        return False
    return True


def is_resizable(hwnd: int) -> bool:
    """A window without WS_THICKFRAME will ignore the size half of a placement."""
    try:
        return bool(win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                    & win32con.WS_THICKFRAME)
    except Exception:
        return False


def _list_windows() -> List[Tuple[int, str]]:
    """Return [(hwnd, title), …] for windows that can actually be arranged."""
    windows = []

    def _cb(hwnd, _):
        if _is_arrangeable(hwnd):
            windows.append((hwnd, win32gui.GetWindowText(hwnd)))

    win32gui.EnumWindows(_cb, None)
    return sorted(windows, key=lambda x: x[1].lower())


_MONITORINFOF_PRIMARY = 1


def _get_monitors() -> List[Dict]:
    """Return list of {name, x, y, w, h, work, primary} for each monitor."""
    monitors = []
    for hmon, _, rect in win32api.EnumDisplayMonitors():
        x, y, x2, y2 = rect
        w, h = x2 - x, y2 - y
        info = win32api.GetMonitorInfo(hmon)
        # Ask Windows which monitor is primary rather than inferring it from the
        # origin. Secondary monitors can sit at a negative origin — this machine
        # has one at x=-2560 — so origin arithmetic is not a reliable signal.
        primary = bool(info.get("Flags", 0) & _MONITORINFOF_PRIMARY)
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


def tile_rects(monitor: Dict, cols: int, gap: int, count: int) -> List[Tuple[int, int, int, int]]:
    """Rects for *count* windows tiled on *monitor*, as (x, y, w, h).

    Pure arithmetic and no Tk, so it can be tested directly.

    Two things this gets right that the previous inline version did not, both of
    which sent windows off the display:

    * It divides the work area's HEIGHT among the rows. The old code advanced each
      row by the full work-area height, so row 1 started exactly at the bottom
      edge — every window past the first row landed off-monitor. The preview's
      "+N more below" was describing that as if it were a feature.
    * It never keeps a window's original height. Preserving it moves a window
      unchanged onto a monitor that may be much shorter: a 2400px-tall window put
      on a 1380px work area overflowed by 1020px. Tiling means fitting the target.

    Coordinates are virtual-desktop absolute, which is what SetWindowPos wants, so
    a monitor at a negative origin (a screen to the left of the primary) works
    without special-casing.
    """
    if count <= 0:
        return []
    wa_x, wa_y, wa_w, wa_h = monitor["work"]
    cols = max(1, min(cols, count))
    rows = -(-count // cols)                       # ceil
    gap = max(0, gap)

    # Never let the gaps consume the whole axis.
    cell_w = max(1, (wa_w - gap * (cols + 1)) // cols)
    cell_h = max(1, (wa_h - gap * (rows + 1)) // rows)

    rects = []
    for i in range(count):
        col, row = i % cols, i // cols
        x = wa_x + gap + col * (cell_w + gap)
        y = wa_y + gap + row * (cell_h + gap)
        # Clamp so rounding or an extreme gap can never push a window past the
        # monitor it was explicitly assigned to.
        w = min(cell_w, wa_x + wa_w - x)
        h = min(cell_h, wa_y + wa_h - y)
        rects.append((x, y, max(1, w), max(1, h)))
    return rects


def monitor_dpi_scale(monitor: Dict) -> float:
    """Scale factor of *monitor*, or 1.0 if it cannot be determined.

    Monitors can run at different scales — this desktop has 240 DPI (2.5x) next to
    120 DPI (1.25x) — and a window's PHYSICAL size changes when it crosses between
    them, because apps hold a logical size. That is why the same game window
    measures 1939px wide on the 1.25x screen and 3878px on the 2.5x one.
    """
    try:
        hmon = ctypes.windll.user32.MonitorFromPoint(
            ctypes.wintypes.POINT(monitor["x"] + monitor["w"] // 2,
                                  monitor["y"] + monitor["h"] // 2), 2)
        dpi_x, dpi_y = ctypes.c_uint(), ctypes.c_uint()
        ctypes.windll.shcore.GetDpiForMonitor(
            hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        return dpi_x.value / 96.0 if dpi_x.value else 1.0
    except Exception:
        return 1.0


def grid_capacity(monitor: Dict, window_size: Tuple[int, int],
                  gap: int = 0) -> Tuple[int, int]:
    """How many columns x rows of *window_size* fit in *monitor*'s work area.

    Used to warn before arranging. A window that enforces its own size cannot be
    tiled into a smaller cell, so asking for a 2x2 grid of windows that only fit
    1x1 produces a heap of overlapping windows and looks like a failure.
    """
    _, _, wa_w, wa_h = monitor["work"]
    win_w, win_h = max(1, window_size[0]), max(1, window_size[1])
    cols = max(0, (wa_w - gap) // (win_w + gap))
    rows = max(0, (wa_h - gap) // (win_h + gap))
    return cols, rows


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


def _place_window(hwnd: int, x: int, y: int, w: int, h: int,
                  tolerance: int = 8,
                  bounds: Optional[Tuple[int, int, int, int]] = None) -> Optional[str]:
    """Move and resize a window to the target rect.

    Steps: restore → remove maximize style → move → verify.

    Returns None on success, or a short reason why it did not take. This used to
    swallow every failure and return nothing, while _apply closed the dialog
    regardless — so a window that ignored the request looked identical to one that
    moved, and "Arrange did nothing" had no diagnosis available.
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
    except Exception as exc:
        return f"the move was rejected ({exc})"

    # 4. Verify. A window can accept the call and still not comply — a minimum
    # size it enforces, a locked aspect ratio, or no WS_THICKFRAME at all.
    try:
        time.sleep(0.05)
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        got_w, got_h = right - left, bottom - top
        if max(abs(left - x), abs(top - y),
               abs(got_w - w), abs(got_h - h)) <= tolerance:
            return None

        # It kept its own size. Position is still ours to control, so at least
        # keep the window on the monitor the user chose instead of letting it
        # spill onto the next screen — which is what a game that enforces a 16:9
        # size does when handed a narrower cell.
        nudged = ""
        if bounds and (abs(got_w - w) > tolerance or abs(got_h - h) > tolerance):
            b_left, b_top, b_w, b_h = bounds
            fit_x = max(b_left, min(x, b_left + b_w - got_w))
            fit_y = max(b_top, min(y, b_top + b_h - got_h))
            if (fit_x, fit_y) != (left, top):
                win32gui.SetWindowPos(
                    hwnd, None, fit_x, fit_y, got_w, got_h,
                    win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
                nudged = ", moved back onto the monitor"

        if not is_resizable(hwnd):
            return f"it cannot be resized, so it stayed {got_w}x{got_h}{nudged}"
        return (f"it enforces its own size — wanted {w}x{h}, "
                f"got {got_w}x{got_h}{nudged}")
    except Exception:
        return None          # cannot verify; assume it worked rather than nag


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
        self.minsize(T.px(580), T.px(420))
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
        # OptionMenu displays its variable, and _monitor_var holds an index — so
        # the control read "0" / "1" and gave no way to tell which screen was
        # selected. Display a name, keep the index for the logic.
        self._monitor_label = tk.StringVar(
            value=self._monitors[self._monitor_var.get()]["name"])
        mon_menu = tk.OptionMenu(inner, self._monitor_label,
                                 self._monitor_label.get())
        mon_menu.configure(bg=T.BG3, fg=T.FG, font=T.FONT,
                           activebackground=T.BG4, highlightthickness=0,
                           relief=tk.FLAT, anchor="w")
        mon_menu["menu"].configure(bg=T.BG3, fg=T.FG, font=T.FONT,
                                   activebackground=T.ACCENT)
        mon_menu["menu"].delete(0, tk.END)
        for i, m in enumerate(self._monitors):
            mon_menu["menu"].add_command(
                label=m["name"], command=lambda v=i: self._select_monitor(v))
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
        body.grid_columnconfigure(1, weight=0, minsize=T.px(200))
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
        sb = Scrollbar(lc, orient=tk.VERTICAL, command=canvas.yview)
        self._list_inner = tk.Frame(canvas, bg=T.BG2)
        self._list_inner.bind("<Configure>",
            lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        list_item = canvas.create_window((0, 0), window=self._list_inner, anchor="nw")
        # Without this the inner frame keeps its own requested width and the rows
        # stop short of the panel edge — measured 763px of rows in a 911px canvas,
        # throwing away 148px that the window titles could have used.
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(list_item, width=e.width))
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
        sb2 = Scrollbar(rc, orient=tk.VERTICAL, command=canvas2.yview)
        self._order_inner = tk.Frame(canvas2, bg=T.BG2)
        self._order_inner.bind("<Configure>",
            lambda _: canvas2.configure(scrollregion=canvas2.bbox("all")))
        order_item = canvas2.create_window((0, 0), window=self._order_inner, anchor="nw")
        canvas2.bind("<Configure>",
                     lambda e: canvas2.itemconfig(order_item, width=e.width))
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
        self._preview = tk.Canvas(inner, bg="#111", width=T.px(280), height=T.px(100),
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

            # Thumbnail. The size lives on a Frame because width/height there are
            # pixels; on the Label they meant 6 characters by 2 lines until an
            # image was attached, at which point they became 6x2 PIXELS and the
            # thumbnail collapsed to 10x6 — effectively invisible.
            tw, th = T.px(64), T.px(38)
            cell = tk.Frame(row, bg="#000", width=tw, height=th)
            cell.pack_propagate(False)
            cell.pack(side=tk.LEFT, padx=(0, T.px(6)), pady=T.px(3))
            thumb = tk.Label(cell, bg="#000")
            thumb.pack(fill=tk.BOTH, expand=True)
            self._set_thumb(thumb, hwnd, tw, th)

            # Title
            lbl_fg = T.FG if not checked else T.ACCENT
            tk.Label(row, text=_ellipsize(title, 42), font=T.FONT, bg=T.BG3,
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
            tk.Label(row, text=_ellipsize(title, 20), font=T.FONT_SMALL, bg=T.BG3,
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
        # Read the canvas's real size rather than assuming the logical one. The
        # canvas is created at T.px(280) x T.px(100), so hardcoding 280x100 drew
        # the whole preview into the top-left corner of a 2.5x larger widget.
        cw, ch = c.winfo_width(), c.winfo_height()
        if cw <= 1 or ch <= 1:                 # not mapped yet
            cw, ch = T.px(280), T.px(100)

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
        margin = T.px(6)
        scale = min((cw - margin * 2) / wa_w, (ch - margin * 2) / wa_h)
        ox = (cw - wa_w * scale) / 2
        oy = (ch - wa_h * scale) / 2

        # Monitor outline
        c.create_rectangle(ox, oy, ox + wa_w * scale, oy + wa_h * scale,
                           outline=T.BORDER, width=T.px(1))

        # Draw the same grid _apply will use, so the preview cannot promise a
        # layout the apply step does not produce.
        for i, (rx, ry, rw, rh) in enumerate(tile_rects(mon, cols, gap, n)):
            sx = ox + (rx - wa_x) * scale
            sy = oy + (ry - wa_y) * scale
            sw, sh = rw * scale, rh * scale

            fill = T.ACCENT if i % 2 == 0 else T.SUCCESS
            c.create_rectangle(sx, sy, sx + sw, sy + sh,
                               fill=fill, outline="", stipple="gray50")
            _, title = self._selected[i]
            c.create_text(sx + sw / 2, sy + sh / 2,
                          text=_ellipsize(title, 10), fill=T.FG,
                          font=("Segoe UI", 7),
                          width=max(sw - T.px(4), T.px(10)))

    # ── Actions ──────────────────────────────────────────────────────────────

    def _capacity_advice(self, mon: Dict, gap: int) -> str:
        """What the user can actually do about windows that kept their own size.

        Deliberately measured AFTER trying, not before: WS_THICKFRAME is not a
        reliable predictor. Onmyoji carries that style — is_resizable() reports
        True — and still snaps straight back to its own size, so a pre-flight check
        based on the style flag would have skipped the very case this is for.
        """
        biggest = (0, 0)
        for hwnd, _ in self._selected:
            try:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            except Exception:
                continue
            if (right - left) * (bottom - top) > biggest[0] * biggest[1]:
                biggest = (right - left, bottom - top)
        if biggest == (0, 0):
            return ""

        fit_cols, fit_rows = grid_capacity(mon, biggest, gap)
        _, _, wa_w, wa_h = mon["work"]
        scale = monitor_dpi_scale(mon)
        return (
            f"\n\nThe largest of them is {biggest[0]}x{biggest[1]} px. "
            f"{mon['name']} has {wa_w}x{wa_h} usable at {scale:.2f}x scaling, "
            f"which fits {fit_cols} column(s) x {fit_rows} row(s) at that size.\n\n"
            f"To tile them properly, lower the app's own resolution — for a game, "
            f"in its video settings — so one window fits one cell. Note that a "
            f"window's pixel size also changes with the monitor's scaling, so the "
            f"same window needs more room on a higher-DPI screen."
        )

    def _select_monitor(self, index: int):
        self._monitor_var.set(index)
        self._monitor_label.set(self._monitors[index]["name"])
        self._draw_preview()

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
        cols = max(1, self._cols_var.get())
        gap = self._gap_var.get()

        failures = []
        size_refused = False
        for (hwnd, title), rect in zip(self._selected,
                                       tile_rects(mon, cols, gap, n)):
            reason = _place_window(hwnd, *rect, bounds=mon["work"])
            if reason:
                failures.append(f"• {_ellipsize(title, 40)} — {reason}")
                size_refused = size_refused or "own size" in reason

        if failures:
            # Closing on a silent failure is what made this feel broken: the
            # dialog vanished and nothing had moved, with nothing to go on.
            advice = self._capacity_advice(mon, gap) if size_refused else ""
            messagebox.showwarning(
                "Some windows kept their own size",
                f"{len(failures)} of {n} did not fit the layout:\n\n"
                + "\n".join(failures[:8])
                + ("\n…" if len(failures) > 8 else "")
                + advice,
                parent=self)

        self.destroy()
