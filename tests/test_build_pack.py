"""Tests for assembling a downloadable pack.

The point of a separate builder is the *source*. The app's own "Export as pack…"
exports the macros as they sit in your library, and those carry the pins you made
while testing — measured on this machine, the two Realm Raid macros in use had
`target_hwnd: 1641012` and `target_position: 0` in them. So the builder reads the
versioned `packs/<name>/*.macro.json` instead, and refuses to write a pack that still
carries either pin.

These run against a fixture pack rather than the repo's own, because CI has no
`templates/` — the images are a user's captures and are git-ignored.
"""

import json
import zipfile

import pytest

from tools import build_pack

pytestmark = pytest.mark.unit


@pytest.fixture
def pack_source(tmp_path, monkeypatch):
    """A pack directory shaped like packs/onmyoji, with one template captured."""
    packs = tmp_path / "packs" / "demo"
    packs.mkdir(parents=True)
    (packs / "raid.macro.json").write_text(json.dumps({
        "name": "Demo - Raid",
        "background": True,
        "target_window": "Demo",
        "target_class": "Win32Window",
        "actions": [
            {"type": "find_and_click", "template": "templates/have.png"},
            {"type": "image_check", "template": "templates/never_captured.png"},
        ],
    }), encoding="utf-8")
    (packs / "templates.spec.json").write_text(
        json.dumps({"description": "Demo pack", "templates": []}), encoding="utf-8")

    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "have.png").write_bytes(b"png")

    monkeypatch.setattr(build_pack, "ROOT", tmp_path)
    return tmp_path


def _build(tmp_path, *extra):
    out = tmp_path / "out.wmbpack"
    code = build_pack.main(["demo", "--out", str(out),
                            "--templates", str(tmp_path / "templates"), *extra])
    return code, out


def test_it_builds_from_the_pack_source(pack_source, capsys):
    code, out = _build(pack_source)
    assert code == 0
    with zipfile.ZipFile(out) as zf:
        assert "macros/Demo - Raid.json" in zf.namelist()
        assert "templates/have.png" in zf.namelist()


def test_a_template_nobody_has_captured_is_not_a_build_failure(pack_source, capsys):
    """Most of this pack's templates are states you cannot summon — a CAPTCHA, a
    disconnect. Refusing to build without them means never building."""
    code, out = _build(pack_source)
    assert code == 0
    with zipfile.ZipFile(out) as zf:
        assert "templates/never_captured.png" not in zf.namelist()
    assert "never_captured.png" in capsys.readouterr().out


def test_the_pins_that_name_one_machine_never_ship(pack_source):
    """Belt and braces with test_pack_store: the builder verifies the zip it wrote,
    because a pack carrying target_position aims someone else's macro at one of
    *their* windows — _resolve_hwnd checks it before anything else."""
    src = pack_source / "packs" / "demo" / "raid.macro.json"
    macro = json.loads(src.read_text(encoding="utf-8"))
    macro.update({"target_hwnd": 1641012, "target_position": 0})
    src.write_text(json.dumps(macro), encoding="utf-8")

    code, out = _build(pack_source)

    assert code == 0
    with zipfile.ZipFile(out) as zf:
        shipped = json.loads(zf.read("macros/Demo - Raid.json"))
    assert "target_hwnd" not in shipped and "target_position" not in shipped
    assert shipped["target_window"] == "Demo", "what names the window portably stays"


def test_it_fails_loudly_if_a_pin_ever_survives(pack_source, monkeypatch):
    """The check has to be able to fail, or it is decoration.

    Patching `_MACHINE_SPECIFIC` proves nothing — export and this check read the same
    constant, so moving it moves both. The only way to see the check work is to make
    the export itself leak.
    """
    def leaky_export(macros, dest, **kw):
        with zipfile.ZipFile(dest, "w") as zf:
            zf.writestr("manifest.json", json.dumps({"templates": []}))
            for macro in macros:
                zf.writestr(f"macros/{macro['name']}.json",
                            json.dumps({**macro, "target_position": 0}))
        return dest

    monkeypatch.setattr(build_pack.ps, "export_pack", leaky_export)
    code, _ = _build(pack_source)
    assert code == 1


def test_a_pack_with_no_captured_images_is_not_publishable(pack_source):
    """Exit 3 is a contract with release.yml, which skips that pack instead of failing.

    Building a pack whose images do not exist yet is the normal way to check the macros
    parse, so it must not be an error. But publishing one is pointless: `summoners-war`
    would have gone onto a release as a 0.8 KB file that does nothing on import.
    """
    (pack_source / "templates" / "have.png").unlink()

    code, out = _build(pack_source)

    assert code == 3
    assert not out.exists(), "an unpublishable pack must not be left for the workflow"


def test_the_skip_is_by_captured_images_not_by_the_spec(pack_source):
    """One image is enough. Most of this pack's templates will always be missing."""
    code, out = _build(pack_source)
    assert code == 0 and out.exists()


def test_an_unknown_pack_is_an_error_not_an_empty_zip(pack_source):
    out = pack_source / "out.wmbpack"
    assert build_pack.main(["nosuch", "--out", str(out)]) == 2
    assert not out.exists()


def test_a_pack_directory_with_no_macros_is_an_error(pack_source):
    for path in (pack_source / "packs" / "demo").glob("*.macro.json"):
        path.unlink()
    code, out = _build(pack_source)
    assert code == 2
    assert not out.exists()


def test_the_manifest_carries_the_spec_description(pack_source):
    _, out = _build(pack_source)
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["description"] == "Demo pack"
    assert manifest["game"] == "Demo"
    # Every template the macros reference, captured or not — so an importer can see
    # what the pack is short of rather than discovering it in a run.
    assert manifest["templates"] == ["have.png", "never_captured.png"]
