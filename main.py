"""Entry point for Macroscope."""

# Enable DPI awareness FIRST — before any other imports.
# This must happen before tkinter, win32gui, PIL, or any module
# that touches the display, otherwise Windows returns scaled coordinates.
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # Per-Monitor DPI Aware v2
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()     # fallback for older Windows
    except Exception:
        pass

import sys
from engine.paths import ensure_dirs, migrate_legacy_data, seed_starter_macros
from gui.app import App


def main():
    ensure_dirs()
    migrate_legacy_data()
    # Adds pack macros the user has never been offered, and updates ones they have
    # not edited. A macro they changed is left alone and reported.
    seed_starter_macros()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
