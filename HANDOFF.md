# Project Handoff / Status

Snapshot of where this project stands and how to continue — so a fresh machine
(or a fresh Claude session) has full context from a `git pull`.

_Last updated: 2026-07-11._

## What this project is

**YuhunBot** — a commercial, freemium automation bot for the game **Onmyoji**
(NetEase, Steam), built on the generic `window-macro-bot` engine. Sold as a
paid product with a free tier.

- **Target game:** Onmyoji (turn-based shikigami/gacha collector). Chosen because
  botting demand is high, our image-recognition method already works on it, and
  competition is only unpolished free scripts. Full research: `marketing/TARGET-GAMES.md`.
- **Brand:** "YuhunBot" (keeps NetEase's "Onmyoji" trademark out of the product name).
- **Pricing:** $6/month or $35 lifetime (SEA-friendly; audience is SEA/VN/CN/JP).
- **Monetization stack:** KeyAuth (licensing), Sellix + crypto (payments — mainstream
  processors ban this category), Discord (community). Full playbook: `GO-COMMERCIAL.md`.
- **Expansion after launch:** Summoners War (closest sibling), then Onmyoji variants.

## Current status: launch-ready (software side)

8 features merged to `main`; 65 tests passing (`python -m pytest tests/`):

1. Freemium licensing (KeyAuth + HWID + HMAC-signed offline cache), enforced in the engine
2. Template Library manager (rename/delete/usage/orphans)
3. Onmyoji branding (YuhunBot) + filled marketing/legal copy
4. Macro packs — export/import shareable `.wmbpack` presets
5. Onmyoji activity pack + `stop` action
6. Guided Capture wizard (finish a pack by clicking through)
7. Bundled packs into the build + first-run seeding of starter macros
8. Hardened Onmyoji pack — resilient priority-poll with anti-ban CAPTCHA stop

## Where things live

| Area | Path |
|------|------|
| Licensing / entitlements | `engine/licensing.py`, `engine/entitlements.py`, `engine/product_config.py` |
| Macro packs | `engine/pack_store.py`, `packs/` |
| Onmyoji pack | `packs/onmyoji/` (macros + `templates.spec.json` + `CAPTURE-GUIDE.md`) |
| Guided capture | `gui/capture_wizard.py` |
| Commercial playbook | `GO-COMMERCIAL.md` |
| Market research | `marketing/TARGET-GAMES.md` |
| Marketing copy | `marketing/` (landing.html, store-listing.md, discord-announcement.md) |
| Legal templates | `legal/` (EULA, refund, privacy) |

## Remaining work (all owner tasks — not code)

1. **Capture the 14 Onmyoji templates** on the game (use Images → Guided capture… → `packs/onmyoji/templates.spec.json`). Capture `onmyoji_captcha.png` carefully — it's the anti-ban guard.
2. Test a macro against live Onmyoji; report any misbehavior for tuning.
3. Create accounts: **KeyAuth** → **Sellix** + crypto → **Discord**.
4. Add **GitHub repo secrets** (see GO-COMMERCIAL.md § Step 4).
5. `git tag v1.0.0 && git push origin v1.0.0` → CI builds the release.
6. Optional: code-signing certificate.

## Setting up on a new machine

```bash
pip install -r requirements-dev.txt      # runtime + test deps
python -m pytest tests/                   # sanity check (should be 65 passing)
python main.py                            # run the app
gh auth login                             # if using gh for PRs
```

- **Build secrets:** `engine/_build_config.py` is git-ignored and NOT in the repo.
  It's generated in CI from GitHub secrets at release time. For local Pro testing,
  copy `engine/_build_config.example.py` → `engine/_build_config.py` and fill in
  KeyAuth values, or set `WMB_DEV_TIER=pro` when running from source.
- **Captured templates** live in `%APPDATA%/WindowMacroBotData/templates/` — they are
  per-machine and do NOT transfer with git. Re-capture (or copy that folder over).

## Note on Claude context

Claude's auto-memory lives under `~/.claude/projects/.../memory/` on the old
machine — it does **not** travel with `git pull`. This file (plus `GO-COMMERCIAL.md`,
`marketing/TARGET-GAMES.md`, and the commit history) is the durable context. To
resume with Claude on the new machine, point it at this file first.
