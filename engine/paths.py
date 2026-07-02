"""
Centralized path resolution for user data and application resources.

User data (macros, templates) lives under %APPDATA%/WindowMacroBotData so the
app works correctly regardless of install location (Program Files, Desktop, etc.).

The application root (where the .exe or main.py lives) is still used for
bundled read-only resources.
"""

from __future__ import annotations

import json
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

# License activation cache (HMAC-signed). Lives alongside user data so it
# survives app updates but is per-machine.
LICENSE_FILE: Path = data_root() / "license.json"

# Bundled, read-only preset packs shipped alongside the app (spec files +
# starter macros). Included in the packaged build via Nuitka --include-data-dir.
PACKS_DIR: Path = app_root() / "packs"


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


def seed_starter_macros(pack: str = "onmyoji") -> None:
    """First-run only (packaged builds): copy the bundled starter macros for
    *pack* into the user's library so a fresh install already has the game's
    macros (templates are still captured via Guided Capture).

    Guarded by a marker file so it never re-seeds — a user who deletes the
    starter macros won't have them reappear.
    """
    if not getattr(sys, "frozen", False):
        return
    marker = data_root() / ".starter_seeded"
    if marker.exists():
        return

    folder_name = pack.capitalize()
    copied = _seed_macros(PACKS_DIR / pack, MACROS_DIR / folder_name)
    try:
        marker.write_text("1", encoding="utf-8")
    except OSError:
        pass
    if copied:
        log.info("Seeded %d starter macro(s) into %s", copied, folder_name)


def _seed_macros(src_dir: Path, dest_dir: Path) -> int:
    """Copy each ``*.macro.json`` in *src_dir* into *dest_dir* as
    ``<macro name>.json`` (matching how the app saves macros). Existing files
    are left untouched. Returns the number copied."""
    if not src_dir.is_dir():
        return 0
    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in sorted(src_dir.glob("*.macro.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("Could not read starter macro %s", path)
            continue
        name = data.get("name")
        if not name:
            continue
        target = dest_dir / f"{name}.json"
        if target.exists():
            continue
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        count += 1
    return count


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
