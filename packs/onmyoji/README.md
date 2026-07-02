# Onmyoji Automation Pack (YuhunBot) — Starter

Macros for the common recurring Onmyoji activities ("often events"). This is a
**starter scaffold**: the macro logic is done, but a working pack needs the
game's real screenshots (templates), which you capture on your own client.
Follow `CAPTURE-GUIDE.md`.

## What's covered
| Macro | Type | Stops when |
|-------|------|------------|
| Soul Farming | infinite repeat | AP runs out |
| Exploration Farm | infinite repeat | AP runs out |
| Orochi (soul boss) | infinite repeat | AP/attempts out |
| Awakening Dungeon | infinite repeat | AP runs out |
| Bounty Seals | limited daily | attempts used up |
| Realm Raid | limited daily (+refresh) | attempts used up |
| Demon Sealing | limited daily | attempts used up |
| Daily Sign-in & Mail | one-shot claim | — (runs once) |

Every farming macro auto-stops itself (via the `stop` action) when its
resource/attempts run out — so you can queue them and walk away.

## Turn this into a working, sellable pack
1. In YuhunBot, make a folder called **Onmyoji**.
2. Drop these `.macro.json` files into your macros folder (or recreate them in
   the editor). Open Onmyoji (Steam client or emulator).
3. Capture every template in `CAPTURE-GUIDE.md` (Editor → Capture Region),
   naming each exactly as listed.
4. Test each macro from its activity screen.
5. Folder `…` menu → **Export as pack…** → `onmyoji.wmbpack`.

## Important caveats
- **Start on the activity screen.** These macros repeat the *battle*; open the
  activity (or add your own navigation clicks) before running.
- **NetEase bans third-party tools** — run responsibly, keep human-like delays,
  consider an alt account. Templates are resolution-specific: capture at the
  resolution you'll run at.
