"""Assemble a downloadable ``.wmbpack`` from a pack's source in this repo.

Why not just use the app's own **Export as pack…**: that exports the macros as they
sit in *your* library, and those carry your window pins and whatever you changed while
testing. Measured on this machine — the two Realm Raid macros in use had
``target_hwnd: 1641012`` and ``target_position: 0`` baked in. Exporting is not the
right source for something other people download.

So the source here is `packs/<name>/*.macro.json` — the versioned pack, the same files
`seed_starter_macros` installs — plus `packs/<name>/templates/`, the images that pack
publishes. Those are versioned too, and have to be: `./templates/` is the user's own
captures and is git-ignored, so a CI checkout has none. `release.yml` runs this to
attach the pack to the release, and it cannot build what is not in the repo.

**Templates are the part that may not travel.** Measured on two clients of one game on
one machine, differing only in graphics settings: a marker scored `1.000` on one and
`0.697` on the other, below what the macro needs. So the pack ships what it has and
`docs/PACKS.md` says how to check, rather than promising the images will work.

    python tools/build_pack.py onmyoji
    python tools/build_pack.py onmyoji --templates templates   # a fresh capture session
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import pack_store as ps   # noqa: E402
from engine.template_store import basename_of, iter_refs   # noqa: E402


def load_pack_macros(pack_dir: Path) -> list[dict]:
    """The pack's own macro files, in a stable order."""
    macros = []
    for path in sorted(pack_dir.glob("*.macro.json")):
        macros.append(json.loads(path.read_text(encoding="utf-8")))
    return macros


def split_templates(macros: list[dict], templates_dir: Path):
    """Which referenced templates exist, and which are missing.

    A missing one is not an error. Most of this pack's templates are states you cannot
    summon on demand — a CAPTCHA, a disconnect — and the engine already degrades to a
    normal no-match and lists them at the start of a run. A pack that refused to build
    without them could never be built at all.
    """
    wanted = ps.referenced_templates(macros)
    have = [t for t in wanted if (templates_dir / t).exists()]
    missing = [t for t in wanted if t not in have]
    return have, missing


def _templates_dir(pack_dir: Path) -> Path:
    """Where a published pack's images come from.

    `packs/<name>/templates/` is versioned, so the release workflow has something to
    build from — `./templates/` is the user's own captures and is git-ignored, which
    means a CI checkout has no images at all. Falling back to it keeps a local build
    working straight from a capture session.
    """
    own = pack_dir / "templates"
    return own if own.is_dir() else ROOT / "templates"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pack", help="pack directory name under packs/, e.g. onmyoji")
    ap.add_argument("--out", type=Path, default=None,
                    help="exact output path (default <out-dir>/<Name>.wmbpack)")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="directory to write <Name>.wmbpack into (default .probe). "
                         "Lets a caller collect packs without knowing how each is "
                         "named — which is what release.yml needs.")
    ap.add_argument("--templates", type=Path, default=None,
                    help="where the images are (default packs/<pack>/templates, "
                         "falling back to ./templates)")
    ap.add_argument("--version", default="1.0", help="pack version string")
    args = ap.parse_args(argv)

    pack_dir = ROOT / "packs" / args.pack
    if not pack_dir.is_dir():
        print(f"no such pack: {pack_dir}", file=sys.stderr)
        return 2

    macros = load_pack_macros(pack_dir)
    if not macros:
        print(f"{pack_dir} has no *.macro.json", file=sys.stderr)
        return 2

    templates_dir = args.templates or _templates_dir(pack_dir)
    have, missing = split_templates(macros, templates_dir)

    name = args.pack.capitalize()
    out = args.out or (args.out_dir or ROOT / ".probe") / f"{name}.wmbpack"
    out.parent.mkdir(parents=True, exist_ok=True)

    spec_path = pack_dir / "templates.spec.json"
    description = ""
    if spec_path.exists():
        description = json.loads(spec_path.read_text(encoding="utf-8")).get(
            "description", "")

    ps.export_pack(macros, out, name=name, game=name, version=args.version,
                   description=description, templates_dir=templates_dir)

    print(f"{out}  ({out.stat().st_size / 1024:.0f} KB)")
    print(f"  images from {templates_dir}")
    print(f"  macros    {len(macros)}: {', '.join(m['name'] for m in macros)}")
    print(f"  templates {len(have)} of {len(have) + len(missing)} included")
    for t in have:
        print(f"      + {t}")
    for t in missing:
        print(f"      - {t}  (never captured — the macro degrades to no-match)")

    # The pins are stripped by export_pack; say so rather than trusting it silently,
    # because a pack that ships target_position points the importer's macro at one of
    # *their* windows.
    with zipfile.ZipFile(out) as zf:
        leaked = sorted({
            key
            for entry in zf.namelist() if entry.startswith("macros/")
            for key in json.loads(zf.read(entry))
            if key in ps._MACHINE_SPECIFIC
        })
    if leaked:
        print(f"  ERROR: machine-specific pins present: {leaked}", file=sys.stderr)
        return 1
    print("  no machine-specific pins")

    # Same check the engine makes at run time, so a pack cannot ship a macro whose
    # template reference does not name a file it carries.
    carried = set(have)
    for macro in macros:
        for ref in iter_refs(macro.get("actions", [])):
            base = basename_of(ref)
            if base not in carried and base not in missing:
                print(f"  ERROR: {macro['name']} references unknown {base}",
                      file=sys.stderr)
                return 1

    if not have:
        # Not a failure — this is the normal state of a pack whose macros are written
        # but whose images have not been captured yet, and building it locally is how
        # you check the macros parse. But the whole point of publishing a pack is that
        # the images come with it, so a release must not carry one: `summoners-war`
        # would have shipped a 0.8 KB file that does nothing on import.
        out.unlink(missing_ok=True)
        print(f"  NOT PUBLISHABLE: no templates captured for {args.pack} yet",
              file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
