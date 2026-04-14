"""
Windows.Graphics.Capture (WGC) integration — silent, GPU-aware window capture.

Uses the `windows-capture` library (Rust-backed WinRT wrapper) to read frames
directly from the DWM compositor's off-screen surface for a target window.
This is the only reliable way to capture pixels from DirectX games, Android
emulators (BlueStacks / LDPlayer), and Chromium apps when they are covered
by other windows — PrintWindow returns black for those.

Architecture
------------
* One persistent `WGCSession` per target hwnd, started lazily on first use.
* Frames arrive on a worker thread and are stored in a lock-guarded cache;
  reads are ~microseconds.
* Sessions are torn down via `stop_all()` when the macro finishes so GPU
  resources are released.
* Requires Windows 10 1903+. Drawing-border disabled (Windows 11 supports
  that flag natively; on older builds a yellow frame may appear, which is
  why we gate this on Win11 elsewhere — see `is_available()`).

Limitations
-----------
* The underlying library identifies windows by title, not hwnd. If multiple
  top-level windows share an identical title, WGC captures the first one it
  finds. We narrow by using the exact title of the given hwnd at session
  start, so ambiguity is rare in practice.
* WGC captures the entire window (including frame / non-client area). We
  crop to client area so coordinates line up with everything else in the
  engine (PrintWindow, pyautogui, PostMessage).
"""

from __future__ import annotations

import sys
import threading
from typing import Dict, Optional

import numpy as np


# Lazy import so the rest of the app still runs if windows-capture is missing.
_IMPORT_ERROR: Optional[Exception] = None
try:
    from windows_capture import WindowsCapture  # type: ignore
    _AVAILABLE = True
except Exception as exc:  # pragma: no cover
    _AVAILABLE = False
    _IMPORT_ERROR = exc


def is_available() -> bool:
    """True if WGC can be used on this machine.

    Requires the `windows-capture` library AND Windows 10 1903 or later
    (Win11 recommended — the yellow capture border is only disablable there).
    """
    if not _AVAILABLE:
        return False
    try:
        ver = sys.getwindowsversion()
        # Win10 build 18362 = 1903 (first WGC-supported build).
        return ver.major >= 10 and ver.build >= 18362
    except Exception:
        return False


# ── single session ────────────────────────────────────────────────────────────

