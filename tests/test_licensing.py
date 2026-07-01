"""Unit tests for license activation, the signed cache, and re-validation."""

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

from engine.entitlements import Tier
from engine.licensing import LicenseManager, ValidationResult, hardware_id

pytestmark = pytest.mark.unit


class FakeBackend:
    """A controllable stand-in for KeyAuth."""

    def __init__(self, result: ValidationResult):
        self.result = result
        self.calls = 0

    def validate(self, key: str, hwid: str) -> ValidationResult:
        self.calls += 1
        return self.result


def _ok(expiry=None) -> ValidationResult:
    return ValidationResult(ok=True, tier=Tier.PRO, message="ok", expiry_iso=expiry)


def _reject() -> ValidationResult:
    return ValidationResult(
        ok=False, tier=Tier.FREE, message="invalid", rejected=True
    )


def _network_error() -> ValidationResult:
    return ValidationResult(ok=False, tier=Tier.FREE, message="offline")


# ── hardware id ───────────────────────────────────────────────────────────────


def test_hardware_id_is_stable_hex():
    a, b = hardware_id(), hardware_id()
    assert a == b
    assert len(a) == 64
    int(a, 16)  # raises if not hex


# ── activation ────────────────────────────────────────────────────────────────


def test_activate_success_unlocks_pro_and_writes_cache(tmp_path):
    cache = tmp_path / "license.json"
    mgr = LicenseManager(backend=FakeBackend(_ok()), cache_path=cache)
    ok, _ = mgr.activate("KEY-123")
    assert ok
    assert mgr.is_pro()
    assert cache.exists()


def test_activate_empty_key_rejected(tmp_path):
    mgr = LicenseManager(backend=FakeBackend(_ok()), cache_path=tmp_path / "l.json")
    ok, _ = mgr.activate("   ")
    assert not ok
    assert not mgr.is_pro()


def test_activate_failure_stays_free(tmp_path):
    mgr = LicenseManager(
        backend=FakeBackend(_reject()), cache_path=tmp_path / "l.json"
    )
    ok, _ = mgr.activate("BAD")
    assert not ok
    assert mgr.tier() == Tier.FREE


def test_deactivate_clears_pro_and_cache(tmp_path):
    cache = tmp_path / "license.json"
    mgr = LicenseManager(backend=FakeBackend(_ok()), cache_path=cache)
    mgr.activate("KEY")
    mgr.deactivate()
    assert not mgr.is_pro()
    assert not cache.exists()


# ── signed cache ──────────────────────────────────────────────────────────────


def test_valid_cache_grants_pro_on_fresh_manager(tmp_path):
    cache = tmp_path / "license.json"
    LicenseManager(backend=FakeBackend(_ok()), cache_path=cache).activate("KEY")

    # A new manager whose backend would reject still trusts the signed cache
    # (offline grace) until it re-validates.
    fresh = LicenseManager(backend=FakeBackend(_reject()), cache_path=cache)
    fresh._load_from_cache()
    assert fresh.is_pro()


def test_tampered_cache_is_ignored(tmp_path):
    cache = tmp_path / "license.json"
    LicenseManager(backend=FakeBackend(_ok()), cache_path=cache).activate("KEY")

    blob = json.loads(cache.read_text(encoding="utf-8"))
    blob["payload"]["key"] = "HACKED"  # change payload, leave signature stale
    cache.write_text(json.dumps(blob), encoding="utf-8")

    fresh = LicenseManager(backend=FakeBackend(_reject()), cache_path=cache)
    fresh._load_from_cache()
    assert not fresh.is_pro()  # signature mismatch → cache discarded


def test_offline_grace_expiry_downgrades(tmp_path):
    cache = tmp_path / "license.json"
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    LicenseManager(
        backend=FakeBackend(_ok()), cache_path=cache, now_fn=lambda: base
    ).activate("KEY")

    later = base + timedelta(days=99)  # far beyond the grace window
    fresh = LicenseManager(
        backend=FakeBackend(_reject()), cache_path=cache, now_fn=lambda: later
    )
    fresh._load_from_cache()
    assert not fresh.is_pro()


# ── re-validation ─────────────────────────────────────────────────────────────


def test_revalidation_revokes_on_server_reject(tmp_path):
    cache = tmp_path / "license.json"
    backend = FakeBackend(_ok())
    mgr = LicenseManager(backend=backend, cache_path=cache)
    mgr.activate("KEY")
    assert mgr.is_pro()

    backend.result = _reject()  # server now rejects the key
    mgr._revalidate_once()
    assert not mgr.is_pro()
    assert not cache.exists()


