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


def _write_pack(tmp_path, name, actions):
    src = tmp_path / "pack"
    src.mkdir(exist_ok=True)
    (src / f"{name.lower()}.macro.json").write_text(
        json.dumps({"name": name, "actions": actions}), encoding="utf-8")
    return src


def test_a_fixed_pack_macro_reaches_an_existing_install(monkeypatch, tmp_path):
    """Seeding never updated anything, so a fix to a shipped macro reached new
    installs only. Measured on a real machine: the installed Realm Raid macros were
    several fixes behind the pack while they were being run."""
    root = tmp_path / "data"
    src = _write_pack(tmp_path, "Alpha", [{"type": "wait", "ms": 6000}])
    dest = _run(monkeypatch, tmp_path, src, root)
    assert "6000" in (dest / "Alpha.json").read_text(encoding="utf-8")

    _write_pack(tmp_path, "Alpha", [{"type": "wait", "ms": 800}])   # the pack is fixed
    dest = _run(monkeypatch, tmp_path, src, root)
    assert "800" in (dest / "Alpha.json").read_text(encoding="utf-8")


def test_a_macro_the_user_edited_is_left_alone_and_reported(monkeypatch, tmp_path):
    """Guessing which side to keep is not seeding's business — but going quiet about
    it would leave them on an old version with no way to know."""
    root = tmp_path / "data"
    src = _write_pack(tmp_path, "Alpha", [{"type": "wait", "ms": 6000}])
    dest = _run(monkeypatch, tmp_path, src, root)
    (dest / "Alpha.json").write_text(
        json.dumps({"name": "Alpha", "actions": [{"type": "wait", "ms": 42}]}),
        encoding="utf-8")

    _write_pack(tmp_path, "Alpha", [{"type": "wait", "ms": 800}])
    said = []
    monkeypatch.setattr(paths, "PACKS_DIR", src.parent)
    monkeypatch.setattr(paths, "MACROS_DIR", root / "macros")
    monkeypatch.setattr(paths, "data_root", lambda: root)
    paths.seed_starter_macros(src.name, log_fn=said.append)

    assert "42" in (dest / "Alpha.json").read_text(encoding="utf-8")
    assert any("differs" in line and "Alpha" in line for line in said), said


def test_an_old_marker_format_leaves_files_alone_rather_than_guessing(
        monkeypatch, tmp_path):
    """A marker that recorded only names cannot tell an untouched file from an edited
    one. Overwriting on that basis could throw away someone's work."""
    root = tmp_path / "data"
    root.mkdir(parents=True)
    dest = root / "macros" / "Pack"
    dest.mkdir(parents=True)
    (dest / "Alpha.json").write_text('{"name": "Alpha", "actions": ["old"]}',
                                     encoding="utf-8")
    (root / ".starter_seeded").write_text(json.dumps({"offered": ["Alpha"]}),
                                          encoding="utf-8")

    src = _write_pack(tmp_path, "Alpha", [{"type": "wait", "ms": 800}])
    monkeypatch.setattr(paths, "PACKS_DIR", src.parent)
    monkeypatch.setattr(paths, "MACROS_DIR", root / "macros")
    monkeypatch.setattr(paths, "data_root", lambda: root)
    said = []
    paths.seed_starter_macros(src.name, log_fn=said.append)

    assert "old" in (dest / "Alpha.json").read_text(encoding="utf-8")
    assert any("differs" in line for line in said), said


def test_a_file_already_matching_the_pack_is_recorded_not_rewritten(
        monkeypatch, tmp_path):
    """So the first launch after this change adopts what is already correct, and the
    one after it can update cleanly."""
    root = tmp_path / "data"
    src = _write_pack(tmp_path, "Alpha", [{"type": "wait", "ms": 800}])
    _run(monkeypatch, tmp_path, src, root)

    marker = json.loads((root / ".starter_seeded").read_text(encoding="utf-8"))
    assert "Alpha" in marker["seeded"], marker

    said = []
    monkeypatch.setattr(paths, "PACKS_DIR", src.parent)
    monkeypatch.setattr(paths, "MACROS_DIR", root / "macros")
    monkeypatch.setattr(paths, "data_root", lambda: root)
    paths.seed_starter_macros(src.name, log_fn=said.append)
    assert not said, said        # nothing to announce on an unchanged second launch


