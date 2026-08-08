"""Tests for offering pack macros to the user's library.

Two failures this replaced, both of which made shipped work invisible:

The seeding ran only inside a packaged build (`sys.frozen`), so anyone running from
source — which is how this project is installed — opened the app to an empty macro
list and no sign that a pack existed.

And its marker was a single flag, so it seeded once and never again: a macro added to
the pack afterwards never reached anyone who had already launched the app.
"""

import json

import pytest

from engine import paths

pytestmark = pytest.mark.unit


def _pack(tmp_path, *names):
    src = tmp_path / "pack"
    src.mkdir(exist_ok=True)
    for name in names:
        (src / f"{name.lower().replace(' ', '-')}.macro.json").write_text(
            json.dumps({"name": name, "actions": []}), encoding="utf-8")
    return src


def _run(monkeypatch, tmp_path, src, root=None):
    """seed_starter_macros with the data root pointed at a temp directory."""
    root = root or tmp_path / "data"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "PACKS_DIR", src.parent)
    monkeypatch.setattr(paths, "MACROS_DIR", root / "macros")
    monkeypatch.setattr(paths, "data_root", lambda: root)
    paths.seed_starter_macros(src.name)
    return root / "macros" / src.name.capitalize()


def test_running_from_source_still_gets_the_pack(monkeypatch, tmp_path):
    """The whole reason this was invisible: sys.frozen is False from source."""
    assert not getattr(__import__("sys"), "frozen", False), "premise: not a build"
    dest = _run(monkeypatch, tmp_path, _pack(tmp_path, "Alpha", "Beta"))
    assert {p.name for p in dest.glob("*.json")} == {"Alpha.json", "Beta.json"}


def test_a_macro_added_to_the_pack_later_arrives_on_the_next_launch(
        monkeypatch, tmp_path):
    root = tmp_path / "data"
    src = _pack(tmp_path, "Alpha")
    dest = _run(monkeypatch, tmp_path, src, root)
    assert {p.name for p in dest.glob("*.json")} == {"Alpha.json"}

    _pack(tmp_path, "Alpha", "Beta")            # the pack grows
    dest = _run(monkeypatch, tmp_path, src, root)
    assert {p.name for p in dest.glob("*.json")} == {"Alpha.json", "Beta.json"}


def test_a_macro_the_user_deleted_stays_deleted(monkeypatch, tmp_path):
    root = tmp_path / "data"
    src = _pack(tmp_path, "Alpha", "Beta")
    dest = _run(monkeypatch, tmp_path, src, root)
    (dest / "Alpha.json").unlink()

    dest = _run(monkeypatch, tmp_path, src, root)
    assert {p.name for p in dest.glob("*.json")} == {"Beta.json"}


def test_the_users_own_edits_are_never_overwritten(monkeypatch, tmp_path):
    root = tmp_path / "data"
    src = _pack(tmp_path, "Alpha")
    dest = _run(monkeypatch, tmp_path, src, root)
    (dest / "Alpha.json").write_text('{"name": "Alpha", "actions": ["mine"]}',
                                     encoding="utf-8")

    # Even with the record wiped, an existing file is left alone.
    (root / ".starter_seeded").unlink()
    dest = _run(monkeypatch, tmp_path, src, root)
    assert "mine" in (dest / "Alpha.json").read_text(encoding="utf-8")


def test_an_old_style_marker_is_treated_as_nothing_recorded(monkeypatch, tmp_path):
    """It held `1` and said nothing about what was seeded. Reading it as empty is
    what lets an install from before a macro existed finally receive it — and it can
    only ever add, because an existing file is never overwritten."""
    root = tmp_path / "data"
    root.mkdir(parents=True)
    (root / ".starter_seeded").write_text("1", encoding="utf-8")

    dest = _run(monkeypatch, tmp_path, _pack(tmp_path, "Alpha"), root)
    assert (dest / "Alpha.json").exists()
    assert paths._read_offered(root / ".starter_seeded") == {"Alpha"}


def test_an_unreadable_marker_does_not_stop_the_app(monkeypatch, tmp_path):
    root = tmp_path / "data"
    root.mkdir(parents=True)
    (root / ".starter_seeded").write_text("{not json", encoding="utf-8")
    dest = _run(monkeypatch, tmp_path, _pack(tmp_path, "Alpha"), root)
    assert (dest / "Alpha.json").exists()


def test_a_missing_pack_directory_is_not_an_error(monkeypatch, tmp_path):
    root = tmp_path / "data"
    root.mkdir(parents=True)
    monkeypatch.setattr(paths, "PACKS_DIR", tmp_path / "nowhere")
    monkeypatch.setattr(paths, "MACROS_DIR", root / "macros")
    monkeypatch.setattr(paths, "data_root", lambda: root)
    paths.seed_starter_macros("nothing")        # must not raise
