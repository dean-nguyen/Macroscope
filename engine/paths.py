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
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

APP_NAME = "Macroscope"

# The folder was called this before the project was renamed. Kept so a packaged
# install that already has macros and templates in it can be migrated rather than
# silently orphaned.
_LEGACY_APP_NAMES = ("WindowMacroBotData",)


def is_packaged() -> bool:
    """True when running from a built binary rather than from source.

    ``sys.frozen`` is **PyInstaller's** marker, and this project builds with Nuitka.
    Measured on a compiled one-liner: ``sys.frozen`` is *absent* and ``__compiled__``
    is ``True``. So every packaged install took the from-source branch below and wrote
    its macros next to the exe — which is read-only in Program Files, and which
    ``data_root``'s own docstring says it exists to avoid.

    Both markers are checked, so changing packager cannot silently move everyone's
    data again.
    """
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def app_root() -> Path:
    """Return the application install directory (read-only resources).

    Nuitka reports ``sys.executable`` as ``<dist>/python.exe`` rather than the
    renamed binary, which is fine — only the directory is wanted here.
    """
    if is_packaged():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """Return the user data directory.

    When packaged (.exe): %APPDATA%/Macroscope — safe regardless of
    install location (Program Files, Desktop, etc.).

    When running from source: the project root — keeps macros/ and templates/
    next to the code for easy development.
    """
    if is_packaged():
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

    Only runs in a packaged build; from source, data_root() is the project directory
    and none of this applies. Copies rather than moves, so the old location stays
    intact for the user to check before deleting.

    Two sources: the original exe-relative layout, and the APPDATA folder under the
    project's previous name. A rename must not orphan someone's captured templates —
    re-capturing them is exactly the tedious work this tool exists to avoid.

    This is also the migration that picks up data left beside the exe by a build that
    never recognised itself as packaged — which, until `is_packaged`, was all of them.
    """
    if not is_packaged():
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


def seed_starter_macros(pack: str = "onmyoji", log_fn=None) -> List[Tuple[str, str]]:
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
    forward = log_fn or (lambda msg: log.info("%s", msg))
    notes: List[Tuple[str, str]] = []

    def say(msg: str, tag: str = "info") -> None:
        notes.append((msg, tag))
        forward(msg)

    marker = data_root() / ".starter_seeded"
    seeded = _read_seeded(marker)
    seeded_images = _read_seeded(marker, key="templates")

    pack_dir = PACKS_DIR / pack
    folder_name = pack.capitalize()
    dest_dir = MACROS_DIR / folder_name
    added, updated, diverged = _sync_macros(pack_dir, dest_dir, seeded)
    img_added, img_updated, img_diverged = _sync_templates(
        pack_dir / "templates", TEMPLATES_DIR, seeded_images)

    try:
        marker.write_text(
            json.dumps({"seeded": seeded, "templates": seeded_images},
                       indent=2, sort_keys=True),
            encoding="utf-8")
    except OSError:
        pass

    if added:
        say(f"Added {len(added)} macro(s) from the {folder_name} pack: "
            f"{', '.join(added)}", "ok")
    if updated:
        say(f"Updated {len(updated)} macro(s) to the current {folder_name} pack: "
            f"{', '.join(updated)}", "ok")
    for name in diverged:
        say(f"'{name}' differs from the {folder_name} pack, so it was left as it is. "
            f"Delete it to take the pack's version.", "warn")
    if img_added:
        say(f"Added {len(img_added)} image(s) from the {folder_name} pack", "ok")
    if img_updated:
        say(f"Updated {len(img_updated)} image(s) to the current {folder_name} pack",
            "ok")
    for name in img_diverged:
        say(f"Image '{name}' differs from the {folder_name} pack, so your version was "
            f"kept. Score it with the match report if it stopped working.", "warn")

    return notes


# Kept local rather than imported from template_store, which imports *this* module.
_SEEDABLE_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")


def _sync_templates(src_dir: Path, dest_dir: Path, seeded: dict):
    """Add, update or leave each image a pack publishes. Mutates *seeded*.

    The exe bundles `packs/` wholesale (`--include-data-dir`), so once a pack carries
    its images the install already *has* them — and before this, seeding copied only
    the macro files, so a fresh install listed every template as missing while the
    files sat inside it. That is the "installed it and nothing happens" complaint, and
    the data was there all along.

    Same three outcomes as `_sync_macros`, and the same reason: a user who re-captured
    a template because the shipped one did not match their client must not have it
    overwritten on the next launch, and one who *deleted* it must not have it come
    back. Both are recognised by comparing hashes rather than guessing.
    """
    added, updated, diverged = [], [], []
    if not src_dir.is_dir():
        return added, updated, diverged
    dest_dir.mkdir(parents=True, exist_ok=True)

    for path in sorted(src_dir.iterdir()):
        if path.suffix.lower() not in _SEEDABLE_IMAGE_EXTS:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            log.warning("Could not read pack image %s", path)
            continue

        name = path.name
        digest = _digest_bytes(data)
        target = dest_dir / name
        known = seeded.get(name)

        if not target.exists():
            # Never offered, or the user deleted it. Only the first is ours to fix —
            # deleting a template that does not match your client is a real decision.
            if known is not None:
                continue
            target.write_bytes(data)
            seeded[name] = digest
            added.append(name)
            continue

        try:
            current = _digest_bytes(target.read_bytes())
        except OSError:
            continue
        if current == digest:
            seeded[name] = digest
        elif known is not None and current == known:
            target.write_bytes(data)
            seeded[name] = digest
            updated.append(name)
        else:
            diverged.append(name)
    return added, updated, diverged


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


def _digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_seeded(marker: Path, key: str = "seeded") -> dict:
    """What was written for each name, as ``{name: digest}``.

    Two older formats read as "nothing recorded": a bare ``1``, and a list of names
    with no hashes. Both mean the same thing — we cannot tell an untouched file from
    an edited one, so such a file is left alone and reported rather than overwritten.
    A marker written before images were seeded has no ``templates`` key, which reads
    the same way: the images already on disk are treated as the user's.
    """
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if isinstance(data, dict) and isinstance(data.get(key), dict):
        return {str(k): str(v) for k, v in data[key].items()}
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
