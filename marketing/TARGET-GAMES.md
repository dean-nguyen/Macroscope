# Target Games — Research & Strategy

Market research anchoring the product to **Onmyoji** (NetEase, Steam) and ranking
expansion targets. Goal set by owner: *easiest wins first* — games where the
existing macros and approach transfer with least effort/risk.

_Last researched: 2026-07 (July 2026)._

---

## TL;DR

- **Launch product = "the Onmyoji bot" (YuhunBot).** It's the lowest-risk,
  highest-certainty win: the tool already runs on Onmyoji, demand is huge, and
  the only competition is unpolished free scripts.
- **Then expand to Summoners War** (the closest paying sibling) via a preset pack.
- **Avoid** action gacha with anti-cheat (Genshin/HSR/Wuthering Waves) and
  ban-happy publishers (Epic Seven for main accounts).

---

## Why Onmyoji is the right base

- **Proven demand.** Onmyoji's grind (御魂/Yuhun soul farming, EXP, awakening,
  exploration) is punishing and repetitive — exactly what players automate.
  There's a whole GitHub `onmyoji` bot topic and an active SEA/VN scene.
- **Method validated.** The leading bots — `runhey/OnmyojiAutoScript`,
  `AymaxLi/auto-onmyoji` — are image-recognition + click bots on the Steam/Nox
  client. **Same technique as our engine.** No kernel anti-cheat wall.
- **Weak, fragmented competition.** Existing tools are free GitHub projects
  (dev setup required) and clunky community tools. **Nobody ships a polished,
  no-setup, freemium product with licensing, template management, multi-account,
  and support.** That's the gap.
- **Audience advantage.** Onmyoji is biggest in CN / JP / SEA (incl. Vietnam).
  Western bot-sellers barely touch it — room to market in-language to a
  community we understand. Consider local payment rails alongside Sellix/crypto.

### How to beat the free tools (the whole game)
Free scripts cap pricing, so win on what they don't do:
1. **No setup** — download, pick a preset, run.
2. **Reliability + anti-ban** — randomized timing/clicks.
3. **Multi-account / multi-instance** (our Pro multi-window feature).
4. **Stays updated** when NetEase patches the UI (free tools rot — big converter).
5. **Support + community** (Discord).

Freemium fit: **Free** = basic Yuhun farming (matches free tools).
**Pro** = all dungeons + multi-account + scheduling + updates.

---

## Expansion ranking (after Onmyoji)

Same "auto-battle → repeat dungeon for gear/mats" loop, so macros transfer:

| Rank | Game | Why | Risk / note |
|------|------|-----|-------------|
| 1 | **Summoners War** | Closest mechanical twin (repeat dungeons 24/7 for runes). Proven **paid** market — scripts sold with "24/7 autoplay + captcha solve". | Saturated; Com2uS captcha/anti-bot |
| 2 | **Onmyoji regional variants** (CN 阴阳师, JP, Yokai Koya) | Same engine, new servers/audiences | Same publisher bans |
| 3 | **Epic Seven** | Turn-based gear farming | Smilegate bans hard — alt accounts only |
| 4 | **Idle hero-collectors** (AFK Journey, Idle Heroes, Hero Wars) | Huge, botting-tolerant, easy loops | Lots of free competition |

### High-potential, different loop
- **Reroll-as-a-service** (esp. Pokémon TCG Pocket) — booming; account resale
  economy means high willingness to pay (a reroll tool sells for $100). Requires
  a dedicated "reroll mode" but monetizes better than pure farming.

---

## Avoid
- **Genshin Impact / Honkai: Star Rail / Wuthering Waves / Zenless** — miHoYo/Kuro,
  action combat + anti-cheat → our PostMessage input won't work and bans users.
- **Epic Seven on main accounts** — aggressive detection/bans.

---

## Decisions locked for launch
- **Product name:** `YuhunBot` (keeps NetEase's "Onmyoji" trademark out of the
  brand; "for Onmyoji" stays in marketing keywords).
- **Pricing:** $6/month or $35 lifetime (SEA-friendly, lifetime to convert).
- **Positioning:** "the Onmyoji bot" for SEO; one flexible engine + per-game
  preset packs (Summoners War pack #2).

---

## Sources
- Onmyoji on Steam — https://store.steampowered.com/app/551170/Onmyoji/
- OnmyojiAutoScript (competitor, free) — https://github.com/runhey/OnmyojiAutoScript
- auto-onmyoji (competitor, free) — https://github.com/AymaxLi/auto-onmyoji
- Games like Onmyoji — https://minireview.io/gacha/onmyoji/games-like
- Summoners War scripts (AnkuLua) — https://ankulua.boards.net/board/6/summoners-war
- SW paid farming script (EpicNPC) — https://www.epicnpc.com/threads/summoners-war-farming-script-24-7-autoplay-captcha-auto-solve🔥.1589611/
- Reroll tool freemium pricing — https://gachareroll.com/
- Macro Automation Studio (competitor platform) — https://www.automationmacro.com/
