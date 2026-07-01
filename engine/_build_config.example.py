"""
EXAMPLE build-time config.

Copy this to ``engine/_build_config.py`` (which is git-ignored) and fill in your
real values, OR let the GitHub Actions release workflow generate it from repo
secrets. Any value left out falls back to an environment variable and then to
the placeholder default in product_config.py.

See GO-COMMERCIAL.md for where each value comes from.
"""

# Storefront / community
PURCHASE_URL = "https://your-store.sellix.io/product/your-pro-key"
SUPPORT_URL = "https://discord.gg/your-invite"

# KeyAuth application (https://keyauth.cc → Applications)
# Note: the KeyAuth "App secret" is a seller-side credential and is NOT used by
# the client, so it is intentionally not listed here or compiled into the build.
KEYAUTH_APP_NAME = "your-app-name"
KEYAUTH_OWNER_ID = "your-owner-id"
KEYAUTH_VERSION = "1.0"

# A long random constant used to sign the local license cache. Generate once,
# keep it constant across releases. e.g. python -c "import secrets; print(secrets.token_hex(32))"
CACHE_HMAC_SECRET = "replace-with-64-hex-chars"
