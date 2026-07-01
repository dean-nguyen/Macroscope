"""
License management — the source of truth for a user's tier.

Responsibilities
    * Compute a stable, per-machine hardware id (HWID) for license locking.
    * Validate a license key against the configured backend (KeyAuth by
      default) and report the resulting tier.
    * Cache the validated result in an HMAC-signed file so a paying user can
      keep working briefly offline, while hand-editing the file cannot grant
      Pro (the signature check fails and the cache is ignored).

Design notes
    * The backend is injected, so tests can use a fake and the production code
      can swap KeyAuth for a self-hosted server later without touching callers.
    * Network calls use only the Python standard library (urllib) so the
      Nuitka build needs no extra packages.
    * The server is always the authority. The local cache only buys an offline
      grace window; once that window lapses we fall back to FREE until the
      server confirms the license again.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol

from engine import product_config as cfg
from engine.entitlements import Tier
from engine.paths import LICENSE_FILE

log = logging.getLogger(__name__)


# ── result type ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of a backend validation call."""

    ok: bool
    tier: Tier
    message: str
    expiry_iso: Optional[str] = None
    # True only when the server explicitly rejected the key (invalid/expired/
    # banned), as opposed to a transient network problem. Used to decide
    # whether to downgrade or keep the offline grace.
    rejected: bool = False


# ── hardware id ───────────────────────────────────────────────────────────────


def _dev_tier_override() -> Optional[Tier]:
    """Developer-only tier override, active ONLY when running from source.

    Set ``WMB_DEV_TIER=pro`` (or ``free``) to force a tier while developing or
    testing, so you can exercise Pro features without a license key.

    This is disabled in packaged builds (``sys.frozen`` is True), so it can
    never act as a bypass in the shipped .exe. Running from source already means
    having the full source, so this adds no attack surface to the product.
    """
    if getattr(sys, "frozen", False):
        return None
    value = os.environ.get("WMB_DEV_TIER", "").strip().lower()
    if value == "pro":
        return Tier.PRO
    if value == "free":
        return Tier.FREE
    return None


def hardware_id() -> str:
    """Return a stable SHA-256 fingerprint of this machine."""
    parts = []
    try:  # Windows MachineGuid — stable across reboots and app updates.
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        ) as key:
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            parts.append(str(guid))
    except Exception:  # noqa: BLE001 - best-effort, fall through to uuid
        pass

    import uuid

    parts.append(str(uuid.getnode()))  # NIC-derived node id
    raw = "|".join(p for p in parts if p) or "unknown-host"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── backends ──────────────────────────────────────────────────────────────────


class LicenseBackend(Protocol):
    """Validates a license key for a machine."""

    def validate(self, key: str, hwid: str) -> ValidationResult: ...


class OfflineBackend:
    """No-op backend used when no licensing provider is configured."""

    def validate(self, key: str, hwid: str) -> ValidationResult:
        return ValidationResult(
            ok=False,
            tier=Tier.FREE,
            message="Licensing is not configured for this build.",
        )


