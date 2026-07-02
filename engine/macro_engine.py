"""
MacroEngine – loads, validates, runs, and manages macros.

A macro JSON file lives in the macros/ directory.
Schema reference: macros/SCHEMA.md
"""

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from engine.action_runner import run_action, ActionError
from engine.entitlements import (
    LockedFeatureError,
    Tier,
    check_can_create,
    check_macro_runnable,
    check_parallel,
    for_tier,
)
from engine.paths import MACROS_DIR


def _clean_folder(folder: str) -> str:
    """Normalize a folder path: strip slashes, forward-slash separator, no '..'."""
    if not folder:
        return ""
    f = folder.replace("\\", "/").strip("/ ")
    # Disallow parent-traversal segments
    parts = [p for p in f.split("/") if p and p not in (".", "..")]
    return "/".join(parts)


def _folder_of(path: Path) -> str:
    """Given a macro file path, return its folder relative to MACROS_DIR."""
    try:
        rel = path.relative_to(MACROS_DIR).parent.as_posix()
    except ValueError:
        return ""
    return "" if rel == "." else rel


class MacroEngine:
    def __init__(
        self,
        log_fn: Optional[Callable[[str], None]] = None,
        tier_fn: Optional[Callable[[], Tier]] = None,
    ):
        self._macros: Dict[str, Dict] = {}          # name → macro dict
        self._running: Dict[str, threading.Thread] = {}
        self._stop_flags: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._log = log_fn or print
        # Returns the user's current licensing tier. Defaults to PRO so the
        # engine is unrestricted when run from source / in tests; the packaged
        # GUI passes the real LicenseManager.tier so the .exe enforces gating.
        self._tier_fn = tier_fn or (lambda: Tier.PRO)

    # ── licensing / entitlements ────────────────────────────────────────────────

    def _entitlements(self):
        return for_tier(self._tier_fn())

    def locked_reason(self, name: str) -> Optional[str]:
        """Return an upgrade message if *name* can't run on the current tier."""
        macro = self.get_macro(name)
        if macro is None:
            return None
        return check_macro_runnable(macro, self._entitlements())

    # ── loading ───────────────────────────────────────────────────────────────

    def load_all(self) -> List[str]:
        """Recursively load every *.json under the macros directory.

        Each macro dict is tagged with a runtime-only ``_folder`` key holding
        its location relative to MACROS_DIR (posix-style, "" for root).
        """
        MACROS_DIR.mkdir(parents=True, exist_ok=True)
        loaded = []
        with self._lock:
            self._macros.clear()
        for path in sorted(MACROS_DIR.rglob("*.json")):
            try:
                macro = self._load_file(path)
                macro["_folder"] = _folder_of(path)
                with self._lock:
                    self._macros[macro["name"]] = macro
                loaded.append(macro["name"])
            except Exception as exc:
                rel = path.relative_to(MACROS_DIR) if path.is_relative_to(MACROS_DIR) else path.name
                self._log(f"[load error] {rel}: {exc}")
        return loaded

    def load_file(self, path: str) -> str:
        """Load a single macro file; returns macro name."""
        p = Path(path)
        macro = self._load_file(p)
        if p.is_relative_to(MACROS_DIR):
            macro["_folder"] = _folder_of(p)
        with self._lock:
            self._macros[macro["name"]] = macro
        return macro["name"]

    def _load_file(self, path: Path) -> Dict:
        with open(path, "r", encoding="utf-8") as f:
            macro = json.load(f)
        _validate(macro)
        return macro

    def save_macro(self, macro: Dict, folder: Optional[str] = None) -> Path:
        """Validate and save a macro dict to macros/<folder>/<name>.json.

        If *folder* is None, uses ``macro["_folder"]`` (or root if absent).
        Internal keys prefixed with ``_`` are stripped before serialization.
        Moves the file if the macro already exists in a different folder.
        """
        _validate(macro)

        # Enforce the free-tier macro count, but only for genuinely new macros
        # (editing/saving an existing one is always allowed). The check is done
        # under the lock so two concurrent saves can't both slip past the limit.
        with self._lock:
            if macro["name"] not in self._macros:
                locked = check_can_create(len(self._macros), self._entitlements())
                if locked:
                    raise LockedFeatureError(locked, feature="max_macros")

        if folder is None:
            folder = macro.get("_folder", "")
        folder = _clean_folder(folder)

        target_dir = MACROS_DIR / folder if folder else MACROS_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        new_path = target_dir / f"{macro['name']}.json"

        # If macro moved, remove the old file.
        with self._lock:
            existing = self._macros.get(macro["name"])
        if existing is not None:
            old_folder = existing.get("_folder", "")
            old_path = (MACROS_DIR / old_folder / f"{macro['name']}.json"
                        if old_folder else MACROS_DIR / f"{macro['name']}.json")
            if old_path.exists() and old_path.resolve() != new_path.resolve():
                try:
                    old_path.unlink()
                except Exception:
                    pass

        # Serialize without runtime-only fields
        clean = {k: v for k, v in macro.items() if not k.startswith("_")}
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2)

        macro["_folder"] = folder
        with self._lock:
            self._macros[macro["name"]] = macro
        return new_path

    def delete_macro(self, name: str) -> None:
        self.stop(name)
        with self._lock:
            macro = self._macros.pop(name, None)
        folder = macro.get("_folder", "") if macro else ""
        path = (MACROS_DIR / folder / f"{name}.json"
                if folder else MACROS_DIR / f"{name}.json")
        if path.exists():
            path.unlink()

    # ── folders ───────────────────────────────────────────────────────────────

    def get_folder(self, name: str) -> str:
        """Return the folder path of a macro (posix-style, "" for root)."""
        with self._lock:
            m = self._macros.get(name)
        return m.get("_folder", "") if m else ""

    def list_folders(self) -> List[str]:
        """Return all folders under macros/ (relative posix paths), sorted.

        Includes empty folders and any parent folders implied by nested paths.
        """
        if not MACROS_DIR.exists():
            return []
        folders = set()
        for p in MACROS_DIR.rglob("*"):
            if p.is_dir():
                rel = p.relative_to(MACROS_DIR).as_posix()
                if rel and rel != ".":
                    folders.add(rel)
        return sorted(folders)

    def create_folder(self, folder: str) -> Path:
        folder = _clean_folder(folder)
        if not folder:
            raise ValueError("Folder name cannot be empty")
        path = MACROS_DIR / folder
        path.mkdir(parents=True, exist_ok=True)
        return path

    def delete_folder(self, folder: str) -> None:
        """Delete a folder and every macro inside it (recursively)."""
        folder = _clean_folder(folder)
        if not folder:
            raise ValueError("Cannot delete root folder")
        path = MACROS_DIR / folder
        if not path.exists():
            return

        # Stop and drop all macros in or under this folder.
        with self._lock:
            victims = [
                name for name, m in self._macros.items()
                if m.get("_folder", "") == folder
                or m.get("_folder", "").startswith(folder + "/")
            ]
        for name in victims:
            self.stop(name)
        with self._lock:
            for name in victims:
                self._macros.pop(name, None)

        shutil.rmtree(path)

    def rename_folder(self, old: str, new: str) -> None:
        old = _clean_folder(old)
        new = _clean_folder(new)
        if not old or not new:
            raise ValueError("Folder names cannot be empty")
        old_path = MACROS_DIR / old
        new_path = MACROS_DIR / new
        if not old_path.exists():
            raise ValueError(f"Folder '{old}' does not exist")
        if new_path.exists():
            raise ValueError(f"Folder '{new}' already exists")
        new_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.rename(new_path)

        # Update in-memory macro folders.
        with self._lock:
            for m in self._macros.values():
                f = m.get("_folder", "")
                if f == old:
                    m["_folder"] = new
                elif f.startswith(old + "/"):
                    m["_folder"] = new + f[len(old):]

    def move_macro(self, name: str, new_folder: str) -> bool:
        """Move a macro's JSON file to a different folder."""
        with self._lock:
            macro = self._macros.get(name)
        if not macro:
            return False
        new_folder = _clean_folder(new_folder)
        old_folder = macro.get("_folder", "")
        if old_folder == new_folder:
            return True

        old_path = (MACROS_DIR / old_folder / f"{name}.json"
                    if old_folder else MACROS_DIR / f"{name}.json")
        new_dir = MACROS_DIR / new_folder if new_folder else MACROS_DIR
        new_dir.mkdir(parents=True, exist_ok=True)
        new_path = new_dir / f"{name}.json"

        if new_path.exists() and new_path.resolve() != old_path.resolve():
            raise ValueError(
                f"A macro named '{name}' already exists in folder '{new_folder or '/'}'")

        if old_path.exists():
            old_path.rename(new_path)
        macro["_folder"] = new_folder
        return True

    # ── querying ──────────────────────────────────────────────────────────────

    def list_macros(self) -> List[Dict]:
        with self._lock:
            return list(self._macros.values())

    def get_macro(self, name: str) -> Optional[Dict]:
        with self._lock:
            return self._macros.get(name)

    def is_running(self, name: str) -> bool:
        with self._lock:
            t = self._running.get(name)
            return t is not None and t.is_alive()

    # ── execution ─────────────────────────────────────────────────────────────

    def run(self, name: str, on_done: Optional[Callable] = None) -> bool:
        """Start a macro in a background thread. Returns False if already running."""
        macro = self.get_macro(name)
        if macro is None:
            self._log(f"[run] macro '{name}' not found")
            return False
        if self.is_running(name):
            self._log(f"[run] macro '{name}' already running")
            return False

        locked = check_macro_runnable(macro, self._entitlements())
        if locked:
            self._log(f"[locked] {name}: {locked}")
            return False

        stop_event = threading.Event()
        with self._lock:
            self._stop_flags[name] = stop_event

        def worker():
            try:
                self._execute(macro, stop_event)
                self._log(f"[done] {name}")
            except Exception as exc:
                self._log(f"[error] {name}: {exc}")
            finally:
                with self._lock:
                    self._running.pop(name, None)
                if on_done:
                    on_done(name)

        t = threading.Thread(target=worker, daemon=True, name=f"macro-{name}")
        with self._lock:
            self._running[name] = t
        t.start()
        return True

    def run_folder(
        self,
        folder: str,
        parallel: bool = True,
        on_each_done: Optional[Callable[[str], None]] = None,
        on_all_done: Optional[Callable[[], None]] = None,
    ) -> List[str]:
        """Run every macro in *folder*.

        parallel=True  → start each macro in its own thread simultaneously.
        parallel=False → run them one after another in a single worker thread;
                         the next macro starts only after the previous one
                         finishes (or is stopped).

        Returns the list of macro names that were scheduled. Macros that are
        already running are skipped.
        """
        folder = _clean_folder(folder)
        with self._lock:
            names = sorted(
                name for name, m in self._macros.items()
                if m.get("_folder", "") == folder
            )
            running = {n for n, t in self._running.items()
                       if t is not None and t.is_alive()}
        names = [n for n in names if n not in running]
        if not names:
            if on_all_done:
                on_all_done()
            return []

        # Parallel (multi-account) runs are a Pro feature. On the free tier,
        # degrade gracefully to sequential rather than blocking entirely.
        if parallel:
            locked = check_parallel(self._entitlements())
            if locked:
                self._log(f"[locked] {locked} Running sequentially instead.")
                parallel = False

        if parallel:
            # Fire-and-forget: each macro is its own thread.
            remaining = {"n": len(names)}
            lock = threading.Lock()

            def _each(name: str):
                if on_each_done:
                    on_each_done(name)
                with lock:
                    remaining["n"] -= 1
                    done = remaining["n"] == 0
                if done and on_all_done:
                    on_all_done()

            for name in names:
                self.run(name, on_done=_each)
            return names

        # Sequential: one worker thread runs each macro's _execute in turn.
        seq_stop = threading.Event()

        def worker():
            try:
                for name in names:
                    if seq_stop.is_set():
                        break
                    macro = self.get_macro(name)
                    if macro is None:
                        continue
                    if self.is_running(name):
                        continue

                    locked = check_macro_runnable(macro, self._entitlements())
                    if locked:
                        self._log(f"[locked] {name}: {locked}")
                        if on_each_done:
                            on_each_done(name)
                        continue

                    per_stop = threading.Event()
                    with self._lock:
                        self._stop_flags[name] = per_stop
                        self._running[name] = threading.current_thread()
                    try:
                        self._execute(macro, per_stop)
                        self._log(f"[done] {name}")
                    except Exception as exc:
                        self._log(f"[error] {name}: {exc}")
                    finally:
                        with self._lock:
                            self._running.pop(name, None)
                        if on_each_done:
                            on_each_done(name)
                        # If the user hit Stop on this macro, stop the whole chain.
                        if per_stop.is_set():
                            seq_stop.set()
            finally:
                if on_all_done:
                    on_all_done()

        t = threading.Thread(target=worker, daemon=True,
                             name=f"seq-{folder or 'root'}")
        t.start()
        return names

    def stop(self, name: str) -> None:
        """Signal a running macro to stop."""
        with self._lock:
            ev = self._stop_flags.get(name)
        if ev:
            ev.set()

    def stop_all(self) -> None:
        with self._lock:
            names = list(self._stop_flags.keys())
        for name in names:
            self.stop(name)
        # Release any WGC capture sessions held for background-mode image search.
        try:
            from engine import wgc_capture
            wgc_capture.stop_all()
        except Exception:
            pass

    # ── internal execution ────────────────────────────────────────────────────

    def _execute(self, macro: Dict, stop: threading.Event) -> None:
        loop = macro.get("loop", False)
        loop_delay = macro.get("loop_delay_ms", 0) / 1000.0

        # Resolve the target hwnd ONCE at macro start — not every iteration.
        # This prevents flipping between identically-titled windows.
        resolved_hwnd = self._resolve_hwnd(macro)
        if resolved_hwnd is not None:
            macro = dict(macro, target_hwnd=resolved_hwnd)

        def _run_once():
            # Rebuild ctx each iteration so the window offset stays current
            # if the window is moved, but the hwnd is pinned from above.
            ctx = self._build_ctx(macro)
            ctx["request_stop"] = stop.set   # lets a `stop` action end the loop

            def run_actions(actions):
                for action in actions:
                    if stop.is_set():
                        return
                    run_action(action, run_actions, ctx)

            run_actions(macro["actions"])

        if loop:
            while not stop.is_set():
                _run_once()
                if loop_delay > 0 and not stop.is_set():
                    stop.wait(timeout=loop_delay)
        else:
            _run_once()

    def _resolve_hwnd(self, macro: Dict) -> Optional[int]:
        """Pin a concrete, valid hwnd for this macro run.

        When ``target_hwnd`` is stale (from a previous session) or absent,
        resolves via ``target_window``.  If multiple windows share the
        same title, picks the **topmost** one (most recently interacted).
        Logs a clear message so the user knows which window was selected.
        """
        target      = macro.get("target_window", "").strip()
        target_hwnd = macro.get("target_hwnd", None)

        if not target and not target_hwnd:
            return None  # no window targeting

        try:
            from engine.background_input import find_all_windows, is_window_valid

            # Saved hwnd still alive?
            if target_hwnd and is_window_valid(target_hwnd):
                return target_hwnd

            # Fall back to title search.
            if not target:
                return None
            matches = find_all_windows(target)
            if not matches:
                return None
            if len(matches) == 1:
                hwnd = matches[0][0]
                self._log(f"[ctx] resolved '{target}' → hwnd {hwnd}")
                return hwnd

            # Multiple windows — pick the topmost (first in z-order).
            hwnd, title = matches[0]
            self._log(
                f"[ctx] {len(matches)} windows match '{target}' — "
                f"using topmost (hwnd {hwnd}, "
                f"click target window first to change)"
            )
            return hwnd
        except Exception:
            return None

    def _build_ctx(self, macro: Dict) -> Dict:
        """
        Resolve execution context for a macro run.

        All modes resolve the target window once and share anchor_hwnd / offset.

        background=True  + target_window  →  PostMessage clicks (no cursor move).
                                              Image/pixel checks still use the
                                              window capture + screen-offset so
                                              coords are correct regardless of
                                              where the window sits on screen.
                                              Works with Win32 apps.
                                              Does NOT work with games/emulators.

        background=False + target_window  →  Real mouse via pyautogui with
                                              window-relative coord offset.
                                              Image search captures the window only.
                                              Works with BlueStacks, games, etc.

        background=False (no target)      →  Real mouse, screen-absolute coords,
                                              full-screen image search.
        """
        background  = macro.get("background", False)
        target      = macro.get("target_window", "").strip()
        target_hwnd = macro.get("target_hwnd", None)

        # ── Resolve the target window (shared by all modes) ────────────────────
        anchor_hwnd = None
        offset_x = offset_y = 0

        if target or target_hwnd:
            try:
                from engine.background_input import find_window, is_window_valid
                import win32gui

                hwnd = None
                # Prefer exact hwnd from the window picker
                if target_hwnd and is_window_valid(target_hwnd):
                    hwnd = target_hwnd
                # Fall back to title-based search
                if hwnd is None and target:
                    hwnd = find_window(target)

                if hwnd:
                    anchor_hwnd = hwnd
                    offset_x, offset_y = win32gui.ClientToScreen(hwnd, (0, 0))
                else:
                    self._log(f"[ctx] window '{target}' not found — using screen coords")
            except Exception as exc:
                self._log(f"[ctx] could not resolve window position: {exc}")

        # ── Build ctx ──────────────────────────────────────────────────────────
        base = {
            "anchor_hwnd": anchor_hwnd,
            "offset_x":    offset_x,
            "offset_y":    offset_y,
            "log":         self._log,
        }

        if background and anchor_hwnd:
            # PostMessage mode: hwnd set → _is_bg() True → clicks via PostMessage
            return {**base, "background": True, "hwnd": anchor_hwnd}

        if background and target:
            self._log(
                f"[background] window '{target}' not found — "
                "falling back to foreground mode"
            )

        # Foreground mode (real mouse, window-relative if anchor_hwnd set)
        return {**base, "background": False, "hwnd": None}


