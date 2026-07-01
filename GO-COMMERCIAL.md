# Going Commercial — Operator Guide

This document is for **you, the owner**. The code side of turning Window Macro
Bot into a paid product is already built and tested. What remains are the things
only a human with accounts and money can do: create a license server account,
set up payments, and ship.

Read top to bottom once, then work the **Action Checklist**.

---

## 1. What is already built (code — done)

| Piece | File | What it does |
|-------|------|--------------|
| Tier model + feature gates | `engine/entitlements.py` | Single source of truth for what Free vs Pro can do |
| License manager | `engine/licensing.py` | Validates keys against KeyAuth, locks to the machine, caches offline (HMAC-signed) |
| Product config | `engine/product_config.py` | One place for store URL, KeyAuth creds, secrets |
| Engine enforcement | `engine/macro_engine.py` | Refuses to run/save locked features regardless of the UI |
| License/upgrade dialog | `gui/license_dialog.py` | Activate a key, "Get Pro", "Community" buttons |
| App wiring | `gui/app.py` | FREE/PRO badge in the header, upgrade prompts |
| Tests | `tests/` | 26 tests, 85% coverage on the licensing/gating logic |

### The Free → Pro split (this is what you're selling)

| | Free | **Pro** |
|---|------|---------|
| Macros | up to **2** | **unlimited** |
| Basic input (click, drag, type, key, scroll, wait) | ✅ | ✅ |
| **Background mode** (run while you use the PC / no cursor steal) | ❌ | ✅ |
| **Image / pixel / rectangle detection** (auto-farming) | ❌ | ✅ |
| **Loop mode** | ❌ | ✅ |
| **Multi-window parallel** (multi-accounting) | ❌ | ✅ |

The free user can still *build* a Pro macro in the editor — they just get an
"Upgrade to Pro" prompt when they try to **run** it. That is the highest-
converting freemium pattern: let them feel the value, charge for the payoff.

To change where the line sits, edit the `_FREE` / `_PRO` objects in
`engine/entitlements.py`. Nothing else needs to change.

---

## 2. Action Checklist (your to-do list, in order)

### ☐ Step 1 — Create your license server (KeyAuth, free)

KeyAuth is the standard licensing system for this niche. It does the key
generation, machine-locking, expiry, and remote kill-switch for you.

1. Sign up at **https://keyauth.cc**.
2. Create an **Application**. Open its settings and copy four values:
   - **App name**
   - **Owner ID**
   - **App secret**
   - **Version** (start at `1.0`)
3. In the app, create at least one **license key** to test with. You can make
   keys with durations (e.g. 30-day, lifetime) — this is how you'll sell
   subscriptions vs one-time.

> KeyAuth's App name and Owner ID are *not* secrets (every client app exposes
> them); the App secret is for response verification. Keep the App secret out of
> public places anyway — Step 4 keeps all of this out of your git repo.

### ☐ Step 2 — Set up payments (sell the keys)

Mainstream processors (Stripe, PayPal, Paddle, LemonSqueezy) **prohibit game
automation/cheat software** and will freeze your account. Use what this niche
uses:

