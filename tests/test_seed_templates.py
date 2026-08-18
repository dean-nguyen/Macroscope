"""Tests for installing the images a pack publishes.

The exe bundles `packs/` wholesale (`--include-data-dir=packs=packs`), so once a pack
carries its template images the install already *has* them. Seeding copied only the
macro files, so a fresh install opened with two macros and listed every template as
missing — while the files sat inside the same directory. That is the "I installed it and
nothing happens" complaint, and the data was there all along.

The rules that matter are about not destroying work. A user who re-captured a template
because the shipped one did not match their client must not have it overwritten on the
next launch, and one who deleted it must not have it come back — deleting a template
that does not match your client is a real decision. Both are recognised by hash rather
than guessed at, the same way `_sync_macros` already did for macros.
"""

import json

import pytest

from engine import paths

pytestmark = pytest.mark.unit


def _pack(tmp_path, **images):
    """A pack directory with one macro and the given `name: bytes` images."""
    src = tmp_path / "packs" / "demo"
    (src / "templates").mkdir(parents=True, exist_ok=True)
    (src / "raid.macro.json").write_text(
        json.dumps({"name": "Demo", "actions": []}), encoding="utf-8")
    for name, data in images.items():
        (src / "templates" / name).write_bytes(data)
    return src


def _run(monkeypatch, tmp_path, src):
    root = tmp_path / "data"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "PACKS_DIR", src.parent)
    monkeypatch.setattr(paths, "MACROS_DIR", root / "macros")
    monkeypatch.setattr(paths, "TEMPLATES_DIR", root / "templates")
    monkeypatch.setattr(paths, "data_root", lambda: root)
    said = []
    paths.seed_starter_macros(src.name, log_fn=said.append)
    return root / "templates", said


def test_a_pack_image_reaches_a_fresh_install(monkeypatch, tmp_path):
    """The regression: the exe carried these and never installed them."""
    templates, said = _run(monkeypatch, tmp_path, _pack(tmp_path, **{"a.png": b"one"}))
    assert (templates / "a.png").read_bytes() == b"one"
    assert any("image" in line for line in said), said


def test_only_images_are_taken(monkeypatch, tmp_path):
    src = _pack(tmp_path, **{"a.png": b"one"})
    (src / "templates" / "notes.txt").write_text("not an image", encoding="utf-8")
    templates, _ = _run(monkeypatch, tmp_path, src)
    assert not (templates / "notes.txt").exists()


def test_an_image_the_user_recaptured_is_never_overwritten(monkeypatch, tmp_path):
    """The whole reason this is hash-based.

    The shipped image may not match their client at all — measured, a marker scored
    1.000 on one client and 0.697 on another — so re-capturing it is the documented
    fix. Undoing that on the next launch would break the account that was working.
    """
    src = _pack(tmp_path, **{"a.png": b"one"})
    templates, _ = _run(monkeypatch, tmp_path, src)

    (templates / "a.png").write_bytes(b"my own capture")
    (src / "templates" / "a.png").write_bytes(b"pack moved on")
    _, said = _run(monkeypatch, tmp_path, src)

    assert (templates / "a.png").read_bytes() == b"my own capture"
    assert any("differs" in line for line in said), said


def test_an_untouched_image_takes_the_pack_update(monkeypatch, tmp_path):
    src = _pack(tmp_path, **{"a.png": b"one"})
    templates, _ = _run(monkeypatch, tmp_path, src)

    (src / "templates" / "a.png").write_bytes(b"recut")
    _, said = _run(monkeypatch, tmp_path, src)

    assert (templates / "a.png").read_bytes() == b"recut"
    assert any("Updated" in line and "image" in line for line in said), said


def test_a_deleted_image_does_not_come_back(monkeypatch, tmp_path):
    """Deleting a template that does not match your client is a real decision."""
    src = _pack(tmp_path, **{"a.png": b"one"})
    templates, _ = _run(monkeypatch, tmp_path, src)

    (templates / "a.png").unlink()
    _run(monkeypatch, tmp_path, src)

    assert not (templates / "a.png").exists()


def test_seeding_twice_changes_nothing_and_says_nothing(monkeypatch, tmp_path):
    src = _pack(tmp_path, **{"a.png": b"one"})
    _run(monkeypatch, tmp_path, src)
    _, said = _run(monkeypatch, tmp_path, src)
    assert said == []


def test_a_pack_with_no_templates_directory_is_fine(monkeypatch, tmp_path):
    src = _pack(tmp_path)
    (src / "templates").rmdir()
    templates, said = _run(monkeypatch, tmp_path, src)
    assert not any("image" in line for line in said), said


def test_an_image_already_on_disk_before_seeding_is_left_alone(monkeypatch, tmp_path):
    """A marker written before images were seeded records none of them, so everything
    already there is the user's — including a hand-captured file with a pack name."""
    src = _pack(tmp_path, **{"a.png": b"pack version"})
    root = tmp_path / "data"
    (root / "templates").mkdir(parents=True)
    (root / "templates" / "a.png").write_bytes(b"was here first")
    (root / ".starter_seeded").write_text(json.dumps({"seeded": {}}), encoding="utf-8")

    templates, said = _run(monkeypatch, tmp_path, src)

    assert (templates / "a.png").read_bytes() == b"was here first"
    assert any("differs" in line for line in said), said


def test_the_marker_keeps_macros_and_images_apart(monkeypatch, tmp_path):
    src = _pack(tmp_path, **{"a.png": b"one"})
    _run(monkeypatch, tmp_path, src)
    marker = json.loads((tmp_path / "data" / ".starter_seeded").read_text("utf-8"))
    assert "Demo" in marker["seeded"]
    assert "a.png" in marker["templates"]
    assert "a.png" not in marker["seeded"]


def test_the_report_comes_back_tagged_for_the_log(monkeypatch, tmp_path):
    """The gap this closes: seeding runs before the window exists, so `log_fn` reached
    stdlib logging only — invisible in a build with the console disabled. The lines that
    matter say a file of yours differs and was left alone, which is advice nobody could
    read. `gui/app.py` opens the log drawer for a "warn", so the severity has to survive.
    """
    src = _pack(tmp_path, **{"a.png": b"one"})
    root = tmp_path / "data"
    monkeypatch.setattr(paths, "PACKS_DIR", src.parent)
    monkeypatch.setattr(paths, "MACROS_DIR", root / "macros")
    monkeypatch.setattr(paths, "TEMPLATES_DIR", root / "templates")
    monkeypatch.setattr(paths, "data_root", lambda: root)
    root.mkdir(parents=True, exist_ok=True)

    notes = paths.seed_starter_macros("demo")
    assert [tag for _, tag in notes] == ["ok", "ok"], notes

    (root / "templates" / "a.png").write_bytes(b"my own capture")
    (src / "templates" / "a.png").write_bytes(b"pack moved on")
    notes = paths.seed_starter_macros("demo")

    assert notes, "a kept local version must be reported"
    assert all(tag == "warn" for _, tag in notes), notes
    assert "differs" in notes[0][0]


def test_log_fn_still_takes_one_argument(monkeypatch, tmp_path):
    """Kept compatible on purpose: the callback is also `log.info` and a bare list
    append in these tests, neither of which knows about tags."""
    src = _pack(tmp_path, **{"a.png": b"one"})
    templates, said = _run(monkeypatch, tmp_path, src)
    assert said and all(isinstance(line, str) for line in said)
