"""
Region capture overlay.

Shows a full-screen dark translucent window.  The user clicks and drags to
draw a selection rectangle; on release the selected area is grabbed as a
PIL Image and passed to the callback.

Usage
-----
    def on_captured(img, x, y, w, h):
        # img is a PIL Image, or None if cancelled
        ...

    RegionCapture(root, on_captured).start()
"""

import tkinter as tk
from typing import Callable, Optional

from PIL import ImageGrab

from gui import theme as T


class RegionCapture:
    def __init__(self, root: tk.Tk, callback: Callable):
        """
        callback(img, x, y, w, h)
          img  – PIL.Image of the captured region, or None on cancel.
          x, y – top-left corner in screen coordinates.
          w, h – size of the region in pixels.
        """
        self._root     = root
        self._callback = callback
        self._overlay: Optional[tk.Toplevel] = None
        self._canvas:  Optional[tk.Canvas]   = None
        self._rect_id: Optional[int] = None
        self._sx = self._sy = 0   # start position (screen coords)

    # ── public ────────────────────────────────────────────────────────────────

    def start(self):
        ov = tk.Toplevel(self._root)
        ov.attributes("-alpha", 0.25)
        ov.attributes("-topmost", True)
        ov.configure(bg="black", cursor="crosshair")
        ov.overrideredirect(True)
        self._overlay = ov

        # Cover entire virtual desktop (all monitors)
        try:
            import win32api
            vx = win32api.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
            vy = win32api.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
            vw = win32api.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
            vh = win32api.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
        except Exception:
            vx, vy = 0, 0
            vw = ov.winfo_screenwidth()
            vh = ov.winfo_screenheight()
        ov.geometry(f"{vw}x{vh}+{vx}+{vy}")

        cv = tk.Canvas(ov, bg="black", highlightthickness=0, cursor="crosshair")
        cv.pack(fill=tk.BOTH, expand=True)
        self._canvas = cv

        cv.create_text(
            vw // 2, 38,
            text="Drag to select a region   |   Esc to cancel",
            fill="white", font=("Segoe UI", 13),
        )

        cv.bind("<ButtonPress-1>",   self._on_press)
        cv.bind("<B1-Motion>",       self._on_drag)
        cv.bind("<ButtonRelease-1>", self._on_release)
        ov.bind("<Escape>",          self._on_cancel)
        ov.focus_force()

    # ── event handlers ────────────────────────────────────────────────────────

    def _on_press(self, event):
        self._sx = event.x_root
        self._sy = event.y_root
        if self._rect_id is not None:
            self._canvas.delete(self._rect_id)
        # Canvas coords == screen coords because canvas fills the fullscreen overlay
        self._rect_id = self._canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline=T.ACCENT, width=2, fill="",
        )

    def _on_drag(self, event):
        if self._rect_id is not None:
            # Translate screen-start to canvas-local coords
            ox = self._overlay.winfo_rootx()
            oy = self._overlay.winfo_rooty()
            self._canvas.coords(
                self._rect_id,
                self._sx - ox, self._sy - oy,
                event.x, event.y,
            )

    def _on_release(self, event):
        x1 = min(self._sx, event.x_root)
        y1 = min(self._sy, event.y_root)
        x2 = max(self._sx, event.x_root)
        y2 = max(self._sy, event.y_root)
        w, h = x2 - x1, y2 - y1

        self._close()

        if w < 4 or h < 4:
            self._callback(None, 0, 0, 0, 0)
            return

        # Delay so the overlay fully disappears before grabbing the screen
        self._root.after(150, lambda: self._grab(x1, y1, x2, y2, w, h))

    def _grab(self, x1, y1, x2, y2, w, h):
        try:
            img = ImageGrab.grab(bbox=(x1, y1, x2, y2), all_screens=True)
            self._callback(img, x1, y1, w, h)
        except Exception as exc:
            self._callback(None, 0, 0, 0, 0)

    def _on_cancel(self, event=None):
        self._close()
        self._callback(None, 0, 0, 0, 0)

    def _close(self):
        if self._overlay:
            self._overlay.destroy()
            self._overlay = None
