"""Tests for recognising a packaged build.

`data_root` promises that a packaged install keeps user data in %APPDATA% "regardless
of install location (Program Files, Desktop, etc.)". It did not. The gate was
`sys.frozen`, which is **PyInstaller's** marker, and `.github/workflows/release.yml`
builds with **Nuitka**.

Measured on a compiled one-liner: `sys.frozen` absent, `__compiled__` True. And on the
real build — the packaged app wrote `macros/`, `templates/` and `.starter_seeded` next
to its own exe. In Program Files that directory is read-only, so the app could not
save a macro at all; anywhere else the data is silently orphaned by the next install.

`migrate_legacy_data` was gated on the same flag, so the recovery path was dead too.
"""

import pytest

from engine import paths

pytestmark = pytest.mark.unit


@pytest.fixture
def as_nuitka(monkeypatch):
    """What a Nuitka build looks like: `__compiled__` present, `sys.frozen` absent."""
    monkeypatch.setitem(paths.__dict__, "__compiled__", True)
    monkeypatch.delattr("sys.frozen", raising=False)


@pytest.fixture
def as_pyinstaller(monkeypatch):
    monkeypatch.delitem(paths.__dict__, "__compiled__", raising=False)
    monkeypatch.setattr("sys.frozen", True, raising=False)


def test_running_from_source_is_not_packaged():
    assert not paths.is_packaged()


def test_a_nuitka_build_is_recognised(as_nuitka):
    """The regression: this was False, and every packaged install paid for it."""
    assert paths.is_packaged()


def test_a_pyinstaller_build_is_still_recognised(as_pyinstaller):
    """Both markers, so changing packager cannot silently move everyone's data."""
    assert paths.is_packaged()


def test_a_packaged_build_keeps_user_data_in_appdata(as_nuitka, monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert paths.data_root() == tmp_path / paths.APP_NAME


def test_a_packaged_build_does_not_write_beside_its_exe(as_nuitka, monkeypatch,
                                                        tmp_path):
    """The measured failure, stated as the thing that must not happen.

    Program Files is read-only to a normal user, so data_root() landing there is not
    "the wrong folder" — it is an app that cannot save anything.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr("sys.executable", str(tmp_path / "install" / "python.exe"))
    assert paths.data_root() != paths.app_root()


def test_running_from_source_keeps_data_in_the_project(monkeypatch, tmp_path):
    """Unchanged on purpose: macros stay next to the code while developing."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert paths.data_root() == paths.app_root()


def test_appdata_missing_falls_back_rather_than_crashing(as_nuitka, monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    assert paths.data_root() == paths.app_root()


def test_the_migration_is_dead_from_source_and_live_in_a_build(monkeypatch, tmp_path):
    """It is what recovers data left beside the exe by the builds that were broken."""
    calls = []
    monkeypatch.setattr(paths, "_migrate_dir", lambda src, dst: calls.append(src))
    monkeypatch.setenv("APPDATA", str(tmp_path))

    paths.migrate_legacy_data()
    assert calls == [], "from source there is nothing to migrate"

    monkeypatch.setitem(paths.__dict__, "__compiled__", True)
    paths.migrate_legacy_data()
    assert calls, "a packaged build must look for data left by an older layout"
