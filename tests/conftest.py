"""Shared test setup.

The suite must not depend on the developer's environment. Several env vars exist
purely as local overrides (see GO-COMMERCIAL.md), and leaving one set silently
changes what the tests assert: with ``WMB_DEV_TIER=pro`` exported — the documented
way to try Pro features while running from source — six licensing tests fail,
because the manager reports Pro where the test expects Free. That reads as a
licensing regression when nothing is broken, and it means CI (a clean
environment) and a dev machine disagree about whether the suite passes.
"""

import pytest

# Local-override variables that must never reach a test unless the test itself
# sets one. Tests that exercise an override use monkeypatch, which runs after
# this fixture, so they are unaffected.
_DEV_OVERRIDES = (
    "WMB_DEV_TIER",
    "WMB_OFFLINE_GRACE_DAYS",
    "WMB_REVALIDATE_HOURS",
)


@pytest.fixture(autouse=True)
def _isolate_dev_env(monkeypatch):
    for name in _DEV_OVERRIDES:
        monkeypatch.delenv(name, raising=False)
