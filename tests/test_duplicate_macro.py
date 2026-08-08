"""Duplicating a macro so it can be pointed at another game client.

One macro per account is the chosen way to drive two clients, and its remaining cost
was making the copy: find the file, copy it, rename it, edit the name inside. This is
the same thing from the macro's context menu.

Driven through the real method with a stub, so no Tk window is needed.
"""

from types import SimpleNamespace

import pytest

from gui.app import App

pytestmark = pytest.mark.unit


class _Engine:
    def __init__(self, macros):
        self.macros = {m["name"]: m for m in macros}
        self.saved = []

    def get_macro(self, name):
        return self.macros.get(name)

    def list_macros(self):
        return list(self.macros.values())

    def get_folder(self, name):
        return self.macros[name].get("_folder", "")

    def save_macro(self, macro, folder=None):
        self.saved.append((dict(macro), folder))
        self.macros[macro["name"]] = macro


def _app(macros):
    engine = _Engine(macros)
    shown = []
    stub = SimpleNamespace(
        _engine=engine,
        _rebuild_list=lambda: None,
        _log=lambda msg, tag="info": None,
        _messages=shown,
    )
    # Bound after construction, because it needs the stub it lives on.
    stub._unused_name = lambda name: App._unused_name(stub, name)
    return stub, engine


def _duplicate(app, engine, name, monkeypatch):
    monkeypatch.setattr("gui.app.messagebox.showinfo",
                        lambda *a, **k: app._messages.append(a))
    monkeypatch.setattr("gui.app.messagebox.showerror",
                        lambda *a, **k: app._messages.append(a))
    App._duplicate_macro(app, name)
    return engine.saved[-1][0] if engine.saved else None


ORIGINAL = {
    "name": "Raid", "_folder": "Onmyoji", "actions": [{"type": "wait", "ms": 5}],
    "target_window": "Onmyoji", "target_class": "Win32Window",
    "target_hwnd": 111, "target_position": 0, "loop": True,
}


def test_the_copy_keeps_what_makes_the_macro_work(monkeypatch):
    app, engine = _app([ORIGINAL])
    copy = _duplicate(app, engine, "Raid", monkeypatch)
    assert copy["actions"] == ORIGINAL["actions"]
    assert copy["target_window"] == "Onmyoji"
    assert copy["target_class"] == "Win32Window"
    assert copy["loop"] is True


def test_the_copy_drops_the_window_pin(monkeypatch):
    """A duplicate that silently drove the *same* client as its original would look
    like it was working while doing everything twice to one account."""
    app, engine = _app([ORIGINAL])
    copy = _duplicate(app, engine, "Raid", monkeypatch)
    assert "target_hwnd" not in copy
    assert "target_position" not in copy


def test_the_user_is_told_to_point_it_somewhere(monkeypatch):
    app, engine = _app([ORIGINAL])
    _duplicate(app, engine, "Raid", monkeypatch)
    said = " ".join(str(m) for m in app._messages)
    assert "Pick window" in said and "same one" in said


def test_the_copy_lands_in_the_same_folder(monkeypatch):
    app, engine = _app([ORIGINAL])
    _duplicate(app, engine, "Raid", monkeypatch)
    assert engine.saved[-1][1] == "Onmyoji"


def test_runtime_only_keys_are_not_copied(monkeypatch):
    app, engine = _app([ORIGINAL])
    copy = _duplicate(app, engine, "Raid", monkeypatch)
    assert not any(k.startswith("_") for k in copy)


def test_the_name_does_not_collide(monkeypatch):
    app, engine = _app([ORIGINAL, {"name": "Raid (2)", "actions": []}])
    copy = _duplicate(app, engine, "Raid", monkeypatch)
    assert copy["name"] == "Raid (3)"


def test_duplicating_twice_gives_two_macros(monkeypatch):
    app, engine = _app([ORIGINAL])
    first = _duplicate(app, engine, "Raid", monkeypatch)
    second = _duplicate(app, engine, "Raid", monkeypatch)
    assert {first["name"], second["name"]} == {"Raid (2)", "Raid (3)"}


def test_a_missing_macro_does_nothing(monkeypatch):
    app, engine = _app([ORIGINAL])
    App._duplicate_macro(app, "no such macro")
    assert engine.saved == []


def test_the_copy_still_validates(monkeypatch):
    from engine.macro_engine import _validate

    app, engine = _app([ORIGINAL])
    _validate(_duplicate(app, engine, "Raid", monkeypatch))
