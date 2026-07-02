# Summoners War — Pack Capture Guide

Turn this starter into a working pack by capturing the game's real screens.
`rune-farm.macro.json` is an example rune-farming loop that references the
template images listed below by name. Capture each one and the macro works.

> Summoners War auto-repeats a chosen dungeon to farm runes/gear — the classic
> "start battle → auto → win → replay" loop, same shape as Onmyoji's Yuhun
> farming. That's why it's the closest expansion.

## How to capture
1. In the app, make a folder called **Summoners War**.
2. Open Summoners War (emulator or PC), go to the dungeon you want to farm, and
   set the battle to **Auto + Repeat** in-game if available.
3. For each template below: sidebar isn't used — in the **macro editor**, click
   **Capture Region**, drag a tight box around the element, and give it the
   exact name listed (so it matches the example macro's references).

## Templates to capture (exact names)
| Save as | What to screenshot |
|---|---|
| `sw_start_battle.png` | The "Start"/"Battle" button before a run |
| `sw_replay.png` | The **Replay** button on the victory screen |
| `sw_victory.png` | A stable part of the victory/results screen |
| `sw_no_energy.png` | The "not enough energy" popup (to stop safely) |
| `sw_network_retry.png` | The reconnect/retry dialog (optional, for stability) |

## Notes
- **Anti-cheat:** Com2uS bans automation and uses periodic CAPTCHAs. Run on an
  **alt account**, keep human-like delays, and don't advertise unfair-advantage
  claims. This is higher-risk than Onmyoji — treat it as expansion #2, not #1.
- Capture at the **resolution you'll run at**; templates are resolution-sensitive.
- Once it runs reliably: folder `…` → **Export as pack…** → `summoners-war.wmbpack`.
