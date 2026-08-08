"""
Centralized path resolution for user data and application resources.

User data (macros, templates) lives under %APPDATA%/Macroscope so the
app works correctly regardless of install location (Program Files, Desktop, etc.).

The application root (where the .exe or main.py lives) is still used for
bundled read-only resources.
"""

from __future__ import annotations

import hashlib
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


def seed_starter_macros(pack: str = "onmyoji", log_fn=None) -> None:
    """Keep the user's library in step with the bundled pack, without ever losing
    work they did themselves.

    Three things this has got wrong in turn, each of which made shipped work
    invisible:

    It ran only in a packaged build (``sys.frozen``), so anyone running from source —
    which is how this project is installed — saw an empty macro list and no sign that
    a pack existed at all.

    Its marker was a single flag, so it seeded once and never again: a macro added to
    the pack afterwards never reached anyone who had already launched the app.

    And it never *updated* anything. A macro seeded once stayed at that version
    forever, so a fix to a shipped macro reached new installs only — measured on this
    machine, where the installed Realm Raid macros were several fixes behind the pack
    while the user was running them.

    So the marker records a hash of exactly what was written. A file still matching
    its hash is one the user has not touched, and gets the update. A file that differs
    is theirs, and is left alone with a line in the log saying the pack has moved on —
    guessing which side to keep is not seeding's business.
    """
    say = log_fn or (lambda msg: log.info("%s", msg))
    marker = data_root() / ".starter_seeded"
    seeded = _read_seeded(marker)

    folder_name = pack.capitalize()
    dest_dir = MACROS_DIR / folder_name
    added, updated, diverged = _sync_macros(PACKS_DIR / pack, dest_dir, seeded)

    try:
        marker.write_text(json.dumps({"seeded": seeded}, indent=2, sort_keys=True),
                          encoding="utf-8")
    except OSError:
        pass

    if added:
        say(f"Added {len(added)} macro(s) from the {folder_name} pack: "
            f"{', '.join(added)}")
    if updated:
        say(f"Updated {len(updated)} macro(s) to the current {folder_name} pack: "
            f"{', '.join(updated)}")
    for name in diverged:
        say(f"'{name}' differs from the {folder_name} pack, so it was left as it is. "
            f"Delete it to take the pack's version.")


def _sync_macros(src_dir: Path, dest_dir: Path, seeded: dict):
    """Add, update or leave each pack macro. Mutates *seeded* with what was written."""
    added, updated, diverged = [], [], []
    if not src_dir.is_dir():
        return added, updated, diverged
    dest_dir.mkdir(parents=True, exist_ok=True)

    for path in sorted(src_dir.glob("*.macro.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("Could not read starter macro %s", path)
            continue
        name = data.get("name")
        if not name:
            continue

        text = json.dumps(data, indent=2)
        digest = _digest(text)
        target = dest_dir / f"{name}.json"
        known = seeded.get(name)

        if not target.exists():
            # Never offered, or the user deleted it. Only the first is ours to fix.
            if known is not None:
                continue
            target.write_text(text, encoding="utf-8")
            seeded[name] = digest
            added.append(name)
            continue

        try:
            current = _digest(target.read_text(encoding="utf-8"))
        except OSError:
            continue
        if current == digest:
            seeded[name] = digest        # already current; just record it
        elif known is not None and current == known:
            target.write_text(text, encoding="utf-8")   # untouched since we wrote it
            seeded[name] = digest
            updated.append(name)
        else:
            diverged.append(name)
    return added, updated, diverged


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_seeded(marker: Path) -> dict:
    """What was written for each macro name, as ``{name: digest}``.

    Two older formats read as "nothing recorded": a bare ``1``, and a list of names
    with no hashes. Both mean the same thing — we cannot tell an untouched file from
    an edited one, so such a file is left alone and reported rather than overwritten.
    """
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if isinstance(data, dict) and isinstance(data.get("seeded"), dict):
        return {str(k): str(v) for k, v in data["seeded"].items()}
    return {}


def _seed_macros(src_dir: Path, dest_dir: Path, skip: Optional[set] = None) -> int:
    """Copy each ``*.macro.json`` in *src_dir* into *dest_dir* as ``<name>.json``,
    never overwriting. Kept for `tests/test_seed_macros.py`, which counts what a pack
    ships; `_sync_macros` is what the app runs."""
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
