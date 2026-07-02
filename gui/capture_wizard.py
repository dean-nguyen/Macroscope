"""
Guided Capture wizard.

Walks the user through capturing every template a pack needs — one screen at a
time, saved with the exact name the macros expect. Turns "read the guide and
name 10 files by hand" into a click-through, so anyone (including non-technical
buyers) can finish a pack for their own game/resolution.

Driven by a template spec: a list of ``{"name", "description"}`` dicts
(see engine.pack_store.load_template_spec).
"""

import tkinter as tk
from typing import Callable, Dict, List, Optional

from engine.paths import TEMPLATES_DIR
from gui import theme as T
from gui.widgets import Button, Label, Frame, SectionLabel

try:
    from PIL import Image, ImageTk
except Exception:  # pragma: no cover
    Image = ImageTk = None


class CaptureWizard(tk.Toplevel):
    PREVIEW = (150, 96)

    def __init__(
        self,
        parent: tk.Misc,
        spec: List[Dict],
        capture_root: Optional[tk.Misc] = None,
        templates_dir=TEMPLATES_DIR,
        on_done: Optional[Callable] = None,
    ) -> None:
        super().__init__(parent)
        self._spec = spec
        self._root = capture_root or parent
        self._templates_dir = templates_dir
        self._on_done = on_done
        self._i = 0
        self._hidden: list = []
        self._preview_img = None

        self.title("Guided Capture")
        self.configure(bg=T.BG)
        self.geometry("460x420")
        self.resizable(False, False)
        self.transient(parent)
        T.center_on_parent(self, parent, 460, 420)
        self.grab_set()

        self._build()
        self._render()
        self.bind("<Escape>", lambda _: self._finish())

    # ── construction ────────────────────────────────────────────────────────────

    def _build(self):
        head = Frame(self)
        head.pack(fill=tk.X, padx=16, pady=(16, 4))
        SectionLabel(head, "Guided Capture", bg=T.BG).pack(side=tk.LEFT)
        self._progress = tk.Label(head, text="", bg=T.BG, fg=T.FG_DIM,
                                  font=T.FONT_SMALL)
        self._progress.pack(side=tk.RIGHT)

        self._name = tk.Label(self, text="", bg=T.BG, fg=T.FG,
                              font=T.FONT_TITLE, anchor="w")
        self._name.pack(fill=tk.X, padx=16, pady=(8, 2))
        self._status = tk.Label(self, text="", bg=T.BG, font=T.FONT_SMALL,
                                anchor="w")
        self._status.pack(fill=tk.X, padx=16)

        self._desc = tk.Label(self, text="", bg=T.BG3, fg=T.FG_DIM,
                              font=T.FONT, wraplength=420, justify="left",
                              padx=12, pady=10, anchor="w")
        self._desc.pack(fill=tk.X, padx=16, pady=12)

        self._preview = tk.Label(self, bg=T.BG2, width=self.PREVIEW[0],
                                 height=self.PREVIEW[1])
        self._preview.pack(pady=4)

        hint = tk.Label(
            self, bg=T.BG, fg=T.FG_XDIM, font=T.FONT_SMALL, wraplength=420,
            justify="left",
            text="Tip: have the game visible first. Click Capture, then drag a "
                 "tight box around the element. Esc when you're done.",
        )
        hint.pack(fill=tk.X, padx=16, pady=(2, 8))

        nav = Frame(self)
        nav.pack(fill=tk.X, padx=16, pady=(4, 14), side=tk.BOTTOM)
        self._back_btn = Button(nav, "‹ Back", command=self._back, variant="ghost")
        self._back_btn.pack(side=tk.LEFT)
        Button(nav, "Done", command=self._finish, variant="ghost").pack(side=tk.RIGHT)
        self._next_btn = Button(nav, "Skip ›", command=self._next, variant="ghost")
        self._next_btn.pack(side=tk.RIGHT, padx=6)
        self._cap_btn = Button(nav, "Capture", command=self._capture, variant="success")
        self._cap_btn.pack(side=tk.RIGHT)

    # ── rendering ───────────────────────────────────────────────────────────────

    def _current(self) -> Dict:
        return self._spec[self._i]

    def _path_for(self, name: str):
        return self._templates_dir / name

    def _render(self):
        item = self._current()
        self._progress.configure(text=f"Step {self._i + 1} of {len(self._spec)}")
        self._name.configure(text=item["name"])
        self._desc.configure(text=item.get("description", ""))

        captured = self._path_for(item["name"]).exists()
        if captured:
            self._status.configure(text="✓ captured", fg=T.SUCCESS)
            self._cap_btn.configure(text="Re-capture")
        else:
            self._status.configure(text="○ not captured yet", fg=T.WARNING)
            self._cap_btn.configure(text="Capture")

        self._back_btn.configure(state=(tk.NORMAL if self._i > 0 else tk.DISABLED))
        self._next_btn.configure(
            text="Finish" if self._i == len(self._spec) - 1 else "Skip ›")
        self._show_preview(item["name"] if captured else None)

    def _show_preview(self, name):
        self._preview_img = None
        if name and ImageTk is not None:
            try:
                with Image.open(self._path_for(name)) as img:
                    img = img.convert("RGB")
                    img.thumbnail(self.PREVIEW)
                    self._preview_img = ImageTk.PhotoImage(img)
            except Exception:
                self._preview_img = None
        self._preview.configure(image=self._preview_img,
                                text="" if self._preview_img else "no image",
                                fg=T.FG_XDIM)

    # ── actions ─────────────────────────────────────────────────────────────────

    def _capture(self):
        from gui.region_capture import RegionCapture
        name = self._current()["name"]
        self._hidden = self._toplevel_chain()
        for w in self._hidden:
            try:
                w.withdraw()
            except tk.TclError:
                pass
        RegionCapture(
            self._root,
            lambda img, x, y, w, h: self._on_captured(name, img),
        ).start()

    def _on_captured(self, name: str, img):
        for w in self._hidden:
            try:
                w.deiconify()
            except tk.TclError:
                pass
        self._hidden = []
        if img is not None:
            try:
                self._templates_dir.mkdir(parents=True, exist_ok=True)
                img.save(str(self._path_for(name)))
            except Exception:
                pass
            if self._i < len(self._spec) - 1:
                self._i += 1  # auto-advance after a successful capture
        self._render()

    def _toplevel_chain(self) -> list:
        """Every window from this wizard up to the root, so capture sees only
        the game underneath."""
        chain, w = [], self
        for _ in range(5):
            if w is None:
                break
            if w not in chain and hasattr(w, "withdraw"):
                chain.append(w)
            w = getattr(w, "master", None)
        return chain

    def _back(self):
        if self._i > 0:
            self._i -= 1
            self._render()

    def _next(self):
        if self._i < len(self._spec) - 1:
            self._i += 1
            self._render()
        else:
            self._finish()

    def _finish(self):
        if self._on_done:
            self._on_done()
        self.destroy()
