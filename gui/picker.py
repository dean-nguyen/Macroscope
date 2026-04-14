"""
Pixel color picker overlay.

Shows a full-screen transparent overlay with a live info bar:
  • Window-relative (client) coords  ← when a target window hwnd is given
  • Screen (absolute) coords         ← when no hwnd is given
  • Pixel colour preview

Click anywhere to capture.  Press Escape to cancel.
"""

import tkinter as tk
from typing import Callable, Optional, Tuple

from PIL import ImageGrab

from gui import theme as T


class PixelPicker:
    """
    Full-screen overlay pixel picker.

    callback(x, y, color)  is called on success.
      - If `hwnd` is passed to start(), x/y are CLIENT-space (window-relative).
      - If no hwnd, x/y are screen-absolute.

    callback(None, None, None) is called on cancel.
    """

    def __init__(self, root: tk.Tk, callback: Callable):
        self._root     = root
        self._callback = callback
        self._overlay: Optional[tk.Toplevel] = None
        self._hwnd: Optional[int] = None
        self._coord_lbl: Optional[tk.Label] = None
        self._swatch:    Optional[tk.Label] = None

    # ── public ────────────────────────────────────────────────────────────────

    def start(self, hwnd: Optional[int] = None):
        """
        Open the picker overlay.

        hwnd : win32 window handle, optional
            When provided, coordinates are reported and returned in the
            window's client space (relative to the inner top-left corner).
            The info bar shows both window-relative AND screen coords live.
        """
        self._hwnd = hwnd

        ov = tk.Toplevel(self._root)
        ov.attributes("-alpha", 0.01)   # nearly invisible but intercepts clicks
        ov.attributes("-topmost", True)
        ov.configure(cursor="crosshair", bg="black")
        ov.title("Pick Pixel")
        ov.overrideredirect(True)

        # Cover the entire virtual desktop (all monitors)
        try:
            import win32api
            vx = win32api.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
            vy = win32api.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
            vw = win32api.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
            vh = win32api.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
        except Exception:
            vx, vy = 0, 0
            vw = self._root.winfo_screenwidth()
            vh = self._root.winfo_screenheight()
        ov.geometry(f"{vw}x{vh}+{vx}+{vy}")

        self._overlay = ov

        # ── info bar at the top ───────────────────────────────────────────────
        bar = tk.Frame(ov, bg="#111111", height=46)
        bar.place(relx=0, rely=0, relwidth=1)
        bar.pack_propagate(False)

        mode_txt = "window-relative coords" if hwnd else "screen coords"
        tk.Label(
            bar,
            text=f"Click to pick pixel ({mode_txt})   |   Esc to cancel",
            bg="#111111", fg="#dddddd",
            font=("Segoe UI", 11),
        ).pack(side=tk.LEFT, padx=16, pady=12)

        # live colour swatch
        self._swatch = tk.Label(bar, text="  ", bg="#000000", width=3,
                                relief=tk.FLAT)
        self._swatch.pack(side=tk.RIGHT, padx=(4, 12), pady=10)

        # live coordinate readout
        self._coord_lbl = tk.Label(
            bar, text="",
            bg="#111111", fg="#aaaaaa",
            font=("Consolas", 10),
        )
        self._coord_lbl.pack(side=tk.RIGHT, padx=4, pady=12)

        ov.bind("<Motion>",   self._on_motion)
        ov.bind("<Button-1>", self._on_click)
        ov.bind("<Escape>",   self._on_cancel)
        ov.focus_force()

    # ── event handlers ────────────────────────────────────────────────────────

    def _on_motion(self, event):
        sx, sy = event.x_root, event.y_root

        # Grab pixel colour
        try:
            r, g, b = _grab_pixel(sx, sy)
        except Exception:
            r, g, b = 0, 0, 0

        # Update colour swatch
        try:
            self._swatch.config(bg=f"#{r:02x}{g:02x}{b:02x}")
        except Exception:
            pass

        # Build coordinate text
        rgb_txt = f"RGB ({r}, {g}, {b})"
        if self._hwnd:
            wx, wy = _screen_to_client(self._hwnd, sx, sy)
            if wx is not None:
                coord_txt = f"Window ({wx}, {wy})   Screen ({sx}, {sy})   {rgb_txt}"
            else:
                coord_txt = f"Screen ({sx}, {sy})   {rgb_txt}   [window lost]"
        else:
            coord_txt = f"Screen ({sx}, {sy})   {rgb_txt}"

        try:
            self._coord_lbl.config(text=coord_txt)
        except Exception:
            pass

    def _on_click(self, event):
        sx, sy = event.x_root, event.y_root
        self._close()
        color = _grab_pixel(sx, sy)

        if self._hwnd:
            wx, wy = _screen_to_client(self._hwnd, sx, sy)
            if wx is not None:
                self._callback(wx, wy, color)
                return
            # window lost → fall back to screen coords

        self._callback(sx, sy, color)

    def _on_cancel(self, event=None):
        self._close()
        self._callback(None, None, None)

    def _close(self):
        if self._overlay:
            self._overlay.destroy()
            self._overlay = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _grab_pixel(x: int, y: int) -> Tuple[int, int, int]:
    img = ImageGrab.grab(bbox=(x, y, x + 1, y + 1), all_screens=True)
    return img.getpixel((0, 0))[:3]


def _screen_to_client(hwnd: int, sx: int, sy: int):
    """
    Convert screen (sx, sy) → window client (cx, cy).
    Returns (None, None) if the conversion fails (window closed, etc.).
    """
    try:
        import win32gui
        cx, cy = win32gui.ScreenToClient(hwnd, (sx, sy))
        return cx, cy
    except Exception:
        return None, None
