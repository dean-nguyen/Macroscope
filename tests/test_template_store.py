"""Unit tests for the template library data layer."""

import pytest
from PIL import Image

from engine import template_store as ts

pytestmark = pytest.mark.unit


def _macro(name, actions):
    return {"name": name, "actions": actions}


# ── references / scanning ─────────────────────────────────────────────────────


def test_basename_handles_both_separators():
    assert ts.basename_of("templates/a.png") == "a.png"
    assert ts.basename_of("templates\\b.png") == "b.png"
    assert ts.basename_of("c.png") == "c.png"


def test_iter_refs_recurses_branches():
    actions = [
        {"type": "find_and_click", "template": "templates/a.png",
         "on_not_found": [{"type": "image_check", "template": "templates/b.png"}]},
        {"type": "click"},
    ]
    assert sorted(ts.iter_refs(actions)) == ["templates/a.png", "templates/b.png"]


def test_usage_by_name_maps_files_to_macros():
    macros = [
        _macro("m1", [{"type": "find_and_click", "template": "templates/a.png"}]),
        _macro("m2", [{"type": "image_wait", "template": "templates/a.png"}]),
        _macro("m3", [{"type": "click"}]),
    ]
    usage = ts.usage_by_name(macros)
    assert usage["a.png"] == ["m1", "m2"]
    assert "click" not in usage


def test_find_missing_detects_dangling_references():
    macros = [_macro("m", [{"type": "image_check", "template": "templates/gone.png"}])]
    templates = []  # nothing on disk
    assert ts.find_missing(macros, templates) == ["gone.png"]


# ── rename reference rewriting (the risky bit) ────────────────────────────────


def test_update_references_rewrites_and_is_immutable():
    original = _macro(
        "m",
        [
            {"type": "find_and_click", "template": "templates/old.png",
             "on_found": [{"type": "image_check", "template": "templates/old.png"}]},
        ],
    )
    updated = ts.update_references(original, "old.png", "new.png")

    # rewritten copy points at the new name, top-level and nested
    assert updated["actions"][0]["template"] == "templates/new.png"
    assert updated["actions"][0]["on_found"][0]["template"] == "templates/new.png"
    # original left untouched
    assert original["actions"][0]["template"] == "templates/old.png"
    assert original["actions"][0]["on_found"][0]["template"] == "templates/old.png"


def test_update_references_returns_none_when_unused():
    macro = _macro("m", [{"type": "click"}])
    assert ts.update_references(macro, "old.png", "new.png") is None


# ── filename helpers ──────────────────────────────────────────────────────────


def test_sanitize_stem_strips_unsafe_chars_and_extension():
    assert ts.sanitize_stem("../evil name.png") == "evil_name"
    assert ts.sanitize_stem("  ") == "template"


def test_build_new_filename_preserves_extension():
    assert ts.build_new_filename("region_1.png", "collect button") == "collect_button.png"
    assert ts.build_new_filename("shot.jpg", "hero") == "hero.jpg"


# ── filesystem operations (real files) ────────────────────────────────────────


def _png(path, size=(10, 8)):
    Image.new("RGB", size, (120, 60, 200)).save(path)


def test_list_templates_reads_files(tmp_path):
    _png(tmp_path / "a.png", (10, 8))
    _png(tmp_path / "b.png", (4, 4))
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")

    items = ts.list_templates(tmp_path)
    names = [t.name for t in items]
    assert names == ["a.png", "b.png"]  # sorted, text file excluded
    a = items[0]
    assert (a.width, a.height) == (10, 8)
    assert a.ref == "templates/a.png"
    assert a.size_bytes > 0


def test_rename_file_moves_and_blocks_collisions(tmp_path):
    _png(tmp_path / "old.png")
    _png(tmp_path / "taken.png")

    ts.rename_file("old.png", "renamed.png", tmp_path)
    assert (tmp_path / "renamed.png").exists()
    assert not (tmp_path / "old.png").exists()

    _png(tmp_path / "again.png")
    with pytest.raises(ValueError):
        ts.rename_file("again.png", "taken.png", tmp_path)


def test_delete_file_is_idempotent(tmp_path):
    _png(tmp_path / "x.png")
    ts.delete_file("x.png", tmp_path)
    assert not (tmp_path / "x.png").exists()
    ts.delete_file("x.png", tmp_path)  # already gone → no error


def test_unique_name_avoids_overwrite(tmp_path):
    assert ts.unique_name("new.png", tmp_path) == "new.png"  # nothing there yet
    _png(tmp_path / "shot.png")
    assert ts.unique_name("shot.png", tmp_path) == "shot_2.png"
    _png(tmp_path / "shot_2.png")
    assert ts.unique_name("shot.png", tmp_path) == "shot_3.png"


def test_find_orphans(tmp_path):
    _png(tmp_path / "used.png")
    _png(tmp_path / "orphan.png")
    templates = ts.list_templates(tmp_path)
    usage = {"used.png": ["m1"]}
    orphans = [t.name for t in ts.find_orphans(templates, usage)]
    assert orphans == ["orphan.png"]
