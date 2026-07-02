"""
Template Library manager.

A window for managing the screenshot images used by image-matching actions:
preview them, see which macros use each one, rename (references in macros are
rewritten automatically), delete, and clean out unused files.

No database — everything is read live from the templates folder and the loaded
macros, so the view always reflects what's actually on disk.
"""

import os
import subprocess
import tkinter as tk
from tkinter import messagebox, filedialog
from typing import Callable, List, Optional

from engine import template_store as ts
from engine import pack_store
from engine.paths import TEMPLATES_DIR, app_root
from gui import theme as T
from gui.widgets import Button, SectionLabel, prompt_text

try:
    from PIL import Image, ImageTk
except Exception:  # pragma: no cover - Pillow is a hard dependency at runtime
    Image = ImageTk = None


class TemplateManager(tk.Toplevel):
    THUMB = (96, 72)

    def __init__(self, parent, engine, on_change: Optional[Callable] = None):
        super().__init__(parent)
        self._engine = engine
        self._on_change = on_change
        self._thumbs: list = []  # keep PhotoImage refs alive

        self.title("Template Library")
        self.configure(bg=T.BG)
        self.geometry("720x560")
        self.minsize(560, 400)
        self.transient(parent)

        self._build_header()
        self._build_list()
        self._refresh()
        self.bind("<Escape>", lambda _: self.destroy())

    # ── construction ────────────────────────────────────────────────────────────

    def _build_header(self):
        hdr = tk.Frame(self, bg=T.BG2)
        hdr.pack(fill=tk.X)
        inner = tk.Frame(hdr, bg=T.BG2)
        inner.pack(fill=tk.X, padx=T.PAD, pady=10)

        SectionLabel(inner, "Templates", bg=T.BG2).pack(side=tk.LEFT)
        self._count = tk.Label(inner, text="0", font=T.FONT_SMALL,
                               bg=T.ACCENT, fg="#fff", padx=6)
        self._count.pack(side=tk.LEFT, padx=6)

        Button(inner, "Guided capture…", command=self._guided_capture,
               variant="primary").pack(side=tk.RIGHT, padx=(6, 0))
        Button(inner, "Delete unused", command=self._delete_unused,
               variant="ghost").pack(side=tk.RIGHT, padx=(6, 0))
        Button(inner, "Refresh", command=self._refresh,
               variant="ghost").pack(side=tk.RIGHT)
        tk.Frame(hdr, bg=T.SEP, height=1).pack(fill=tk.X, side=tk.BOTTOM)

    def _guided_capture(self):
        """Pick a pack's template spec and step-capture every image it needs."""
        path = filedialog.askopenfilename(
            parent=self, title="Choose a pack template spec",
            initialdir=str(app_root() / "packs"),
            filetypes=[("Template spec", "*.spec.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            spec = pack_store.load_template_spec(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Guided capture",
                                 f"Could not read spec:\n{exc}", parent=self)
            return
        if not spec:
            messagebox.showinfo("Guided capture",
                                "That spec lists no templates.", parent=self)
            return
        from gui.capture_wizard import CaptureWizard
        CaptureWizard(self, spec, capture_root=self.master, on_done=self._refresh)

    def _build_list(self):
        canvas = tk.Canvas(self, bg=T.BG, highlightthickness=0, bd=0)
        vsb = tk.Scrollbar(self, orient=tk.VERTICAL, command=canvas.yview,
                           bg=T.BG3, troughcolor=T.BG, width=8)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._inner = tk.Frame(canvas, bg=T.BG)
        win = canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>",
                         lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

        def _wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda _: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda _: canvas.unbind_all("<MouseWheel>"))

    # ── data / rendering ────────────────────────────────────────────────────────

    def _refresh(self):
        for w in self._inner.winfo_children():
            w.destroy()
        self._thumbs.clear()

        macros = self._engine.list_macros()
        templates = ts.list_templates()
        usage = ts.usage_by_name(macros)
        missing = ts.find_missing(macros, templates)

        self._count.configure(text=str(len(templates)))

        if missing:
            self._missing_banner(missing)

        if not templates:
            tk.Label(self._inner, text="No template images yet.",
                     bg=T.BG, fg=T.FG_DIM, font=T.FONT_H2).pack(pady=40)
            tk.Label(self._inner,
                     text="Capture one from the macro editor "
                          "(Capture Region).",
                     bg=T.BG, fg=T.FG_XDIM, font=T.FONT_SMALL).pack()
            return

        for info in templates:
            self._add_row(info, usage.get(info.name, []))

    def _missing_banner(self, missing: List[str]):
        band = tk.Frame(self._inner, bg=T.BG3)
        band.pack(fill=tk.X, padx=T.PAD, pady=(T.PAD, 4))
        tk.Label(band,
                 text=f"⚠ {len(missing)} referenced template(s) are missing: "
                      + ", ".join(missing[:6]) + ("…" if len(missing) > 6 else ""),
                 bg=T.BG3, fg=T.WARNING, font=T.FONT_SMALL,
                 wraplength=640, justify="left", padx=10, pady=8).pack(anchor="w")

    def _add_row(self, info, users: List[str]):
        row = tk.Frame(self._inner, bg=T.BG3)
        row.pack(fill=tk.X, padx=T.PAD, pady=4)

        # Thumbnail
        thumb = self._thumb_for(info.path)
        tcell = tk.Label(row, image=thumb, bg=T.BG2, width=self.THUMB[0],
                         height=self.THUMB[1])
        if thumb is None:
            tcell.configure(text="?", fg=T.FG_DIM, font=T.FONT_H2)
        tcell.image = thumb
        tcell.pack(side=tk.LEFT, padx=8, pady=8)

        # Info column
        col = tk.Frame(row, bg=T.BG3)
        col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        tk.Label(col, text=info.name, bg=T.BG3, fg=T.FG,
                 font=T.FONT_BOLD, anchor="w").pack(anchor="w")
        meta = f"{info.width}×{info.height}px · {info.size_bytes // 1024 or 1} KB"
        tk.Label(col, text=meta, bg=T.BG3, fg=T.FG_DIM,
                 font=T.FONT_SMALL, anchor="w").pack(anchor="w")

        if users:
            shown = ", ".join(users[:3]) + ("…" if len(users) > 3 else "")
            usage_txt, color = f"Used by {len(users)}: {shown}", T.SUCCESS
        else:
            usage_txt, color = "Unused", T.WARNING
        tk.Label(col, text=usage_txt, bg=T.BG3, fg=color,
                 font=T.FONT_SMALL, anchor="w").pack(anchor="w")

        # Actions
        acts = tk.Frame(row, bg=T.BG3)
        acts.pack(side=tk.RIGHT, padx=8)
        Button(acts, "Rename", command=lambda: self._rename(info),
               variant="ghost").pack(side=tk.LEFT, padx=2)
        Button(acts, "Reveal", command=lambda: self._reveal(info),
               variant="ghost").pack(side=tk.LEFT, padx=2)
        Button(acts, "Delete", command=lambda: self._delete(info, users),
               variant="danger").pack(side=tk.LEFT, padx=2)

    def _thumb_for(self, path):
        if ImageTk is None:
            return None
        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                img.thumbnail(self.THUMB)
                photo = ImageTk.PhotoImage(img)
            self._thumbs.append(photo)
            return photo
        except Exception:
            return None

    # ── actions ───────────────────────────────────────────────────────────────

    def _rename(self, info):
        new_stem = self._prompt("Rename template",
                                "New name (extension kept):",
                                os.path.splitext(info.name)[0])
        if not new_stem:
            return
        new_name = ts.build_new_filename(info.name, new_stem)
        if new_name == info.name:
            return
        try:
            ts.rename_file(info.name, new_name)
        except ValueError as exc:
            messagebox.showerror("Rename failed", str(exc), parent=self)
            return

        # Rewrite references in every macro that used the old file.
        updated = 0
        for macro in self._engine.list_macros():
            new_macro = ts.update_references(macro, info.name, new_name)
            if new_macro is not None:
                self._engine.save_macro(new_macro)
                updated += 1

        self._notify_change()
        self._refresh()
        messagebox.showinfo(
            "Renamed",
            f"Renamed to {new_name}.\nUpdated references in {updated} macro(s).",
            parent=self,
        )

    def _delete(self, info, users: List[str]):
        warn = ""
        if users:
            warn = ("\n\nWARNING: still used by "
                    f"{len(users)} macro(s): {', '.join(users[:5])}"
                    f"{'…' if len(users) > 5 else ''}.\n"
                    "Those actions will fail until you fix them.")
        if not messagebox.askyesno("Delete template",
                                   f"Delete '{info.name}'?{warn}", parent=self):
            return
        ts.delete_file(info.name)
        self._notify_change()
        self._refresh()

    def _delete_unused(self):
        macros = self._engine.list_macros()
        templates = ts.list_templates()
        usage = ts.usage_by_name(macros)
        orphans = ts.find_orphans(templates, usage)
        if not orphans:
            messagebox.showinfo("Nothing to delete",
                                "No unused templates found.", parent=self)
            return
        if not messagebox.askyesno(
            "Delete unused",
            f"Delete {len(orphans)} unused template(s)? This cannot be undone.",
            parent=self,
        ):
            return
        for info in orphans:
            ts.delete_file(info.name)
        self._notify_change()
        self._refresh()

    def _reveal(self, info):
        try:
            subprocess.run(["explorer", "/select,", str(info.path)], check=False)
        except Exception:
            try:
                os.startfile(str(info.path.parent))  # noqa: S606
            except Exception:
                messagebox.showerror("Reveal failed",
                                     f"Could not open {info.path}", parent=self)

    def _notify_change(self):
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                pass

    # ── small prompt ────────────────────────────────────────────────────────────

    def _prompt(self, title: str, label: str, initial: str = "") -> Optional[str]:
        return prompt_text(self, title, label, initial)