# ── validation ────────────────────────────────────────────────────────────────

_REQUIRED_ACTION_FIELDS: Dict[str, List[str]] = {
    "move":           ["x", "y"],
    "click":          [],
    "double_click":   [],
    "right_click":    [],
    "drag":           ["x", "y", "x2", "y2"],
    "scroll":         [],
    "key":            ["keys"],
    "type":           ["text"],
    "wait":           ["ms"],
    "stop":           [],
    "pixel_wait":     ["x", "y", "color"],
    "pixel_check":    ["x", "y", "color"],
    "find_and_click": ["template"],
    "image_wait":     ["template"],
    "image_check":    ["template"],
    "find_rects_and_click": [],
    "find_all_and_click":   ["template"],
}


def _validate(macro: Dict) -> None:
    if "name" not in macro:
        raise ValueError("Macro missing required field 'name'")
    if not isinstance(macro.get("actions", None), list):
        raise ValueError("Macro missing required field 'actions' (must be a list)")
    _validate_actions(macro["actions"])


def _validate_actions(actions: List[Dict]) -> None:
    for i, action in enumerate(actions):
        t = action.get("type")
        if t is None:
            raise ValueError(f"Action[{i}] missing 'type'")
        if t not in _REQUIRED_ACTION_FIELDS:
            raise ValueError(f"Action[{i}] unknown type '{t}'")
        for field in _REQUIRED_ACTION_FIELDS[t]:
            if field not in action:
                raise ValueError(
                    f"Action[{i}] type='{t}' missing required field '{field}'"
                )
        # recurse into branch actions
        for branch in ("on_match", "on_no_match", "on_found", "on_not_found"):
            if branch in action:
                _validate_actions(action[branch])
