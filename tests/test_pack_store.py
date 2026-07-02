"""Unit tests for macro pack export/import."""

import json
import zipfile

import pytest

from engine import pack_store as ps

pytestmark = pytest.mark.unit


def _macro(name, template=None, folder=""):
    actions = []
    if template:
        actions = [{"type": "find_and_click", "template": f"templates/{template}"}]
    return {"name": name, "_folder": folder, "actions": actions}


def _write(path, data=b"img"):
    path.write_bytes(data)


def test_referenced_templates_dedupes():
    macros = [_macro("a", "x.png"), _macro("b", "x.png"), _macro("c", "y.png")]
    assert ps.referenced_templates(macros) == ["x.png", "y.png"]


def test_export_creates_valid_pack(tmp_path):
    tdir = tmp_path / "templates"
    tdir.mkdir()
    _write(tdir / "x.png")
    dest = tmp_path / "pack.wmbpack"

    ps.export_pack([_macro("a", "x.png")], dest, name="MyPack",
                   game="Onmyoji", templates_dir=tdir)

    assert dest.exists()
    with zipfile.ZipFile(dest) as z:
        names = z.namelist()
        assert "manifest.json" in names
        assert "macros/a.json" in names
        assert "templates/x.png" in names
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["name"] == "MyPack"
        assert manifest["game"] == "Onmyoji"
        assert manifest["templates"] == ["x.png"]
        macro = json.loads(z.read("macros/a.json"))
        assert "_folder" not in macro  # runtime keys stripped


def test_roundtrip_import(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write(src / "x.png", b"orig")
    dest = tmp_path / "pack.wmbpack"
    ps.export_pack([_macro("a", "x.png")], dest, name="Pack",
                   game="Onmyoji", templates_dir=src)

    dst = tmp_path / "dst"
    dst.mkdir()
    result = ps.extract_pack(dest, templates_dir=dst)

    assert (dst / "x.png").read_bytes() == b"orig"
    assert result.folder == "Onmyoji"
    assert len(result.macros) == 1
    macro = result.macros[0]
    assert macro["_folder"] == "Onmyoji"
    assert macro["actions"][0]["template"] == "templates/x.png"


def test_import_renames_on_template_collision(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write(src / "x.png", b"packimg")
    dest = tmp_path / "p.wmbpack"
    ps.export_pack([_macro("a", "x.png")], dest, name="P", templates_dir=src)

    dst = tmp_path / "dst"
    dst.mkdir()
    _write(dst / "x.png", b"existing")  # collision

    result = ps.extract_pack(dest, templates_dir=dst)

    assert (dst / "x.png").read_bytes() == b"existing"      # existing untouched
    assert (dst / "x_2.png").read_bytes() == b"packimg"     # pack's copy renamed
    assert result.template_renames == {"x.png": "x_2.png"}
    assert result.macros[0]["actions"][0]["template"] == "templates/x_2.png"


def test_import_dedupes_macro_name(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "p.wmbpack"
    ps.export_pack([_macro("farm")], dest, name="P", templates_dir=src)

    dst = tmp_path / "dst"
    dst.mkdir()
    result = ps.extract_pack(dest, templates_dir=dst,
                             existing_macro_names=frozenset({"farm"}))
    assert result.macros[0]["name"] == "farm (2)"


def test_into_folder_override(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "p.wmbpack"
    ps.export_pack([_macro("a")], dest, name="P", game="Onmyoji", templates_dir=src)

    dst = tmp_path / "dst"
    dst.mkdir()
    result = ps.extract_pack(dest, templates_dir=dst, into_folder="Custom")
    assert result.folder == "Custom"
    assert result.macros[0]["_folder"] == "Custom"


def test_read_manifest(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "p.wmbpack"
    ps.export_pack([_macro("a", "x.png")], dest, name="P", game="G",
                   description="hi", templates_dir=src)
    manifest = ps.read_manifest(dest)
    assert manifest["name"] == "P"
    assert manifest["description"] == "hi"


def test_safe_folder_sanitizes():
    assert ps._safe_folder("Summoners War") == "Summoners War"
    assert ps._safe_folder("../evil/Onmyoji") == "Onmyoji"
    assert ps._safe_folder("") == "Imported"