class KeyAuthBackend:
    """Validates keys against a KeyAuth application (https://keyauth.cc)."""

    def __init__(self, timeout_s: float = cfg.NETWORK_TIMEOUT_S) -> None:
        self._timeout = timeout_s

    def validate(self, key: str, hwid: str) -> ValidationResult:
        session = self._init_session()
        if session is None:
            return ValidationResult(
                ok=False, tier=Tier.FREE,
                message="Could not reach the license server. Check your "
                        "internet connection and try again.",
            )
        return self._validate_license(key, hwid, session)

    # -- internal --

    def _init_session(self) -> Optional[str]:
        body = {
            "type": "init",
            "ver": cfg.KEYAUTH_VERSION,
            "name": cfg.KEYAUTH_APP_NAME,
            "ownerid": cfg.KEYAUTH_OWNER_ID,
        }
        data = self._post(body)
        if data and data.get("success"):
            return data.get("sessionid", "")
        return None

    def _validate_license(
        self, key: str, hwid: str, session: str
    ) -> ValidationResult:
        body = {
            "type": "license",
            "key": key,
            "hwid": hwid,
            "sessionid": session,
            "name": cfg.KEYAUTH_APP_NAME,
            "ownerid": cfg.KEYAUTH_OWNER_ID,
        }
        data = self._post(body)
        if data is None:
            return ValidationResult(
                ok=False, tier=Tier.FREE,
                message="License server did not respond.",
            )
        if data.get("success"):
            return ValidationResult(
                ok=True, tier=Tier.PRO,
                message=data.get("message", "License activated."),
                expiry_iso=_extract_expiry(data),
            )
        # An explicit failure response = the key was rejected.
        return ValidationResult(
            ok=False, tier=Tier.FREE,
            message=data.get("message", "Invalid or expired license key."),
            rejected=True,
        )

    def _post(self, body: Dict[str, str]) -> Optional[Dict]:
        try:
            encoded = urllib.parse.urlencode(body).encode("utf-8")
            req = urllib.request.Request(
                cfg.KEYAUTH_API_URL,
                data=encoded,
                headers={"User-Agent": "WindowMacroBot"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - network/parse errors are non-fatal
            log.warning("KeyAuth request failed: %s", exc)
            return None


def _extract_expiry(data: Dict) -> Optional[str]:
    """Pull the subscription expiry (unix → iso) from a KeyAuth response."""
    try:
        subs = data.get("info", {}).get("subscriptions", [])
        if subs:
            ts = int(subs[0].get("expiry"))
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:  # noqa: BLE001
        pass
    return None


def _default_backend() -> LicenseBackend:
    return KeyAuthBackend() if cfg.keyauth_configured() else OfflineBackend()


# ── signed cache ──────────────────────────────────────────────────────────────


def _sign(payload: Dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        cfg.CACHE_HMAC_SECRET.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _read_cache(path: Path, hwid: str) -> Optional[Dict]:
    """Read and verify the signed cache. Returns the payload or None."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            blob = json.load(fh)
        payload, sig = blob.get("payload"), blob.get("sig")
        if not isinstance(payload, dict) or not sig:
            return None
        if not hmac.compare_digest(sig, _sign(payload)):
            log.warning("License cache signature mismatch — ignoring.")
            return None
        if payload.get("hwid") != hwid:
            log.warning("License cache bound to a different machine — ignoring.")
            return None
        return payload
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not read license cache: %s", exc)
        return None


def _write_cache(path: Path, payload: Dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = {"payload": payload, "sig": _sign(payload)}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(blob, fh, indent=2)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not write license cache: %s", exc)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# ── manager ───────────────────────────────────────────────────────────────────


class LicenseManager:
    """Owns the current tier and the activation lifecycle."""

    def __init__(
        self,
        backend: Optional[LicenseBackend] = None,
        log_fn: Optional[Callable[[str], None]] = None,
        cache_path: Path = LICENSE_FILE,
        now_fn: Optional[Callable[[], datetime]] = None,
        on_change: Optional[Callable[[], None]] = None,
    ) -> None:
        self._backend = backend or _default_backend()
        self._log = log_fn or (lambda _msg: None)
        self._cache_path = cache_path
        self._now = now_fn or (lambda: datetime.now(timezone.utc))
        # Fired (best-effort) whenever the tier actually changes — including from
        # the background re-validation thread — so the UI can refresh.
        self._on_change = on_change
        self._hwid = hardware_id()

        self._lock = threading.Lock()
        self._tier = Tier.FREE
        self._key: Optional[str] = None
        self._expiry_iso: Optional[str] = None
        self._last_validated_iso: Optional[str] = None

        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None

    # -- public API --

    @property
    def hwid(self) -> str:
        return self._hwid

    def tier(self) -> Tier:
        override = _dev_tier_override()  # source-only; ignored in packaged builds
        if override is not None:
            return override
        with self._lock:
            return self._tier

    def is_pro(self) -> bool:
        return self.tier() == Tier.PRO

    def start(self) -> None:
        """Load the cached license and begin periodic background re-validation."""
        # Defence in depth: a production build (KeyAuth configured) must not ship
        # with the public placeholder cache secret, or anyone could forge a
        # signed Pro cache. The release pipeline also blocks this at build time.
        if cfg.keyauth_configured() and cfg.cache_secret_is_default():
            self._log(
                "[SECURITY] CACHE_HMAC_SECRET is still the default placeholder — "
                "the offline license cache is forgeable. Set a real secret "
                "before release (see GO-COMMERCIAL.md)."
            )
        self._load_from_cache()
        if self._key and cfg.keyauth_configured():
            self._worker = threading.Thread(
                target=self._revalidate_loop, daemon=True, name="license-check"
            )
            self._worker.start()

    def stop(self) -> None:
        self._stop.set()

    def activate(self, key: str) -> tuple[bool, str]:
        """Validate *key* now. On success, persist Pro; return (ok, message)."""
        key = (key or "").strip()
        if not key:
            return False, "Please enter a license key."
        result = self._backend.validate(key, self._hwid)
        if result.ok:
            self._apply(Tier.PRO, key, result.expiry_iso)
            self._log("License activated — Pro features unlocked.")
            return True, result.message or "License activated."
        return False, result.message

    def deactivate(self) -> None:
        """Remove the license from this machine (back to FREE)."""
        self._apply(Tier.FREE, None, None)
        try:
            self._cache_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        self._log("License removed from this machine.")

    def status(self) -> Dict[str, Optional[str]]:
        """A snapshot for the UI."""
        with self._lock:
            return {
                "tier": self._tier.value,
                "key": _mask(self._key),
                "expiry": self._expiry_iso,
                "hwid": self._hwid[:16],
                "configured": str(cfg.keyauth_configured()),
            }

    # -- internal --

    def _apply(
        self, tier: Tier, key: Optional[str], expiry_iso: Optional[str]
    ) -> None:
        now_iso = self._now().isoformat()
        with self._lock:
            changed = self._tier != tier
            self._tier = tier
            self._key = key
            self._expiry_iso = expiry_iso
            self._last_validated_iso = now_iso
        if tier == Tier.PRO and key:
            _write_cache(
                self._cache_path,
                {
                    "key": key,
                    "tier": tier.value,
                    "expiry": expiry_iso,
                    "hwid": self._hwid,
                    "last_validated": now_iso,
                },
            )
        if changed and self._on_change:
            try:
                self._on_change()
            except Exception:  # noqa: BLE001 - UI callback must never break licensing
                pass

    def _load_from_cache(self) -> None:
        payload = _read_cache(self._cache_path, self._hwid)
        if not payload or payload.get("tier") != Tier.PRO.value:
            return

        expiry = _parse_iso(payload.get("expiry"))
        if expiry and self._now() > expiry:
            self._log("License has expired.")
            return

        last = _parse_iso(payload.get("last_validated"))
        grace = timedelta(days=cfg.OFFLINE_GRACE_DAYS)
        within_grace = last is not None and (self._now() - last) <= grace

        # Always remember the key so background re-validation can restore Pro,
        # but only grant Pro immediately if the last check is within grace.
        with self._lock:
            self._key = payload.get("key")
            self._expiry_iso = payload.get("expiry")
            self._last_validated_iso = payload.get("last_validated")
            self._tier = Tier.PRO if within_grace else Tier.FREE
        if not within_grace:
            self._log("Offline grace expired — reconnecting to verify license.")

    def _revalidate_loop(self) -> None:
        interval = cfg.REVALIDATE_INTERVAL_HOURS * 3600
        # Verify once shortly after launch, then on the configured interval.
        while not self._stop.is_set():
            self._revalidate_once()
            self._stop.wait(timeout=interval)

    def _revalidate_once(self) -> None:
        with self._lock:
            key = self._key
        if not key:
            return
        result = self._backend.validate(key, self._hwid)
        if result.ok:
            self._apply(Tier.PRO, key, result.expiry_iso)
        elif result.rejected:
            # Server actively rejected — revoke locally.
            self._apply(Tier.FREE, None, None)
            try:
                self._cache_path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            self._log("License is no longer valid — Pro features locked.")
        # Transient network failure: keep the current tier (offline grace).


def _mask(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}…{key[-4:]}"
