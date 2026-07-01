"""
Template image library — the data layer behind the Template Manager.

Templates are the screenshot images used by the image-matching actions
(``find_and_click``, ``image_wait``, ``image_check``, ``find_all_and_click``).
They live as plain files in ``TEMPLATES_DIR`` and macros reference them by a
relative path like ``templates/region_123.png``.

There is deliberately **no database**: the library is derived on demand from the
filesystem plus the loaded macros, so it can never drift out of sync with the
actual files. This module holds the pure/testable logic (listing, usage
scanning, reference rewriting); the GUI supplies macro loading/saving.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from engine.paths import TEMPLATES_DIR

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"})

# Action-dict keys that can hold nested action lists (branches).
_BRANCH_KEYS = ("on_match", "on_no_match", "on_found", "on_not_found")


@dataclass(frozen=True)
class TemplateInfo:
    """A single template file plus the metadata the UI needs."""

    name: str            # filename, e.g. "region_123.png"
    ref: str             # macro reference, e.g. "templates/region_123.png"
    path: Path
    width: int
    height: int
    size_bytes: int
    mtime: float


# ── references ────────────────────────────────────────────────────────────────


def ref_for(name: str) -> str:
    """The macro-reference string for a template file name."""
    return f"templates/{name}"


def basename_of(ref: str) -> str:
    """Filename of a template reference, tolerant of / or \\ separators."""
    return Path(str(ref).replace("\\", "/")).name


def iter_refs(actions: List[Dict]) -> Iterator[str]:
    """Yield every ``template`` reference in an action list, recursing branches."""
    for action in actions or []:
        ref = action.get("template")
        if isinstance(ref, str) and ref:
            yield ref
        for branch in _BRANCH_KEYS:
            nested = action.get(branch)
            if isinstance(nested, list):
                yield from iter_refs(nested)


# ── listing ───────────────────────────────────────────────────────────────────


def _read_dims(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size
    except Exception:
        return (0, 0)


def list_templates(templates_dir: Path = TEMPLATES_DIR) -> List[TemplateInfo]:
    """List every image file in *templates_dir* (top level), sorted by name."""
    if not templates_dir.exists():
        return []
    out: List[TemplateInfo] = []
    for path in sorted(templates_dir.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        width, height = _read_dims(path)
        out.append(
            TemplateInfo(
                name=path.name,
                ref=ref_for(path.name),
                path=path,
                width=width,
                height=height,
                size_bytes=stat.st_size,
                mtime=stat.st_mtime,
            )
        )
    return out


# ── usage analysis ────────────────────────────────────────────────────────────


def usage_by_name(macros: List[Dict]) -> Dict[str, List[str]]:
    """Map each referenced template file name → sorted list of macro names."""
    out: Dict[str, List[str]] = {}
    for macro in macros:
        used = {basename_of(r) for r in iter_refs(macro.get("actions", []))}
        for name in used:
            out.setdefault(name, [])
            if macro.get("name") not in out[name]:
                out[name].append(macro["name"])
    for name in out:
        out[name].sort(key=str.lower)
    return out


def find_orphans(
    templates: List[TemplateInfo], usage: Dict[str, List[str]]
) -> List[TemplateInfo]:
    """Template files that no macro references."""
    return [t for t in templates if not usage.get(t.name)]


def find_missing(
    macros: List[Dict], templates: List[TemplateInfo]
) -> List[str]:
    """Referenced template names that have no corresponding file on disk."""
    existing = {t.name for t in templates}
    referenced = {
        basename_of(r)
        for macro in macros
        for r in iter_refs(macro.get("actions", []))
    }
    return sorted(referenced - existing, key=str.lower)


# ── reference rewriting (immutable) ───────────────────────────────────────────


def update_references(macro: Dict, old_name: str, new_name: str) -> Optional[Dict]:
    """Return a NEW macro dict with references to *old_name* pointed at
    *new_name*, or ``None`` if the macro didn't reference it.

    The input macro is never mutated (deep-copies only the branches it touches).
    """
    new_ref = ref_for(new_name)
    changed = False

    def walk(actions: List[Dict]) -> List[Dict]:
        nonlocal changed
        rewritten = []
        for action in actions:
            copy = dict(action)
            ref = copy.get("template")
            if isinstance(ref, str) and basename_of(ref) == old_name:
                copy["template"] = new_ref
                changed = True
            for branch in _BRANCH_KEYS:
                if isinstance(copy.get(branch), list):
                    copy[branch] = walk(copy[branch])
            rewritten.append(copy)
        return rewritten

    new_macro = dict(macro)
    new_macro["actions"] = walk(macro.get("actions", []))
    return new_macro if changed else None


# ── filesystem operations ─────────────────────────────────────────────────────


def sanitize_stem(stem: str) -> str:
    """Reduce a user-entered name to a safe file stem (no path, no separators)."""
    stem = basename_of(stem)
    stem = re.sub(r"\.[^.]*$", "", stem)          # drop any extension
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)  # safe chars only
    stem = stem.strip("._-")
    return stem or "template"


def build_new_filename(old_name: str, new_stem: str) -> str:
    """Combine a sanitized new stem with the original file's extension."""
    ext = Path(old_name).suffix or ".png"
    return f"{sanitize_stem(new_stem)}{ext}"


def rename_file(
    old_name: str, new_name: str, templates_dir: Path = TEMPLATES_DIR
) -> Path:
    """Rename a template file. Raises ValueError if the target already exists."""
    src = templates_dir / old_name
    dst = templates_dir / new_name
    if not src.exists():
        raise ValueError(f"Template not found: {old_name}")
    if dst.exists() and dst.resolve() != src.resolve():
        raise ValueError(f"A template named '{new_name}' already exists")
    src.rename(dst)
    return dst


def delete_file(name: str, templates_dir: Path = TEMPLATES_DIR) -> None:
    """Delete a template file (no error if it's already gone)."""
    (templates_dir / name).unlink(missing_ok=True)


def unique_name(name: str, templates_dir: Path = TEMPLATES_DIR) -> str:
    """Return *name*, or name_2/name_3/... if a file already exists, so a new
    capture never silently overwrites an existing template."""
    if not (templates_dir / name).exists():
        return name
    stem, ext = Path(name).stem, Path(name).suffix
    i = 2
    while (templates_dir / f"{stem}_{i}{ext}").exists():
        i += 1
    return f"{stem}_{i}{ext}"
