"""
Product / commercial configuration — the single place to set everything that
turns this build into a sellable product.

Values resolve in this order (first hit wins):

    1. ``engine/_build_config.py``  — generated at build time from CI secrets.
       This file is git-ignored, so real credentials never live in the repo
       yet still get compiled into the shipped .exe. See GO-COMMERCIAL.md.
    2. environment variables          — handy for local development.
    3. the safe placeholder defaults below.

While the KeyAuth values are blank the app runs in FREE mode for everyone (no
licensing calls made), which is the correct, safe default for an unconfigured
build.
"""

from __future__ import annotations

import os

# Optional generated module written by the release pipeline (git-ignored).
try:  # pragma: no cover - presence depends on the build environment
    from engine import _build_config as _bc  # type: ignore
except Exception:  # noqa: BLE001
    _bc = None


def _resolve(attr: str, env: str, default: str) -> str:
    """Resolve a config value: build constant → env var → default."""
    if _bc is not None and getattr(_bc, attr, None):
        return str(getattr(_bc, attr))
    return os.environ.get(env, default)


# ── Identity ────────────────────────────────────────────────────────────────
PRODUCT_NAME: str = _resolve("PRODUCT_NAME", "WMB_PRODUCT_NAME", "Window Macro Bot")
VERSION: str = _resolve("VERSION", "WMB_VERSION", "1.0.0")

# Where the "Get Pro" / "Buy" buttons send the user. Use your Sellix / SellApp /
# crypto checkout link. TODO: replace before release.
PURCHASE_URL: str = _resolve("PURCHASE_URL", "WMB_PURCHASE_URL",
                             "https://example.sellix.io/")

# Community / support hub (Discord is the norm in this niche). TODO: replace.
SUPPORT_URL: str = _resolve("SUPPORT_URL", "WMB_SUPPORT_URL",
                            "https://discord.gg/your-invite")

# ── KeyAuth (https://keyauth.cc) ──────────────────────────────────────────────
# Create a free account → create an Application → copy these values in.
# Leave blank to ship a build that is FREE-only (no licensing calls made).
# (The KeyAuth "App secret" is a seller-side credential and is NOT sent by the
# client, so it is deliberately not compiled into the binary.)
KEYAUTH_APP_NAME: str = _resolve("KEYAUTH_APP_NAME", "WMB_KEYAUTH_APP", "")
KEYAUTH_OWNER_ID: str = _resolve("KEYAUTH_OWNER_ID", "WMB_KEYAUTH_OWNER", "")
KEYAUTH_VERSION: str = _resolve("KEYAUTH_VERSION", "WMB_KEYAUTH_VERSION", "1.0")
KEYAUTH_API_URL: str = _resolve("KEYAUTH_API_URL", "WMB_KEYAUTH_API",
                                "https://keyauth.win/api/1.3/")

# ── Local cache hardening ─────────────────────────────────────────────────────
# Used to HMAC-sign the offline license cache so a user cannot grant themselves
# Pro by hand-editing license.json. Set this to a long random string before
# release; it only has to stay constant across versions. TODO: replace.
_DEFAULT_CACHE_SECRET = "change-this-to-a-long-random-string-before-release"
CACHE_HMAC_SECRET: str = _resolve(
    "CACHE_HMAC_SECRET", "WMB_CACHE_SECRET", _DEFAULT_CACHE_SECRET
)

# How long a previously-validated Pro license keeps working with no internet,
# and how often we re-check the server while the app is open.
OFFLINE_GRACE_DAYS: int = int(os.environ.get("WMB_OFFLINE_GRACE_DAYS", "3"))
REVALIDATE_INTERVAL_HOURS: int = int(os.environ.get("WMB_REVALIDATE_HOURS", "12"))

# Network timeout for licensing calls (seconds).
NETWORK_TIMEOUT_S: float = float(os.environ.get("WMB_NETWORK_TIMEOUT", "10"))


def keyauth_configured() -> bool:
    """True when the minimum KeyAuth credentials are present."""
    return bool(KEYAUTH_APP_NAME and KEYAUTH_OWNER_ID)


def cache_secret_is_default() -> bool:
    """True when the offline-cache signing key is still the public placeholder."""
    return CACHE_HMAC_SECRET == _DEFAULT_CACHE_SECRET
