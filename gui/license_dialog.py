"""
License / upgrade dialog.

Serves two jobs with one window:
  * Activate a license key (enter key → validate against the server).
  * Upsell Pro (a "Get Pro" button to the purchase page, plus a reason banner
    shown when the user just tried to use a locked feature).

Network activation runs on a worker thread so the UI never freezes; results are
marshalled back with ``after`` (tkinter is single-threaded).
"""

import threading
import tkinter as tk
import webbrowser
from typing import Callable, Optional

from engine import product_config as cfg
from engine.entitlements import Tier
from engine.licensing import LicenseManager
from gui import theme as T
from gui.widgets import Button, Frame, Label


class LicenseDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        manager: LicenseManager,
        on_change: Optional[Callable[[], None]] = None,
        reason: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._on_change = on_change

        self.title(f"{cfg.PRODUCT_NAME} — License")
        self.configure(bg=T.BG)
        self.resizable(False, False)
        self.transient(parent)
        T.center_on_parent(self, parent, 440, 430)
        self.grab_set()

        self._build(reason)
        self.bind("<Escape>", lambda _: self.destroy())

    # ── construction ────────────────────────────────────────────────────────────

    def _build(self, reason: Optional[str]) -> None:
        is_pro = self._manager.is_pro()

        # Reason banner (only when sent here by a locked feature)
        if reason:
            banner = tk.Label(
                self, text=reason, bg=T.BG3, fg=T.WARNING,
                font=T.FONT_SMALL, wraplength=400, justify="left",
                padx=12, pady=8,
            )
            banner.pack(fill=tk.X, padx=16, pady=(16, 0))

        # Tier header
        head = Frame(self)
        head.pack(fill=tk.X, padx=16, pady=(16, 4))
        Label(head, text="Current plan:", dim=True).pack(side=tk.LEFT)
        tier_text = "PRO" if is_pro else "FREE"
        tier_color = T.SUCCESS if is_pro else T.FG_DIM
        tk.Label(
            head, text=tier_text, bg=T.BG, fg=tier_color, font=T.FONT_TITLE,
        ).pack(side=tk.LEFT, padx=8)

        status = self._manager.status()
        if is_pro and status.get("expiry"):
            Label(self, text=f"Renews / expires: {status['expiry'][:10]}",
                  dim=True).pack(anchor="w", padx=16)

        # Feature summary
        feats = (
            "Pro unlocks: background mode · image / pixel / rectangle "
            "detection · loops · multi-window parallel runs."
        )
        tk.Label(
            self, text=feats, bg=T.BG, fg=T.FG_DIM, font=T.FONT_SMALL,
            wraplength=400, justify="left",
        ).pack(anchor="w", padx=16, pady=(8, 4))

        # Key entry
        Label(self, text="License key:").pack(anchor="w", padx=16, pady=(10, 2))
        self._entry = tk.Entry(
            self, bg=T.BG3, fg=T.FG, insertbackground=T.FG,
            font=T.FONT_MONO, relief=tk.FLAT, highlightthickness=1,
            highlightcolor=T.ACCENT, highlightbackground=T.BORDER,
        )
        self._entry.pack(padx=16, fill=tk.X, ipady=5)
        self._entry.focus_set()
        self._entry.bind("<Return>", lambda _: self._activate())

        # Status line
        self._status = tk.StringVar(value="")
        self._status_lbl = tk.Label(
            self, textvariable=self._status, bg=T.BG, fg=T.FG_DIM,
            font=T.FONT_SMALL, wraplength=400, justify="left",
        )
        self._status_lbl.pack(anchor="w", padx=16, pady=(6, 0))

        if not cfg.keyauth_configured():
            self._set_status(
                "Note: licensing isn't configured in this build yet "
                "(see GO-COMMERCIAL.md).", T.WARNING,
            )

        # Action buttons
        row = Frame(self)
        row.pack(fill=tk.X, padx=16, pady=14)
        self._activate_btn = Button(row, "Activate", command=self._activate,
                                    variant="success")
        self._activate_btn.pack(side=tk.LEFT)
        Button(row, "Get Pro", command=self._buy,
               variant="primary").pack(side=tk.LEFT, padx=6)
        Button(row, "Community", command=self._community,
               variant="ghost").pack(side=tk.LEFT)
        if is_pro:
            Button(row, "Remove", command=self._remove,
                   variant="ghost").pack(side=tk.RIGHT)

        # Machine id (support reference)
        tk.Label(
            self, text=f"Machine ID: {status['hwid']}…", bg=T.BG, fg=T.FG_XDIM,
            font=T.FONT_SMALL,
        ).pack(anchor="w", padx=16, pady=(0, 10))

    # ── actions ───────────────────────────────────────────────────────────────

    def _set_status(self, text: str, color: str = T.FG_DIM) -> None:
        self._status.set(text)
        self._status_lbl.configure(fg=color)

    def _activate(self) -> None:
        key = self._entry.get().strip()
        if not key:
            self._set_status("Please enter a license key.", T.WARNING)
            return
        self._activate_btn.configure(state=tk.DISABLED)
        self._set_status("Activating…", T.FG_DIM)

        def work() -> None:
            ok, msg = self._manager.activate(key)
            try:  # dialog may have been closed during the network call
                self.after(0, lambda: self._on_activated(ok, msg))
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_activated(self, ok: bool, msg: str) -> None:
        if not self.winfo_exists():
            return
        self._activate_btn.configure(state=tk.NORMAL)
        if ok:
            self._set_status("Activated — Pro unlocked.", T.SUCCESS)
            if self._on_change:
                self._on_change()
            self.after(900, lambda: self.destroy() if self.winfo_exists() else None)
        else:
            self._set_status(msg or "Activation failed.", T.DANGER)

    def _buy(self) -> None:
        webbrowser.open(cfg.PURCHASE_URL)

    def _community(self) -> None:
        webbrowser.open(cfg.SUPPORT_URL)

    def _remove(self) -> None:
        self._manager.deactivate()
        if self._on_change:
            self._on_change()
        self.destroy()