- **Sellix** (https://sellix.io) or **SellApp** — digital-goods checkout that
  supports crypto and (sometimes) cards, and can **auto-deliver a KeyAuth license
  key** on purchase via webhook/integration.
- **Crypto** (NOWPayments, Coinbase Commerce) — your most durable rail; low
  freeze risk.

Recommended starting setup: **Sellix product → on payment, deliver a KeyAuth
key**. Sellix has a KeyAuth integration so the buyer is emailed a working key
automatically. Put your Sellix product link in `PURCHASE_URL` (Step 4).

### ☐ Step 3 — Pick your price (recommendation below)

You chose **freemium → paid**. Recommended launch pricing:

| Plan | Price | Notes |
|------|-------|-------|
| Free | $0 | 2 macros, foreground only — the funnel |
| **Pro monthly** | **$8–12 / mo** | recurring, best revenue; use KeyAuth 30-day keys |
| **Pro lifetime** | **$40–60 one-time** | converts the "I hate subscriptions" crowd |

Start at the low end, raise once you have testimonials. Sell *one specific game/
use-case* ("the X farming bot") rather than "a generic macro tool" — it converts
far better.

### ☐ Step 4 — Put your secrets into the build (no git commit)

Your live values must be **compiled into the `.exe`** (a customer's PC has no
environment variables). The release pipeline does this for you from **GitHub
repository secrets**.

In your GitHub repo → **Settings → Secrets and variables → Actions → New
repository secret**, add:

| Secret name | Value |
|-------------|-------|
| `KEYAUTH_APP_NAME` | from Step 1 |
| `KEYAUTH_OWNER_ID` | from Step 1 |
| `KEYAUTH_VERSION` | `1.0` |
| `PURCHASE_URL` | your Sellix product link |
| `SUPPORT_URL` | your Discord invite |
| `CACHE_HMAC_SECRET` | a long random string — generate with: `python -c "import secrets; print(secrets.token_hex(32))"` |

The workflow (`.github/workflows/release.yml`) writes these into
`engine/_build_config.py` at build time, which is git-ignored, so they never
land in your source. The build **fails on purpose** if you configure KeyAuth but
forget `CACHE_HMAC_SECRET`, so you can't accidentally ship a forgeable license
cache.

> The KeyAuth **App secret** is intentionally *not* in this list — it's a
> seller-side credential the client never sends, so compiling it into the `.exe`
> would only expose it for no benefit.

### ☐ Step 5 — Build and release

```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions runs the tests, injects your secrets, compiles with Nuitka, and
publishes a release zip. Download it and confirm the FREE/PRO badge appears and
your test key from Step 1 activates.

### ☐ Step 6 — Code signing (recommended, costs money)

Automation tools trip Windows SmartScreen and antivirus. A signing certificate
greatly reduces "Unknown publisher" scares.

- Buy an **OV code-signing certificate** (~$200–400/yr) from a reseller
  (SSL.com, Sectigo, etc.). Note: some CAs decline game-automation software.
- Sign `WindowMacroBot.exe` with `signtool` before zipping (add a signing step
  to the workflow once you have the cert).
- Even unsigned, **Nuitka compiles to C**, which is much harder to crack than a
  normal PyInstaller build — you already have a real anti-piracy advantage.

### ☐ Step 7 — Distribution & marketing

- **Discord server** — this niche lives on Discord. It's your storefront,
  support desk, and community. Put the invite in `SUPPORT_URL`.
- **YouTube demo** showing the bot running hands-free = your #1 conversion tool.
- A simple landing page with the free download + the Sellix "Buy Pro" button.
- Post in the specific game's communities/forums.

### ☐ Step 8 — Legal posture (do not skip)

- Operate through a **business entity**, not your personal name.
- Ship a short **EULA** that disclaims liability for game bans and gives **no
  refunds after a key is delivered**.
- Be aware: game publishers have sued bot/cheat sellers. Avoid titles whose
  publishers actively litigate, and never target games with kernel anti-cheat
  (Vanguard, EAC, BattlEye) — this tool's PostMessage input can't beat them and
  will get users banned.

---

## 3. How to test Pro on your own machine (before selling)

**Fastest — zero setup (developer override, source only):**

```bash
# Windows PowerShell
$env:WMB_DEV_TIER = "pro"; python main.py
```

This forces Pro while running from source so you can try every feature without a
key. It is **ignored in the packaged .exe** (`sys.frozen` is true there), so it
can never be used as a bypass by customers — it only works on a dev checkout,
where you already have the full source anyway.

**Realistic — end-to-end with a real key:**

1. Copy `engine/_build_config.example.py` to `engine/_build_config.py` and fill
   in your KeyAuth values (this file is git-ignored).
2. Run from source: `python main.py`.
3. Click the **FREE · Upgrade** badge in the header → paste a license key from
   KeyAuth → **Activate**. The badge flips to **PRO**.

To give yourself or a tester permanent Pro in a real build, generate a
**lifetime license key** in your KeyAuth dashboard and activate it — the proper,
revocable way (never a hardcoded key in the binary).

To simulate "license revoked", ban/delete the key in KeyAuth — within the
re-validation interval the app drops back to Free.

---

## 4. How the licensing works (reference)

- **Activation**: user pastes a key → validated against KeyAuth, locked to the
  machine's hardware ID.
- **Offline grace**: a successful check is cached in `%APPDATA%/
  WindowMacroBotData/license.json`, **HMAC-signed**. Hand-editing the file to
  fake Pro fails the signature check and is ignored. The cache only lets a
  *paying* user keep working for `OFFLINE_GRACE_DAYS` (default 3) without
  internet.
- **Re-validation**: while open, the app re-checks the server every
  `REVALIDATE_INTERVAL_HOURS` (default 12). If the server rejects the key
  (expired/banned), Pro is revoked immediately.
- **Enforcement is in the engine**, not just the UI — locked features are
  refused in `MacroEngine.run/run_folder/save_macro`, so a patched UI can't
  unlock them.

### Honest limitations

No client-side license system is uncrackable; a determined attacker who unpacks
the binary can find the embedded secret. The realistic goal — which this
achieves — is to stop casual sharing/file-editing and to make Pro inconvenient
enough to crack that most users just pay. The server (KeyAuth) is always the
authority, so you can revoke leaked keys.

---

## 5. Quick reference — tune the product

| Want to change… | Edit |
|-----------------|------|
| What Free vs Pro can do | `engine/entitlements.py` (`_FREE` / `_PRO`) |
| Store / Discord links, KeyAuth creds | repo secrets (Step 4) or `engine/_build_config.py` |
| Offline grace / re-check interval | `WMB_OFFLINE_GRACE_DAYS`, `WMB_REVALIDATE_HOURS` |
| Run the tests | `pip install -r requirements-dev.txt && python -m pytest tests/` |
