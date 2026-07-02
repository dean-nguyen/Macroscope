"""Tests for first-run seeding of bundled starter macros."""

import json

import pytest

from engine.paths import PACKS_DIR, _seed_macros

pytestmark = pytest.mark.unit


def _macro_file(path, name):
    path.write_text(json.dumps({"name": name, "actions": []}), encoding="utf-8")


def test_seed_copies_named_macros(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _macro_file(src / "a.macro.json", "Onmyoji - Soul")
    _macro_file(src / "b.macro.json", "Onmyoji - Exp")
    (src / "notes.txt").write_text("ignore", encoding="utf-8")

    dest = tmp_path / "dest"
    assert _seed_macros(src, dest) == 2
    assert (dest / "Onmyoji - Soul.json").exists()
    assert (dest / "Onmyoji - Exp.json").exists()


def test_seed_skips_existing_and_preserves_it(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _macro_file(src / "a.macro.json", "Keep")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "Keep.json").write_text(
        json.dumps({"name": "Keep", "actions": [{"type": "click"}]}), encoding="utf-8"
    )

    assert _seed_macros(src, dest) == 0
    data = json.loads((dest / "Keep.json").read_text(encoding="utf-8"))
    assert data["actions"] == [{"type": "click"}]  # user's version untouched


def test_seed_missing_source_dir(tmp_path):
    assert _seed_macros(tmp_path / "nope", tmp_path / "dest") == 0


def test_seed_skips_macro_without_name(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.macro.json").write_text('{"actions": []}', encoding="utf-8")
    assert _seed_macros(src, tmp_path / "dest") == 0


def test_bundled_onmyoji_pack_seeds_all_macros(tmp_path):
    # The real bundled Onmyoji pack should seed its 8 activity macros.
    assert _seed_macros(PACKS_DIR / "onmyoji", tmp_path / "out") == 8