def test_revalidation_keeps_pro_on_network_error(tmp_path):
    cache = tmp_path / "license.json"
    backend = FakeBackend(_ok())
    mgr = LicenseManager(backend=backend, cache_path=cache)
    mgr.activate("KEY")

    backend.result = _network_error()  # transient failure, not a rejection
    mgr._revalidate_once()
    assert mgr.is_pro()  # offline grace preserved


# ── status snapshot ───────────────────────────────────────────────────────────


def test_status_masks_key_and_reports_tier(tmp_path):
    mgr = LicenseManager(backend=FakeBackend(_ok()), cache_path=tmp_path / "l.json")
    assert mgr.status()["tier"] == "free"

    mgr.activate("ABCD-EFGH-IJKL")
    snap = mgr.status()
    assert snap["tier"] == "pro"
    assert "…" in (snap["key"] or "")  # key is masked, not shown in full
    assert len(snap["hwid"]) == 16


# ── KeyAuth backend (network mocked) ──────────────────────────────────────────


class _FakeResp:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _mock_urlopen(monkeypatch, responses):
    from engine import licensing

    state = {"i": 0}

    def fake(req, timeout=None):
        payload = responses[min(state["i"], len(responses) - 1)]
        state["i"] += 1
        if isinstance(payload, Exception):
            raise payload
        return _FakeResp(payload)

    monkeypatch.setattr(licensing.urllib.request, "urlopen", fake)


def test_keyauth_validate_success(monkeypatch):
    from engine import licensing

    _mock_urlopen(
        monkeypatch,
        [
            {"success": True, "sessionid": "sid"},
            {
                "success": True,
                "message": "Logged in!",
                "info": {"subscriptions": [{"expiry": "1893456000"}]},
            },
        ],
    )
    result = licensing.KeyAuthBackend().validate("KEY", "HWID")
    assert result.ok
    assert result.tier == Tier.PRO
    assert result.expiry_iso is not None


def test_keyauth_validate_rejected(monkeypatch):
    from engine import licensing

    _mock_urlopen(
        monkeypatch,
        [
            {"success": True, "sessionid": "sid"},
            {"success": False, "message": "Invalid license key"},
        ],
    )
    result = licensing.KeyAuthBackend().validate("BAD", "HWID")
    assert not result.ok
    assert result.rejected


def test_keyauth_network_error_is_not_a_rejection(monkeypatch):
    from engine import licensing

    _mock_urlopen(monkeypatch, [OSError("no network")])
    result = licensing.KeyAuthBackend().validate("KEY", "HWID")
    assert not result.ok
    assert not result.rejected  # transient → caller keeps offline grace


# ── on_change callback ────────────────────────────────────────────────────────


def test_on_change_fires_when_tier_changes(tmp_path):
    calls = {"n": 0}
    mgr = LicenseManager(
        backend=FakeBackend(_ok()),
        cache_path=tmp_path / "l.json",
        on_change=lambda: calls.__setitem__("n", calls["n"] + 1),
    )
    mgr.activate("KEY")  # FREE -> PRO
    assert calls["n"] == 1


def test_on_change_silent_when_tier_unchanged(tmp_path):
    calls = {"n": 0}
    mgr = LicenseManager(
        backend=FakeBackend(_reject()),
        cache_path=tmp_path / "l.json",
        on_change=lambda: calls.__setitem__("n", calls["n"] + 1),
    )
    mgr.activate("BAD")  # stays FREE -> no callback
    assert calls["n"] == 0


def test_on_change_exception_does_not_break_activation(tmp_path):
    def boom():
        raise RuntimeError("ui blew up")

    mgr = LicenseManager(
        backend=FakeBackend(_ok()), cache_path=tmp_path / "l.json", on_change=boom
    )
    ok, _ = mgr.activate("KEY")
    assert ok and mgr.is_pro()  # licensing survives a bad UI callback


# ── developer tier override (source-only) ─────────────────────────────────────


def test_dev_override_forces_pro_from_source(tmp_path, monkeypatch):
    monkeypatch.setenv("WMB_DEV_TIER", "pro")
    mgr = LicenseManager(backend=FakeBackend(_reject()), cache_path=tmp_path / "l.json")
    assert mgr.tier() == Tier.PRO  # unlocked without any key, running from source


def test_dev_override_ignored_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("WMB_DEV_TIER", raising=False)
    mgr = LicenseManager(backend=FakeBackend(_reject()), cache_path=tmp_path / "l.json")
    assert mgr.tier() == Tier.FREE


def test_dev_override_disabled_in_packaged_build(tmp_path, monkeypatch):
    # Simulate a frozen (Nuitka/PyInstaller) build: the override must NOT apply,
    # so it can never act as a bypass in the shipped .exe.
    monkeypatch.setenv("WMB_DEV_TIER", "pro")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    mgr = LicenseManager(backend=FakeBackend(_reject()), cache_path=tmp_path / "l.json")
    assert mgr.tier() == Tier.FREE
