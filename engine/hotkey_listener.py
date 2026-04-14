"""
Global hotkey listener using the keyboard library.

Each macro may declare a trigger:
  "trigger": { "type": "hotkey", "keys": ["ctrl", "F1"] }

The listener registers hotkeys globally so they work even when the
app window is not focused (typical game-tool behavior).
"""

import threading
from typing import Callable, Dict, List, Optional

try:
    import keyboard
    _KEYBOARD_AVAILABLE = True
except Exception:
    _KEYBOARD_AVAILABLE = False


class HotkeyListener:
    def __init__(self, log_fn: Optional[Callable[[str], None]] = None):
        self._log = log_fn or print
        self._registered: Dict[str, str] = {}   # name → hotkey string
        self._lock = threading.Lock()

    def register(self, name: str, keys: List[str], callback: Callable) -> bool:
        """Register a hotkey for a macro. Returns False if keyboard unavailable."""
        if not _KEYBOARD_AVAILABLE:
            self._log("[hotkey] 'keyboard' library not available; hotkeys disabled")
            return False

        hotkey_str = "+".join(keys)
        self.unregister(name)

        try:
            keyboard.add_hotkey(hotkey_str, callback, suppress=False)
            with self._lock:
                self._registered[name] = hotkey_str
            self._log(f"[hotkey] registered '{hotkey_str}' → {name}")
            return True
        except Exception as exc:
            self._log(f"[hotkey] failed to register '{hotkey_str}': {exc}")
            return False

    def unregister(self, name: str) -> None:
        if not _KEYBOARD_AVAILABLE:
            return
        with self._lock:
            hotkey_str = self._registered.pop(name, None)
        if hotkey_str:
            try:
                keyboard.remove_hotkey(hotkey_str)
                self._log(f"[hotkey] unregistered '{hotkey_str}'")
            except Exception:
                pass

    def unregister_all(self) -> None:
        if not _KEYBOARD_AVAILABLE:
            return
        with self._lock:
            names = list(self._registered.keys())
        for name in names:
            self.unregister(name)
