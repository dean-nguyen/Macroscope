"""
Macro packs — export/import a bundle of macros plus their template images.

A pack is a single ``.wmbpack`` file (a zip) so it can be shared, sold, or
imported with one click:

    manifest.json          pack metadata (name, game, version, macro/template lists)
    macros/<name>.json     the macro definitions
    templates/<file>       only the template images the macros reference

This is what makes "one flexible engine + per-game preset packs" work. There is
no database — a pack is self-contained and importing it just drops files into
the normal macros/ and templates/ folders.

The heavy logic (which templates a pack needs, collision-safe renames on import,
rewriting references) is reused from :mod:`engine.template_store`.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from engine.paths import TEMPLATES_DIR
from engine.template_store import (
    basename_of,
    iter_refs,
    unique_name,
    update_references,
)

PACK_EXT = ".wmbpack"
MANIFEST_NAME = "manifest.json"
PACK_FORMAT = 1


def _safe_folder(name: str) -> str:
    """Reduce a name to a single safe folder segment."""
    name = str(name).replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9 _-]+", "", name).strip()
    return name or "Imported"


def referenced_templates(macros: List[Dict]) -> List[str]:
    """Sorted unique template file names used by *macros*."""
    refs = set()
    for macro in macros:
        for ref in iter_refs(macro.get("actions", [])):
            refs.add(basename_of(ref))
    return sorted(refs)


def build_manifest(
    macros: List[Dict],
    *,
    name: str,
    game: str = "",
    version: str = "1.0",
    description: str = "",
) -> Dict:
    """Assemble the manifest dict for a pack."""
    return {
        "format": PACK_FORMAT,
        "name": name,
        "game": game,
        "version": version,
        "description": description,
        "macros": [m["name"] for m in macros],
        "templates": referenced_templates(macros),
    }


def export_pack(
    macros: List[Dict],
    dest_path: Path,
    *,
    name: str,
    game: str = "",
    version: str = "1.0",
    description: str = "",
    templates_dir: Path = TEMPLATES_DIR,
) -> Path:
    """Write *macros* and their templates to a ``.wmbpack`` zip at *dest_path*."""
    dest_path = Path(dest_path)
    manifest = build_manifest(
        macros, name=name, game=game, version=version, description=description
    )
    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        for macro in macros:
            clean = {k: v for k, v in macro.items() if not k.startswith("_")}
            zf.writestr(f"macros/{macro['name']}.json", json.dumps(clean, indent=2))
        for ref in manifest["templates"]:
            src = templates_dir / ref
            if src.exists():
                zf.write(src, f"templates/{ref}")
    return dest_path


@dataclass
class ImportResult:
    """Outcome of extracting a pack, ready for the caller to save the macros."""

    manifest: Dict
    macros: List[Dict]                      # ready-to-save (folder set, refs fixed)
    folder: str
    template_renames: Dict[str, str] = field(default_factory=dict)


def read_manifest(pack_path: Path) -> Dict:
    """Read just the manifest from a pack (for a preview before importing)."""
    with zipfile.ZipFile(pack_path) as zf:
        return json.loads(zf.read(MANIFEST_NAME))


def extract_pack(
    pack_path: Path,
    templates_dir: Path = TEMPLATES_DIR,
    existing_macro_names: Optional[frozenset] = None,
    into_folder: Optional[str] = None,
) -> ImportResult:
    """Extract templates to disk (collision-safe) and return ready-to-save macros.

    Template files that would collide with existing ones are renamed, and the
    macro references are rewritten to match. Macro names that collide are
    suffixed so nothing is silently overwritten. The caller saves the returned
    macros via its engine.
    """
    existing = set(existing_macro_names or frozenset())
    templates_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(pack_path) as zf:
        manifest = json.loads(zf.read(MANIFEST_NAME))
        folder = (
            into_folder if into_folder is not None
            else _safe_folder(manifest.get("game") or manifest.get("name") or "Imported")
        )

        renames = _extract_templates(zf, templates_dir)
        macros = _load_macros(zf, renames, folder, existing)

    return ImportResult(manifest=manifest, macros=macros, folder=folder,
                        template_renames=renames)


def _extract_templates(zf: zipfile.ZipFile, templates_dir: Path) -> Dict[str, str]:
    """Copy templates/* out of the zip, renaming on collision. Returns old→new."""
    renames: Dict[str, str] = {}
    for entry in zf.namelist():
        if not entry.startswith("templates/") or entry.endswith("/"):
            continue
        original = Path(entry).name
        target = unique_name(original, templates_dir)
        if target != original:
            renames[original] = target
        with zf.open(entry) as src, open(templates_dir / target, "wb") as out:
            shutil.copyfileobj(src, out)
    return renames


def _load_macros(
    zf: zipfile.ZipFile,
    renames: Dict[str, str],
    folder: str,
    existing: set,
) -> List[Dict]:
    """Parse macros/*.json, rewrite renamed refs, de-dup names, set folder."""
    macros: List[Dict] = []
    for entry in zf.namelist():
        if not entry.startswith("macros/") or not entry.endswith(".json"):
            continue
        macro = json.loads(zf.read(entry))
        for old, new in renames.items():
            updated = update_references(macro, old, new)
            if updated is not None:
                macro = updated
        macro["name"] = _dedupe_name(macro.get("name", "macro"), existing)
        existing.add(macro["name"])
        macro["_folder"] = folder
        macros.append(macro)
    return macros


def _dedupe_name(base: str, existing: set) -> str:
    if base not in existing:
        return base
    i = 2
    while f"{base} ({i})" in existing:
        i += 1
    return f"{base} ({i})"


# ── template specs (for guided capture) ───────────────────────────────────────


def load_template_spec(path: Path) -> List[Dict]:
    """Load a ``*.spec.json`` describing the templates a pack needs.

    Returns a list of ``{"name": ..., "description": ...}`` dicts (entries
    without a name are dropped). The Guided Capture wizard walks this list.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: List[Dict] = []
    for item in data.get("templates", []):
        if isinstance(item, dict) and item.get("name"):
            out.append({
                "name": str(item["name"]),
                "description": str(item.get("description", "")),
            })
    return out


def spec_missing(spec: List[Dict], templates_dir: Path = TEMPLATES_DIR) -> List[str]:
    """Names in *spec* that have not been captured yet."""
    return [it["name"] for it in spec if not (templates_dir / it["name"]).exists()]
