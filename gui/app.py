"""
Main application window — clean productivity layout.

Layout:
  +--------------------------------------------------+
  |  Header (title + minimal controls)               |
  +------------+-------------------------------------+
  |            |                                      |
  |  Sidebar   |  Detail area (welcome / log)         |
  |  (macros)  |                                      |
  |            +--------------------------------------+
  |            |  Log drawer (collapsible)            |
  +------------+--------------------------------------+
  |  Status bar                                      |
  +--------------------------------------------------+
"""

import tkinter as tk
from tkinter import messagebox
from datetime import datetime
from typing import Optional

from engine.macro_engine import MacroEngine
from engine.hotkey_listener import HotkeyListener
from engine.entitlements import LockedFeatureError
from engine.licensing import LicenseManager
from gui import theme as T
from gui.widgets import Button, IconButton, Label, Frame, SectionLabel, Badge, ScrolledText, recolor
from gui.editor import MacroEditor
from gui.license_dialog import LicenseDialog


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Window Macro Bot")
        self.geometry("1060x680")
        self.minsize(760, 500)
        self.configure(bg=T.BG)
        self.resizable(True, True)

        # Licensing must exist before the engine so the engine can enforce
        # the user's tier on every run/save. on_change marshals to the main
        # thread so a background re-validation downgrade refreshes the badge.
        self._license = LicenseManager(
            log_fn=self._log,
            on_change=lambda: self.after(0, self._on_license_change),
        )

        self._engine  = MacroEngine(log_fn=self._log, tier_fn=self._license.tier)
        self._hotkeys = HotkeyListener(log_fn=self._log)
        self._stop_hotkey = ["ctrl", "F12"]
        self._toggle_btns: dict = {}
        self._collapsed: set = set()        # collapsed folder paths
        self._log_visible = False           # log drawer starts hidden

        self._build_ui()
        self._reload_macros()
        self._register_stop_hotkey()
        # Start licensing only after the UI exists so on_change can refresh it.
        self._license.start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self._build_header()
        self._build_sidebar()
        self._build_detail_area()
        self._build_status_bar()

    # ── header ────────────────────────────────────────────────────────────────

    def _build_header(self):
        hdr = tk.Frame(self, bg=T.BG2, height=52)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew")
        hdr.grid_propagate(False)

        inner = tk.Frame(hdr, bg=T.BG2)
        inner.pack(fill=tk.X, padx=T.PAD, pady=0)
        inner.pack_propagate(False)
        inner.configure(height=50)

        # Left: app title
        tk.Label(
            inner, text="Macro Bot",
            font=T.FONT_TITLE, bg=T.BG2, fg=T.FG,
        ).pack(side=tk.LEFT, pady=12)

        # Right: minimal action row
        right = tk.Frame(inner, bg=T.BG2)
        right.pack(side=tk.RIGHT, pady=10)

        # Plan badge (FREE / PRO) — click to open the license dialog.
        self._plan_badge = tk.Label(
            right, text="", font=T.FONT_SMALL, padx=8, pady=3,
            cursor="hand2",
        )
        self._plan_badge.pack(side=tk.LEFT, padx=(0, 8))
        self._plan_badge.bind("<Button-1>", lambda _: self._open_license())
        self._refresh_plan_badge()

        Button(right, "New Macro",  command=self._new_macro).pack(side=tk.LEFT, padx=3)
        Button(right, "New Folder", command=self._new_folder, variant="ghost").pack(side=tk.LEFT, padx=3)

        # Separator dot
        tk.Label(right, text=" ", bg=T.BG2, fg=T.FG_DIM).pack(side=tk.LEFT, padx=2)

        Button(right, "Stop All", command=self._stop_all, variant="danger").pack(side=tk.LEFT, padx=3)

        # Stop hotkey badge
        self._stop_hk_var = tk.StringVar()
        self._update_stop_hk_label()
        hk = tk.Label(
            right, textvariable=self._stop_hk_var,
            bg=T.BG3, fg=T.FG_DIM, font=T.FONT_SMALL,
            cursor="hand2", padx=8, pady=3,
        )
        hk.pack(side=tk.LEFT, padx=(8, 0))
        hk.bind("<Button-1>",  lambda _: self._change_stop_hotkey())
        hk.bind("<Enter>",     lambda _: hk.config(fg=T.FG))
        hk.bind("<Leave>",     lambda _: hk.config(fg=T.FG_DIM))

        # Bottom border
        tk.Frame(hdr, bg=T.SEP, height=1).pack(fill=tk.X, side=tk.BOTTOM)

    # ── sidebar ───────────────────────────────────────────────────────────────

    def _build_sidebar(self):
        sidebar = tk.Frame(self, bg=T.BG2, width=T.SIDEBAR_W)
        sidebar.grid(row=1, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(1, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        # Panel header
        ph = tk.Frame(sidebar, bg=T.BG2)
        ph.grid(row=0, column=0, sticky="ew", padx=T.PAD, pady=(T.PAD, 4))
        SectionLabel(ph, "Macros", bg=T.BG2).pack(side=tk.LEFT)
        self._count_badge = tk.Label(
            ph, text="0", font=T.FONT_SMALL,
            bg=T.ACCENT, fg="#fff", padx=6, pady=0,
        )
        self._count_badge.pack(side=tk.LEFT, padx=6)

        # Extra buttons (Images, Arrange, Reload) — tucked right
        btn_row = tk.Frame(ph, bg=T.BG2)
        btn_row.pack(side=tk.RIGHT)
        tk.Label(btn_row, text="Images", font=T.FONT_SMALL, bg=T.BG2,
                 fg=T.FG_DIM, cursor="hand2", padx=4).pack(side=tk.LEFT)
        btn_row.winfo_children()[-1].bind("<Button-1>", lambda _: self._open_templates())
        btn_row.winfo_children()[-1].bind("<Enter>", lambda e: e.widget.config(fg=T.ACCENT))
        btn_row.winfo_children()[-1].bind("<Leave>", lambda e: e.widget.config(fg=T.FG_DIM))
        tk.Label(btn_row, text="Arrange", font=T.FONT_SMALL, bg=T.BG2,
                 fg=T.FG_DIM, cursor="hand2", padx=4).pack(side=tk.LEFT)
        btn_row.winfo_children()[-1].bind("<Button-1>", lambda _: self._open_arranger())
        btn_row.winfo_children()[-1].bind("<Enter>", lambda e: e.widget.config(fg=T.ACCENT))
        btn_row.winfo_children()[-1].bind("<Leave>", lambda e: e.widget.config(fg=T.FG_DIM))
        tk.Label(btn_row, text="Reload", font=T.FONT_SMALL, bg=T.BG2,
                 fg=T.FG_DIM, cursor="hand2", padx=4).pack(side=tk.LEFT)
        btn_row.winfo_children()[-1].bind("<Button-1>", lambda _: self._reload_macros())
        btn_row.winfo_children()[-1].bind("<Enter>", lambda e: e.widget.config(fg=T.ACCENT))
        btn_row.winfo_children()[-1].bind("<Leave>", lambda e: e.widget.config(fg=T.FG_DIM))

        # Scrollable list
        canvas = tk.Canvas(sidebar, bg=T.BG2, highlightthickness=0, bd=0)
        vsb = tk.Scrollbar(sidebar, orient=tk.VERTICAL, command=canvas.yview,
                           bg=T.BG3, troughcolor=T.BG2, width=6)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.grid(row=1, column=0, sticky="nsew")
        vsb.grid(row=1, column=1, sticky="ns")

        self._list_inner  = tk.Frame(canvas, bg=T.BG2)
        self._list_window = canvas.create_window((0, 0), window=self._list_inner, anchor="nw")

        self._list_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(self._list_window, width=e.width),
        )

        def _wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda _: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda _: canvas.unbind_all("<MouseWheel>"))

        self._list_canvas = canvas

        # Right border separator
        tk.Frame(self, bg=T.SEP, width=1).grid(row=1, column=0, sticky="nse")

    # ── detail area (right side) ──────────────────────────────────────────────

    def _build_detail_area(self):
        detail = tk.Frame(self, bg=T.BG)
        detail.grid(row=1, column=1, sticky="nsew")
        detail.grid_rowconfigure(0, weight=1)
        detail.grid_rowconfigure(1, weight=0)
        detail.grid_columnconfigure(0, weight=1)

        # Welcome / info panel
        welcome = tk.Frame(detail, bg=T.BG)
        welcome.grid(row=0, column=0, sticky="nsew")
        center = tk.Frame(welcome, bg=T.BG)
        center.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(center, text="Macro Bot", font=("Segoe UI", 20, "bold"),
                 bg=T.BG, fg=T.FG_DIM).pack()
        tk.Label(center, text="Select a macro to run, or create a new one.",
                 font=T.FONT, bg=T.BG, fg=T.FG_XDIM).pack(pady=(4, 16))

        shortcut_info = [
            ("New Macro", "Click  New Macro  in the header"),
            ("Run / Stop", "Click  ▶  or use the assigned hotkey"),
            ("Stop All",   "+".join(self._stop_hotkey)),
        ]
        for label, hint in shortcut_info:
            row = tk.Frame(center, bg=T.BG)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=label, font=T.FONT_BOLD, bg=T.BG,
                     fg=T.FG_DIM, width=12, anchor="e").pack(side=tk.LEFT)
            tk.Label(row, text=hint, font=T.FONT_SMALL, bg=T.BG,
                     fg=T.FG_XDIM, anchor="w").pack(side=tk.LEFT, padx=(8, 0))

        self._welcome = welcome

        # Log drawer (collapsible, starts hidden)
        self._log_frame = tk.Frame(detail, bg=T.BG2)
        # Header bar for the drawer
        log_hdr = tk.Frame(self._log_frame, bg=T.BG2)
        log_hdr.pack(fill=tk.X)
        tk.Frame(log_hdr, bg=T.SEP, height=1).pack(fill=tk.X, side=tk.TOP)
        log_hdr_inner = tk.Frame(log_hdr, bg=T.BG2)
        log_hdr_inner.pack(fill=tk.X, padx=T.PAD, pady=4)
        SectionLabel(log_hdr_inner, "Log", bg=T.BG2).pack(side=tk.LEFT)
        tk.Label(log_hdr_inner, text="Clear", font=T.FONT_SMALL, bg=T.BG2,
                 fg=T.FG_DIM, cursor="hand2").pack(side=tk.RIGHT)
        log_hdr_inner.winfo_children()[-1].bind("<Button-1>", lambda _: self._clear_log())
        tk.Label(log_hdr_inner, text="Hide", font=T.FONT_SMALL, bg=T.BG2,
                 fg=T.FG_DIM, cursor="hand2").pack(side=tk.RIGHT, padx=(0, 10))
        log_hdr_inner.winfo_children()[-1].bind("<Button-1>", lambda _: self._toggle_log())

        self._log_box = ScrolledText(self._log_frame, state=tk.DISABLED, height=10)
        self._log_box.pack(fill=tk.BOTH, expand=True, padx=(T.PAD, 6), pady=(0, 6))

        self._log_box.text.tag_configure("ts",   foreground=T.FG_XDIM)
        self._log_box.text.tag_configure("info", foreground=T.FG_DIM)
        self._log_box.text.tag_configure("ok",   foreground=T.SUCCESS)
        self._log_box.text.tag_configure("warn", foreground=T.WARNING)
        self._log_box.text.tag_configure("err",  foreground=T.DANGER)

    def _toggle_log(self):
        self._log_visible = not self._log_visible
        if self._log_visible:
            self._log_frame.grid(row=1, column=0, sticky="nsew")
            # Give log drawer some weight so it's visible
            self._log_frame.master.grid_rowconfigure(1, weight=1, minsize=150)
        else:
            self._log_frame.grid_forget()
            self._log_frame.master.grid_rowconfigure(1, weight=0, minsize=0)

    # ── status bar ────────────────────────────────────────────────────────────

    def _build_status_bar(self):
        bar = tk.Frame(self, bg=T.BG2, height=26)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        tk.Frame(bar, bg=T.SEP, height=1).pack(fill=tk.X, side=tk.TOP)

        inner = tk.Frame(bar, bg=T.BG2)
        inner.pack(fill=tk.X, padx=T.PAD)

        self._status_var = tk.StringVar(value="Ready")
        tk.Label(
            inner, textvariable=self._status_var,
            bg=T.BG2, fg=T.FG_DIM, font=T.FONT_SMALL, anchor="w",
        ).pack(side=tk.LEFT)

        # Log toggle (right side of status bar)
        log_toggle = tk.Label(
            inner, text="Show Log", font=T.FONT_SMALL, bg=T.BG2,
            fg=T.FG_DIM, cursor="hand2", padx=4,
        )
        log_toggle.pack(side=tk.RIGHT)
        log_toggle.bind("<Button-1>", lambda _: self._toggle_log())
        log_toggle.bind("<Enter>", lambda e: e.widget.config(fg=T.ACCENT))
        log_toggle.bind("<Leave>", lambda e: e.widget.config(fg=T.FG_DIM))
        self._log_toggle_label = log_toggle

    # ── macro list rendering ──────────────────────────────────────────────────

    def _rebuild_list(self):
        self._toggle_btns.clear()
        for w in self._list_inner.winfo_children():
            w.destroy()

        macros = self._engine.list_macros()
        self._count_badge.configure(text=str(len(macros)))

        # Group by folder
        tree: dict = {}
        for m in macros:
            tree.setdefault(m.get("_folder", ""), []).append(m)
        for f in self._engine.list_folders():
            tree.setdefault(f, [])

        # Empty state
        if not macros and not tree.keys() - {""}:
            pad = tk.Frame(self._list_inner, bg=T.BG2)
            pad.pack(fill=tk.BOTH, expand=True, pady=60)
            tk.Label(pad, text="No macros yet",
                     bg=T.BG2, fg=T.FG_DIM, font=T.FONT_H2).pack()
            tk.Label(pad, text='Click "New Macro" above',
                     bg=T.BG2, fg=T.FG_XDIM, font=T.FONT_SMALL).pack(pady=4)
            return

        # Root macros
        for macro in sorted(tree.get("", []), key=lambda m: m["name"].lower()):
            self._add_macro_row(macro, self._list_inner)

        # Folders
        for folder in sorted(f for f in tree.keys() if f):
            self._add_folder_section(folder, tree[folder])

    def _add_folder_section(self, folder: str, macros: list):
        collapsed = folder in self._collapsed

        # Folder header — clean, minimal
        hdr = tk.Frame(self._list_inner, bg=T.BG2)
        hdr.pack(fill=tk.X, padx=T.PAD, pady=(10, 2))

        arrow = ">" if collapsed else "v"
        label_text = f"{arrow}  {folder}"
        title = tk.Label(
            hdr, text=label_text,
            font=T.FONT_SMALL, bg=T.BG2, fg=T.FG_DIM,
            cursor="hand2", anchor="w",
        )
        title.pack(side=tk.LEFT, fill=tk.X, expand=True)
        title.bind("<Button-1>", lambda _, f=folder: self._toggle_folder(f))
        title.bind("<Enter>", lambda e: e.widget.config(fg=T.FG))
        title.bind("<Leave>", lambda e: e.widget.config(fg=T.FG_DIM))

        # Macro count
        tk.Label(hdr, text=str(len(macros)), font=T.FONT_SMALL,
                 bg=T.BG2, fg=T.FG_XDIM).pack(side=tk.LEFT, padx=4)

        # Folder actions (small, muted)
        for icon, cmd in [
            ("▶", lambda f=folder: self._run_folder(f)),
            ("+", lambda f=folder: self._new_macro(folder=f)),
            ("...", lambda f=folder: self._folder_menu(f)),
        ]:
            lbl = tk.Label(hdr, text=icon, font=T.FONT_SMALL, bg=T.BG2,
                           fg=T.FG_XDIM, cursor="hand2", padx=3)
            lbl.pack(side=tk.LEFT)
            lbl.bind("<Button-1>", lambda _, c=cmd: c())
            lbl.bind("<Enter>", lambda e: e.widget.config(fg=T.ACCENT))
            lbl.bind("<Leave>", lambda e: e.widget.config(fg=T.FG_XDIM))

        # Folder body
        if not collapsed:
            body = tk.Frame(self._list_inner, bg=T.BG2)
            body.pack(fill=tk.X, padx=(8, 0))
            if not macros:
                tk.Label(body, text="  Empty folder",
                         font=T.FONT_SMALL, bg=T.BG2, fg=T.FG_XDIM,
                         anchor="w").pack(fill=tk.X, padx=T.PAD, pady=4)
            else:
                for m in sorted(macros, key=lambda m: m["name"].lower()):
                    self._add_macro_row(m, body)

    def _folder_menu(self, folder: str):
        """Right-click-style menu for folder actions."""
        menu = tk.Menu(self, tearoff=0, bg=T.BG3, fg=T.FG,
                       activebackground=T.ACCENT, activeforeground="#fff",
                       font=T.FONT_SMALL, bd=0)
        menu.add_command(label="Rename folder", command=lambda: self._rename_folder(folder))
        menu.add_command(label="Delete folder", command=lambda: self._delete_folder(folder))
        menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def _toggle_folder(self, folder: str):
        if folder in self._collapsed:
            self._collapsed.discard(folder)
        else:
            self._collapsed.add(folder)
        self._rebuild_list()

    def _add_macro_row(self, macro: dict, parent=None):
        if parent is None:
            parent = self._list_inner
        name   = macro["name"]
        is_bg  = macro.get("background", False)
        is_run = self._engine.is_running(name)

        # Row container — clean, minimal
        row = tk.Frame(parent, bg=T.BG2)
        row.pack(fill=tk.X, padx=6, pady=1)

        inner = tk.Frame(row, bg=T.BG3)
        inner.pack(fill=tk.X, ipady=6)
        inner.columnconfigure(0, weight=0, minsize=8)   # status dot
        inner.columnconfigure(1, weight=1)               # name + info
        inner.columnconfigure(2, weight=0)               # hotkey badge
        inner.columnconfigure(3, weight=0, minsize=80)   # buttons

        # Status dot (green=running, dim=idle)
        dot_color = T.SUCCESS if is_run else T.FG_XDIM
        dot = tk.Label(inner, text="\u25cf", font=("Segoe UI", 7),
                       bg=T.BG3, fg=dot_color, padx=6)
        dot.grid(row=0, column=0, rowspan=2, sticky="w", padx=(6, 0))

        # Name
        tk.Label(
            inner, text=name,
            font=T.FONT, bg=T.BG3, fg=T.FG, anchor="w",
        ).grid(row=0, column=1, sticky="w", padx=(4, 8), pady=(4, 0))

        # Subtitle (description or BG badge)
        subtitle_parts = []
        if macro.get("description"):
            subtitle_parts.append(macro["description"][:40])
        if is_bg:
            tw = macro.get("target_window", "")
            subtitle_parts.append(f"BG: {tw[:20]}" if tw else "Background")
        subtitle = "  |  ".join(subtitle_parts) if subtitle_parts else ""
        if subtitle:
            tk.Label(
                inner, text=subtitle,
                font=T.FONT_SMALL, bg=T.BG3, fg=T.FG_DIM, anchor="w",
            ).grid(row=1, column=1, sticky="w", padx=(4, 8), pady=(0, 4))

        # Hotkey badge (if assigned)
        trigger = macro.get("trigger", {})
        if trigger.get("keys"):
            hk_str = "+".join(trigger["keys"])
            tk.Label(
                inner, text=hk_str,
                font=T.FONT_SMALL, bg=T.BG2, fg=T.FG_DIM, padx=5, pady=1,
            ).grid(row=0, column=2, rowspan=2, padx=(0, 4))

        # Action buttons — appear on right
        btns = tk.Frame(inner, bg=T.BG3)
        btns.grid(row=0, column=3, rowspan=2, sticky="e", padx=(0, 6))

        # Play / Stop toggle
        toggle = IconButton(
            btns, "■" if is_run else "▶",
            command=lambda n=name: self._toggle_macro(n),
            bg=T.DANGER if is_run else T.SUCCESS,
            hover_bg="#f87171" if is_run else "#4ade80",
        )
        toggle.pack(side=tk.LEFT, padx=1)
        self._toggle_btns[name] = toggle

        # Edit
        IconButton(btns, "✎",
                   command=lambda m=macro: self._edit_macro(m),
                   bg=T.BG2, hover_bg=T.BORDER).pack(side=tk.LEFT, padx=1)

        # More menu (move, delete)
        more = tk.Label(btns, text="...", font=T.FONT_BOLD, bg=T.BG3,
                        fg=T.FG_DIM, cursor="hand2", padx=4)
        more.pack(side=tk.LEFT, padx=1)
        more.bind("<Button-1>", lambda _, n=name: self._macro_menu(n))
        more.bind("<Enter>", lambda e: e.widget.config(fg=T.FG))
        more.bind("<Leave>", lambda e: e.widget.config(fg=T.FG_DIM))

        # Hover effect
        def _enter(e):
            recolor(inner, T.BG4)
        def _leave(e):
            recolor(inner, T.BG3)
        for w in [inner, btns]:
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)

    def _macro_menu(self, name: str):
        menu = tk.Menu(self, tearoff=0, bg=T.BG3, fg=T.FG,
                       activebackground=T.ACCENT, activeforeground="#fff",
                       font=T.FONT_SMALL, bd=0)
        menu.add_command(label="Move to folder...", command=lambda: self._move_macro(name))
        menu.add_separator()
        menu.add_command(label="Delete", command=lambda: self._delete_macro(name))
        menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    # ── actions ───────────────────────────────────────────────────────────────

    def _reload_macros(self):
        self._hotkeys.unregister_all()
        names = self._engine.load_all()
        self._log(f"Loaded {len(names)} macro(s)")

        for macro in self._engine.list_macros():
            trigger = macro.get("trigger", {})
            if trigger.get("type") == "hotkey" and trigger.get("keys"):
                n = macro["name"]
                self._hotkeys.register(
                    n, trigger["keys"], lambda name=n: self._toggle_macro(name)
                )

        self._register_stop_hotkey()
        self._rebuild_list()
        self._status("Ready")

    def _new_macro(self, folder: str = ""):
        self._pending_new_folder = folder
        MacroEditor(self, save_callback=self._save_macro)

    def _new_folder(self):
        name = self._prompt("New Folder", "Folder name:", "")
        if not name:
            return
        try:
            self._engine.create_folder(name)
            self._log(f"Created folder '{name}'")
            self._rebuild_list()
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)

    def _rename_folder(self, folder: str):
        new_name = self._prompt("Rename Folder", "New name:", folder)
        if not new_name or new_name == folder:
            return
        try:
            self._engine.rename_folder(folder, new_name)
            if folder in self._collapsed:
                self._collapsed.discard(folder)
                self._collapsed.add(new_name)
            self._log(f"Renamed folder '{folder}' -> '{new_name}'")
            self._rebuild_list()
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)

    def _delete_folder(self, folder: str):
        if not messagebox.askyesno(
            "Delete Folder",
            f"Delete folder '{folder}' and all macros inside?",
            parent=self,
        ):
            return
        for m in self._engine.list_macros():
            f = m.get("_folder", "")
            if f == folder or f.startswith(folder + "/"):
                self._hotkeys.unregister(m["name"])
        try:
            self._engine.delete_folder(folder)
            self._collapsed.discard(folder)
            self._log(f"Deleted folder '{folder}'")
            self._rebuild_list()
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)

    def _run_folder(self, folder: str):
        names = [
            m["name"] for m in self._engine.list_macros()
            if m.get("_folder", "") == folder
            and not self._engine.is_running(m["name"])
        ]
        if not names:
            self._log(f"Nothing to run in '{folder}'", tag="warn")
            return

        mode = self._choose_run_mode(folder, len(names))
        if mode is None:
            return
        parallel = (mode == "parallel")

        def _each(n):
            self.after(0, lambda: self._update_toggle_btn(n, running=False))

        self._log(
            f"Running {len(names)} macro(s) in '{folder}' "
            f"({'parallel' if parallel else 'sequential'})",
            tag="ok",
        )
        for n in names:
            self._update_toggle_btn(n, running=True)
        self._engine.run_folder(folder, parallel=parallel, on_each_done=_each)

    def _choose_run_mode(self, folder: str, count: int) -> Optional[str]:
        dlg = tk.Toplevel(self)
        dlg.title("Run Folder")
        dlg.configure(bg=T.BG)
        T.center_on_parent(dlg, self, 360, 180)
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        Label(dlg, text=f"Run {count} macro(s) in '{folder}'",
              bold=True).pack(pady=(20, 4), padx=16)
        Label(dlg, text="Choose execution mode:", dim=True).pack(padx=16)

        result = {"value": None}
        def _pick(mode):
            result["value"] = mode
            dlg.destroy()

        row = Frame(dlg)
        row.pack(pady=20)
        Button(row, "Parallel", command=lambda: _pick("parallel"),
               variant="success").pack(side=tk.LEFT, padx=4)
        Button(row, "Sequential", command=lambda: _pick("sequential"),
               variant="primary").pack(side=tk.LEFT, padx=4)
        Button(row, "Cancel", command=dlg.destroy,
               variant="ghost").pack(side=tk.LEFT, padx=4)
        dlg.bind("<Escape>", lambda _: dlg.destroy())
        self.wait_window(dlg)
        return result["value"]

    def _open_arranger(self):
        from gui.arranger import WindowArranger
        WindowArranger(self)

    def _open_templates(self):
        from gui.template_manager import TemplateManager
        TemplateManager(self, self._engine, on_change=self._rebuild_list)

    def _edit_macro(self, macro: dict):
        MacroEditor(self, save_callback=self._save_macro, macro=macro)

    def _save_macro(self, macro: dict):
        if "_folder" not in macro:
            existing = self._engine.get_folder(macro["name"])
            if existing:
                macro["_folder"] = existing
            else:
                macro["_folder"] = getattr(self, "_pending_new_folder", "") or ""
        self._pending_new_folder = ""

        try:
            path = self._engine.save_macro(macro)
        except LockedFeatureError as exc:
            self._show_upgrade(exc.message)
            return
        self._log(f"Saved '{macro['name']}'")

        trigger = macro.get("trigger", {})
        if trigger.get("type") == "hotkey" and trigger.get("keys"):
            self._hotkeys.register(
                macro["name"], trigger["keys"],
                lambda n=macro["name"]: self._toggle_macro(n),
            )

        self._rebuild_list()
        self._status(f"Saved '{macro['name']}'")

    def _delete_macro(self, name: str):
        if not messagebox.askyesno("Delete", f"Delete '{name}'?", parent=self):
            return
        self._hotkeys.unregister(name)
        self._engine.delete_macro(name)
        self._rebuild_list()
        self._log(f"Deleted '{name}'")

    def _move_macro(self, name: str):
        current = self._engine.get_folder(name)
        folders = [""] + self._engine.list_folders()
        choice = self._choose_folder("Move Macro", f"Move '{name}' to:", folders, current)
        if choice is None or choice == current:
            return
        try:
            self._engine.move_macro(name, choice)
            self._log(f"Moved '{name}' -> '{choice or '/'}'")
            self._rebuild_list()
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)

    def _toggle_macro(self, name: str):
        if self._engine.is_running(name):
            self._engine.stop(name)
            self._log(f"Stopped '{name}'", tag="warn")
            self._status(f"Stopped '{name}'")
            self._update_toggle_btn(name, running=False)
        else:
            reason = self._engine.locked_reason(name)
            if reason:
                self._show_upgrade(reason)
                return
            self._log(f"Running '{name}'", tag="ok")
            self._status(f"Running '{name}'")
            self._engine.run(
                name,
                on_done=lambda n: self.after(0, lambda: self._on_macro_done(n)),
            )
            self._update_toggle_btn(name, running=True)

    def _on_macro_done(self, name: str):
        self._status(f"'{name}' finished")
        self._update_toggle_btn(name, running=False)

    def _update_toggle_btn(self, name: str, running: bool):
        btn = self._toggle_btns.get(name)
        if btn is None or not btn.winfo_exists():
            return
        if running:
            btn.configure(text="\u25a0", bg=T.DANGER, activebackground="#f87171")
            btn._bg = T.DANGER
            btn._hover = "#f87171"
        else:
            btn.configure(text="\u25b6", bg=T.SUCCESS, activebackground="#4ade80")
            btn._bg = T.SUCCESS
            btn._hover = "#4ade80"

    def _stop_all(self):
        self._engine.stop_all()
        for name in list(self._toggle_btns):
            self._update_toggle_btn(name, running=False)
        self._log("All macros stopped", tag="warn")
        self._status("Stopped")

    # ── licensing ─────────────────────────────────────────────────────────────

    def _refresh_plan_badge(self):
        """Update the header plan chip to reflect the current tier."""
        if not hasattr(self, "_plan_badge") or not self._plan_badge.winfo_exists():
            return
        if self._license.is_pro():
            self._plan_badge.configure(text="PRO", bg=T.SUCCESS, fg="#06281a")
        else:
            self._plan_badge.configure(text="FREE · Upgrade", bg=T.BG3, fg=T.WARNING)

    def _open_license(self, reason: str = None):
        LicenseDialog(self, self._license,
                      on_change=self._on_license_change, reason=reason)

    def _on_license_change(self):
        self._refresh_plan_badge()
        self._rebuild_list()
        tier = "Pro" if self._license.is_pro() else "Free"
        self._status(f"Plan: {tier}")

    def _show_upgrade(self, reason: str):
        """Open the upgrade dialog with the reason a feature was blocked."""
        self._log(reason, tag="warn")
        self._open_license(reason=reason)

    # ── global stop hotkey ────────────────────────────────────────────────────

    def _register_stop_hotkey(self):
        self._hotkeys.register(
            "__stop_all__",
            self._stop_hotkey,
            callback=lambda: self.after(0, self._stop_all),
        )

    def _update_stop_hk_label(self):
        hk = "+".join(self._stop_hotkey)
        self._stop_hk_var.set(f"Stop: {hk}")

    def _change_stop_hotkey(self):
        dlg = tk.Toplevel(self)
        dlg.title("Change Stop Hotkey")
        dlg.configure(bg=T.BG)
        T.center_on_parent(dlg, self, 340, 170)
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        Label(dlg, text="Emergency Stop Hotkey", bold=True).pack(pady=(18, 4))
        Label(dlg, text="Current: " + "+".join(self._stop_hotkey), dim=True).pack()
        Label(dlg, text="New hotkey (e.g. ctrl+F12):").pack(pady=(12, 2))

        entry = tk.Entry(
            dlg, bg=T.BG3, fg=T.FG, insertbackground=T.FG,
            font=T.FONT_MONO, relief=tk.FLAT, highlightthickness=1,
            highlightcolor=T.ACCENT, highlightbackground=T.BORDER,
        )
        entry.insert(0, "+".join(self._stop_hotkey))
        entry.pack(padx=20, fill=tk.X, ipady=4)
        entry.focus_set()

        def _apply():
            raw = entry.get().strip()
            if not raw:
                return
            keys = [k.strip() for k in raw.replace(",", "+").split("+") if k.strip()]
            self._hotkeys.unregister("__stop_all__")
            self._stop_hotkey = keys
            self._register_stop_hotkey()
            self._update_stop_hk_label()
            self._log(f"Stop hotkey -> {'+'.join(keys)}")
            dlg.destroy()

        row = Frame(dlg)
        row.pack(pady=10)
        Button(row, "Apply",  command=_apply,      variant="success").pack(side=tk.LEFT, padx=4)
        Button(row, "Cancel", command=dlg.destroy,  variant="ghost"  ).pack(side=tk.LEFT, padx=4)
        dlg.bind("<Return>", lambda _: _apply())

    # ── log ───────────────────────────────────────────────────────────────────

    def _log(self, msg: str, tag: str = "info"):
        def _append():
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_box.configure(state=tk.NORMAL)
            self._log_box.text.insert(tk.END, f"{ts}  ", "ts")
            self._log_box.text.insert(tk.END, msg + "\n", tag)
            self._log_box.text.see(tk.END)
            self._log_box.configure(state=tk.DISABLED)
            # Auto-show log on errors/warnings
            if tag in ("err", "warn", "ok") and not self._log_visible:
                self._toggle_log()
        self.after(0, _append)

    def _clear_log(self):
        self._log_box.configure(state=tk.NORMAL)
        self._log_box.delete("1.0", tk.END)
        self._log_box.configure(state=tk.DISABLED)

    def _status(self, msg: str):
        self.after(0, lambda: self._status_var.set(msg))

    # ── small dialogs ─────────────────────────────────────────────────────────

    def _prompt(self, title: str, label: str, initial: str = "") -> Optional[str]:
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.configure(bg=T.BG)
        T.center_on_parent(dlg, self, 340, 155)
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        Label(dlg, text=label).pack(pady=(18, 6), padx=20, anchor="w")
        entry = tk.Entry(
            dlg, bg=T.BG3, fg=T.FG, insertbackground=T.FG,
            font=T.FONT, relief=tk.FLAT, highlightthickness=1,
            highlightcolor=T.ACCENT, highlightbackground=T.BORDER,
        )
        entry.insert(0, initial)
        entry.pack(padx=20, fill=tk.X, ipady=5)
        entry.focus_set()
        entry.select_range(0, tk.END)

        result = {"value": None}
        def _ok():
            result["value"] = entry.get().strip()
            dlg.destroy()

        row = Frame(dlg)
        row.pack(pady=12)
        Button(row, "OK",     command=_ok,          variant="success").pack(side=tk.LEFT, padx=4)
        Button(row, "Cancel", command=dlg.destroy,  variant="ghost"  ).pack(side=tk.LEFT, padx=4)
        dlg.bind("<Return>", lambda _: _ok())
        dlg.bind("<Escape>", lambda _: dlg.destroy())
        self.wait_window(dlg)
        return result["value"] or None

    def _choose_folder(self, title: str, label: str,
                       folders: list, current: str) -> Optional[str]:
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.configure(bg=T.BG)
        T.center_on_parent(dlg, self, 360, 340)
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        Label(dlg, text=label, bold=True).pack(pady=(14, 4), padx=16, anchor="w")

        var = tk.StringVar(value=current)
        lst = tk.Frame(dlg, bg=T.BG2)
        lst.pack(padx=16, pady=4, fill=tk.BOTH, expand=True)

        for f in folders:
            display = "/  (root)" if f == "" else f
            rb = tk.Radiobutton(
                lst, text=display, variable=var, value=f,
                bg=T.BG2, fg=T.FG, selectcolor=T.BG3,
                activebackground=T.BG2, activeforeground=T.FG,
                font=T.FONT, anchor="w", padx=6, pady=2,
                highlightthickness=0,
            )
            rb.pack(fill=tk.X)

        Label(dlg, text="Or create new:", dim=True).pack(padx=16, anchor="w", pady=(8, 2))
        new_entry = tk.Entry(
            dlg, bg=T.BG3, fg=T.FG, insertbackground=T.FG,
            font=T.FONT, relief=tk.FLAT, highlightthickness=1,
            highlightcolor=T.ACCENT, highlightbackground=T.BORDER,
        )
        new_entry.pack(padx=16, fill=tk.X, ipady=4)

        result = {"value": None}
        def _ok():
            new = new_entry.get().strip()
            result["value"] = new if new else var.get()
            dlg.destroy()

        row = Frame(dlg)
        row.pack(pady=10)
        Button(row, "Move",   command=_ok,          variant="success").pack(side=tk.LEFT, padx=4)
        Button(row, "Cancel", command=dlg.destroy,  variant="ghost"  ).pack(side=tk.LEFT, padx=4)
        dlg.bind("<Return>", lambda _: _ok())
        dlg.bind("<Escape>", lambda _: dlg.destroy())
        self.wait_window(dlg)
        return result["value"]

    # ── close ─────────────────────────────────────────────────────────────────

    def _on_close(self):
        self._engine.stop_all()
        self._hotkeys.unregister_all()
        self._license.stop()
        self.destroy()