class WGCSession:
    """One live WGC capture for a specific window (hwnd)."""

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self._frame: Optional[np.ndarray] = None     # latest client-area BGR
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._control = None
        self._failed = False

    def start(self, timeout: float = 2.0) -> bool:
        """Start the capture thread and wait for the first frame.

        Returns False if the window has no title, windows-capture is not
        available, or the first frame doesn't arrive within *timeout*.

        To ensure WGC locks onto the CORRECT window (not another one with
        the same title), we temporarily rename the target to a unique string
        during session startup and restore it immediately after.
        """
        if not _AVAILABLE:
            return False

        import win32gui
        try:
            original_title = win32gui.GetWindowText(self.hwnd)
        except Exception:
            return False
        if not original_title:
            return False

        # Use a unique temporary title so WGC locks onto the exact hwnd,
        # even when multiple windows share the same title.
        unique_title = f"__wgc_{self.hwnd}_{id(self)}__"

        try:
            win32gui.SetWindowText(self.hwnd, unique_title)
        except Exception:
            unique_title = original_title   # fallback: use original

        try:
            cap = WindowsCapture(
                cursor_capture=False,
                draw_border=False,       # honored on Win11; best-effort otherwise
                window_name=unique_title,
            )

            @cap.event
            def on_frame_arrived(frame, control):
                try:
                    # frame.frame_buffer is the whole window (BGRA).
                    # Convert to BGR and crop to client area.
                    bgra = frame.frame_buffer
                    bgr = bgra[:, :, :3]
                    client = self._crop_to_client(bgr)
                    if client is None or client.size == 0:
                        return
                    with self._lock:
                        # Copy so we don't hold on to the library's buffer
                        # (which gets overwritten next frame).
                        self._frame = client.copy()
                    self._ready.set()
                except Exception:
                    pass

            @cap.event
            def on_closed():
                self._failed = True
                self._ready.set()

            self._control = cap.start_free_threaded()
        except Exception:
            return False
        finally:
            # Restore original title as soon as WGC has locked onto the window.
            if unique_title != original_title:
                try:
                    win32gui.SetWindowText(self.hwnd, original_title)
                except Exception:
                    pass

        if not self._ready.wait(timeout=timeout):
            return False
        return not self._failed and self._frame is not None

    def latest(self) -> Optional[np.ndarray]:
        """Return the most recent client-area BGR frame (or None)."""
        with self._lock:
            return None if self._frame is None else self._frame

    def stop(self) -> None:
        if self._control is not None:
            try:
                self._control.stop()
            except Exception:
                pass
            self._control = None

    # ── helpers ───────────────────────────────────────────────────────────────

    def _crop_to_client(self, full_frame: np.ndarray) -> Optional[np.ndarray]:
        """Crop a full-window BGR frame to the client rect, then resize to
        logical pixel size so the output matches screen-grab resolution.

        WGC captures at physical (DPI-scaled) resolution, but templates and
        screen grabs are at logical resolution. Without this resize, template
        matching fails because needle and haystack are at different scales.
        """
        try:
            import cv2 as _cv2
            import win32gui

            wleft, wtop, wright, wbottom = win32gui.GetWindowRect(self.hwnd)
            ww = wright - wleft
            wh = wbottom - wtop
            if ww <= 0 or wh <= 0:
                return None

            cx0_screen, cy0_screen = win32gui.ClientToScreen(self.hwnd, (0, 0))
            cleft, ctop, cright, cbottom = win32gui.GetClientRect(self.hwnd)
            cw_logical = cright - cleft
            ch_logical = cbottom - ctop
            if cw_logical <= 0 or ch_logical <= 0:
                return None

            # Offset from window top-left to client top-left (in window coords).
            dx = cx0_screen - wleft
            dy = cy0_screen - wtop

            fh, fw = full_frame.shape[:2]
            # Scale offset + client size to physical pixels if DPI-scaled.
            if fw != ww or fh != wh:
                sx = fw / ww
                sy = fh / wh
                dx = int(round(dx * sx))
                dy = int(round(dy * sy))
                cw_phys = int(round(cw_logical * sx))
                ch_phys = int(round(ch_logical * sy))
            else:
                cw_phys = cw_logical
                ch_phys = ch_logical

            x2 = min(dx + cw_phys, fw)
            y2 = min(dy + ch_phys, fh)
            x1 = max(dx, 0)
            y1 = max(dy, 0)
            cropped = full_frame[y1:y2, x1:x2]

            # Resize from physical to logical pixel size so the output
            # matches screen-grab / template resolution.
            if cropped.shape[1] != cw_logical or cropped.shape[0] != ch_logical:
                cropped = _cv2.resize(cropped, (cw_logical, ch_logical),
                                      interpolation=_cv2.INTER_AREA)

            return cropped
        except Exception:
            return None


# ── manager / singleton ──────────────────────────────────────────────────────

class WGCManager:
    """Caches one WGCSession per hwnd; sessions are started lazily and kept
    alive until `stop_all()` is called (typically at macro end).

    Failed windows are retried periodically (not permanently blacklisted)
    in case they weren't rendering when first attempted.
    """

    def __init__(self) -> None:
        self._sessions: Dict[int, WGCSession] = {}
        self._failed: Dict[int, int] = {}  # hwnd -> fail_count (retried periodically)
        self._lock = threading.Lock()

    def get_frame(self, hwnd: int) -> Optional[np.ndarray]:
        """Return the latest BGR client-area frame for *hwnd*, or None.

        Periodically retries failed windows (every ~100 calls) in case they
        weren't rendering when first attempted.
        """
        if not is_available():
            return None

        with self._lock:
            # Check if this hwnd failed before; retry every 100 calls
            if hwnd in self._failed:
                self._failed[hwnd] += 1
                if self._failed[hwnd] < 100:
                    return None
                # Time to retry; reset counter
                del self._failed[hwnd]

            sess = self._sessions.get(hwnd)
            if sess is None:
                sess = WGCSession(hwnd)
                if not sess.start():
                    sess.stop()
                    self._failed[hwnd] = 0
                    return None
                self._sessions[hwnd] = sess

        return sess.latest()

    def stop(self, hwnd: int) -> None:
        with self._lock:
            sess = self._sessions.pop(hwnd, None)
            self._failed.pop(hwnd, None)
        if sess is not None:
            sess.stop()

    def stop_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._failed.clear()
        for s in sessions:
            s.stop()


_manager = WGCManager()


def get_frame(hwnd: int) -> Optional[np.ndarray]:
    """Get the latest captured client-area BGR frame for *hwnd*, or None."""
    return _manager.get_frame(hwnd)


def stop_session(hwnd: int) -> None:
    """Stop the WGC session for a single hwnd."""
    _manager.stop(hwnd)


def stop_all() -> None:
    """Stop every active WGC session (call on macro end / app close)."""
    _manager.stop_all()
