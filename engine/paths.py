"""
Centralized path resolution for user data and application resources.

User data (macros, templates) lives under %APPDATA%/Macroscope so the
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
from typing import Optional

log = logging.getLogger(__name__)

APP_NAME = "Macroscope"

# The folder was called this before the project was renamed. Kept so a packaged
# install that already has macros and templates in it can be migrated rather than
# silently orphaned.
_LEGACY_APP_NAMES = ("WindowMacroBotData",)


def app_root() -> Path:
    """Return the application install directory (read-only resources)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """Return the user data directory.

    When packaged (.exe): %APPDATA%/Macroscope — safe regardless of
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


# Bundled, read-only preset packs shipped alongside the app (spec files +
# starter macros). Included in the packaged build via Nuitka --include-data-dir.
PACKS_DIR: Path = app_root() / "packs"


def ensure_dirs() -> None:
    """Create user data directories if they don't exist yet."""
    MACROS_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


def migrate_legacy_data() -> None:
    """One-time migration of user data into the current APPDATA location.

    Only runs when the app is frozen (packaged as .exe); from source, data_root()
    is the project directory and none of this applies. Copies rather than moves, so
    the old location stays intact for the user to check before deleting.

    Two sources: the original exe-relative layout, and the APPDATA folder under the
    project's previous name. A rename must not orphan someone's captured templates —
    re-capturing them is exactly the tedious work this tool exists to avoid.
    """
    if not getattr(sys, "frozen", False):
        return

    old_root = app_root()
    _migrate_dir(old_root / "macros", MACROS_DIR)
    _migrate_dir(old_root / "templates", TEMPLATES_DIR)

    import os
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return
    for legacy in _LEGACY_APP_NAMES:
        legacy_root = Path(appdata) / legacy
        if legacy_root == data_root() or not legacy_root.exists():
            continue
        _migrate_dir(legacy_root / "macros", MACROS_DIR)
        _migrate_dir(legacy_root / "templates", TEMPLATES_DIR)


def seed_starter_macros(pack: str = "onmyoji") -> None:
    """Copy any bundled macro for *pack* the user has not been offered before into
    their library, so a fresh install has something to run and an existing one picks
    up macros added since (templates are still captured via Guided Capture).

    Two things this used to get wrong.

    It ran only in a packaged build (``sys.frozen``), so anyone running from source —
    which is how this project is installed — saw an empty macro list and no sign that
    a pack existed at all.

    And its marker was a single flag, so it seeded once and never again: a macro added
    to the pack afterwards never reached anyone who had already launched the app. The
    marker now records *which* macro names have been offered, so a new one arrives on
    the next launch while one the user deleted stays deleted.
    """
    marker = data_root() / ".starter_seeded"
    offered = _read_offered(marker)

    folder_name = pack.capitalize()
    copied = _seed_macros(PACKS_DIR / pack, MACROS_DIR / folder_name, skip=offered)
    names = _pack_macro_names(PACKS_DIR / pack)
    try:
        marker.write_text(json.dumps({"offered": sorted(offered | names)}, indent=2),
                          encoding="utf-8")
    except OSError:
        pass
    if copied:
        log.info("Seeded %d starter macro(s) into %s", copied, folder_name)


def _read_offered(marker: Path) -> set:
    """Macro names already offered to this user.

    A marker from the old format holds ``1`` and says nothing about *what* was seeded.
    Reading that as "nothing recorded" means such a user is offered the current pack
    once — which only ever adds macros they do not have, since an existing file is
    never overwritten. That is the point: it is how an install from before a macro
    existed finally receives it.
    """
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if isinstance(data, dict) and isinstance(data.get("offered"), list):
        return {str(n) for n in data["offered"]}
    return set()


def _pack_macro_names(src_dir: Path) -> set:
    names = set()
    if not src_dir.is_dir():
        return names
    for path in sorted(src_dir.glob("*.macro.json")):
        try:
            name = json.loads(path.read_text(encoding="utf-8")).get("name")
        except (OSError, ValueError):
            continue
        if name:
            names.add(str(name))
    return names


def _seed_macros(src_dir: Path, dest_dir: Path, skip: Optional[set] = None) -> int:
    """Copy each ``*.macro.json`` in *src_dir* into *dest_dir* as
    ``<macro name>.json`` (matching how the app saves macros). Names in *skip* have
    been offered before and are left alone even if the user deleted them; existing
    files are never overwritten. Returns the number copied."""
    if not src_dir.is_dir():
        return 0
    skip = skip or set()
    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in sorted(src_dir.glob("*.macro.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("Could not read starter macro %s", path)
            continue
        name = data.get("name")
        if not name or name in skip:
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
