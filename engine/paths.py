"""
Centralized path resolution for user data and application resources.

User data (macros, templates) lives under %APPDATA%/WindowMacroBotData so the
app works correctly regardless of install location (Program Files, Desktop, etc.).

The application root (where the .exe or main.py lives) is still used for
bundled read-only resources.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "WindowMacroBotData"


def app_root() -> Path:
    """Return the application install directory (read-only resources)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """Return the user data directory.

    When packaged (.exe): %APPDATA%/WindowMacroBotData — safe regardless of
    install location (Program Files, Desktop, etc.).

    When running from source: the project root — keeps macros/ and templates/
    next to the code for easy development.
    """
    if getattr(sys, "frozen", False):
        import os
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME
    return app_root()


# Concrete directories — importable constants
MACROS_DIR: Path = data_root() / "macros"
TEMPLATES_DIR: Path = data_root() / "templates"


def ensure_dirs() -> None:
    """Create user data directories if they don't exist yet."""
    MACROS_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


def migrate_legacy_data() -> None:
    """One-time migration: copy exe-relative macros/ and templates/ to APPDATA.

    Only runs when the app is frozen (packaged as .exe) and the old
    exe-relative directories contain data that hasn't been migrated yet.
    Copies files instead of moving — the old directory is left intact so
    the user can verify before deleting it manually.
    """
    if not getattr(sys, "frozen", False):
        return

    old_root = app_root()
    _migrate_dir(old_root / "macros", MACROS_DIR)
    _migrate_dir(old_root / "templates", TEMPLATES_DIR)


def _migrate_dir(src: Path, dst: Path) -> None:
    """Copy files from *src* into *dst*, skipping files that already exist."""
    if not src.is_dir():
        return
    if src.resolve() == dst.resolve():
        return

    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in src.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(src)
        target = dst / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        count += 1

    if count:
        log.info("Migrated %d file(s) from %s to %s", count, src, dst)