def test_an_old_style_marker_is_treated_as_nothing_recorded(monkeypatch, tmp_path):
    """It held `1` and said nothing about what was seeded. Reading it as empty is
    what lets an install from before a macro existed finally receive it — and it can
    only ever add, because an existing file is never overwritten."""
    root = tmp_path / "data"
    root.mkdir(parents=True)
    (root / ".starter_seeded").write_text("1", encoding="utf-8")

    dest = _run(monkeypatch, tmp_path, _pack(tmp_path, "Alpha"), root)
    assert (dest / "Alpha.json").exists()
    assert set(paths._read_seeded(root / ".starter_seeded")) == {"Alpha"}


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


# ── pinning a macro must not cost the user every future fix ────────────────────
#
# The window picker writes target_window/target_class/target_position/target_hwnd, so
# pinning a macro — a required step with two game clients, not an optional tweak — changed
# the file and made seeding call it "edited". Measured on a live install: both Realm Raid
# macros read DIVERGED and were being left alone, so a day of pack fixes would never have
# reached the macros actually being run. Same failure as "a macro seeded once stayed at
# that version forever", with a different cause.

def _installed(tmp_path, name):
    return tmp_path / "data" / "macros" / "pack" / f"{name}.json"


def test_a_pinned_macro_still_takes_the_update(monkeypatch, tmp_path):
    src = _pack(tmp_path, "Alpha")
    root = tmp_path / "data"
    _run(monkeypatch, tmp_path, src, root)

    # The user picks a window: exactly what gui/editor.py writes.
    path = _installed(tmp_path, "Alpha")
    macro = json.loads(path.read_text(encoding="utf-8"))
    macro.update({"target_window": "陰陽師Onmyoji", "target_class": "Win32Window",
                  "target_position": 1, "target_hwnd": 264108})
    path.write_text(json.dumps(macro, indent=2, ensure_ascii=False), encoding="utf-8")

    # The pack moves on.
    (src / "alpha.macro.json").write_text(
        json.dumps({"name": "Alpha", "actions": [{"type": "wait", "ms": 900}]}),
        encoding="utf-8")
    _run(monkeypatch, tmp_path, src, root)

    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["actions"] == [{"type": "wait", "ms": 900}], "the fix did not arrive"
    assert after["target_position"] == 1, "the pin was thrown away"
    assert after["target_hwnd"] == 264108
    assert after["target_window"] == "陰陽師Onmyoji"
    assert after["target_class"] == "Win32Window"


def test_a_macro_the_user_really_edited_is_still_left_alone(monkeypatch, tmp_path):
    """The rule that must not be weakened by any of this."""
    src = _pack(tmp_path, "Alpha")
    root = tmp_path / "data"
    _run(monkeypatch, tmp_path, src, root)

    path = _installed(tmp_path, "Alpha")
    macro = json.loads(path.read_text(encoding="utf-8"))
    macro["actions"] = [{"type": "wait", "ms": 1}]        # their own change
    macro["target_position"] = 0                          # and a pin
    path.write_text(json.dumps(macro, indent=2), encoding="utf-8")

    (src / "alpha.macro.json").write_text(
        json.dumps({"name": "Alpha", "actions": [{"type": "wait", "ms": 900}]}),
        encoding="utf-8")
    _, said = _run(monkeypatch, tmp_path, src, root), None
    kept = json.loads(path.read_text(encoding="utf-8"))
    assert kept["actions"] == [{"type": "wait", "ms": 1}], "their edit was overwritten"


def test_pinning_alone_does_not_count_as_an_edit(monkeypatch, tmp_path):
    """Reported, too: a macro that is only pinned must not be announced as diverged, or
    the log cries wolf on every launch of a normal two-client setup."""
    src = _pack(tmp_path, "Alpha")
    root = tmp_path / "data"
    _run(monkeypatch, tmp_path, src, root)

    path = _installed(tmp_path, "Alpha")
    macro = json.loads(path.read_text(encoding="utf-8"))
    macro["target_position"] = 1
    path.write_text(json.dumps(macro, indent=2), encoding="utf-8")

    said = []
    monkeypatch.setattr(paths, "PACKS_DIR", src.parent)
    monkeypatch.setattr(paths, "MACROS_DIR", root / "macros")
    monkeypatch.setattr(paths, "data_root", lambda: root)
    paths.seed_starter_macros(src.name, log_fn=said.append)
    assert not any("differs" in line for line in said), said
