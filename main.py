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
    # Adds pack macros and images the user has never been offered, and updates the ones
    # they have not edited. Anything they changed is left alone and reported — and the
    # report has to be carried into the window, because this runs before it exists and
    # a packaged build has no console for stdlib logging to reach.
    notes = seed_starter_macros()
    App(startup_notes=notes).mainloop()


if __name__ == "__main__":
    main()
