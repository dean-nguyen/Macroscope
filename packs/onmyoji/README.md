# Onmyoji Automation Pack (YuhunBot)

Macros for the recurring Onmyoji activities. The macro logic is done and was
checked against a live English Steam client; a working pack still needs the
game's screenshots (templates), which you capture on your own machine —
follow `CAPTURE-GUIDE.md`.

## What's covered

| Macro | Type | Stops when |
|-------|------|------------|
| Soul Farming | infinite repeat | AP runs out |
| Exploration Farm | infinite repeat | AP runs out |
| Orochi | infinite repeat | AP / attempts out |
| Awakening Dungeon | infinite repeat | AP runs out |
| Bounty Seals | limited daily | attempts used up |
| Demon Sealing | limited daily | attempts used up |
| Realm Raid | limited daily (+ refresh) | attempts used up |
| Claim Mail | one-shot | — |
| Daily Sign-in | one-shot | — |

Every macro also stops on a **verification/CAPTCHA screen** and on a **full
inventory**, and clears confirm dialogs and reward screens by itself.

## How these were tuned

Behaviour taken from a live client rather than assumed:

- **The client takes ~3 s to react** to a menu click and keeps the button drawn
  meanwhile. The macros therefore poll every `2500 ms` and wait after each click,
  instead of the old `800 ms` — a fast poll clicked the same button repeatedly.
- **Thresholds are `0.80`** for anything clicked and `0.70` for stop-guards, where
  a false stop is the safe direction. These are raw correlation: measured on the
  live window, a template that is on screen scores `~0.92` while absent ones reach
  `~0.47`. Scores were previously remapped into `[0.5, 1.0]`, which made every
  number look far stricter than it was.
- **Realm Raid needs a target selected first.** The Attack button does not exist
  on the target list, so the macro picks a cell from the 3×3 grid, then attacks.
  (The previous version clicked Attack straight from the list, never found it,
  and so did nothing but refresh forever.)
- **Refresh raises a confirm dialog** ("Raid log progress will be reset"), which
  the macro now answers.
- **Onmyoji reuses one orange button chrome everywhere**, so the plain OK button
  cannot be identified by template — a capture of it scored `0.91` against the
  Realm Raid *Refresh* button. Popups are therefore detected by a distinctive
  template (their banner or message text) and the OK is pressed by position,
  since confirm dialogs are modal and centred.

## Resolution independence

Templates are matched scale-aware: the engine finds the scale factor for your
window size once, caches it, and reuses it — so a pack captured at one
resolution keeps working at another. Navigation clicks can use `xp`/`yp`
(fractions of the window's client area) instead of pixels for the same reason;
Realm Raid's grid uses them.

## Turn this into a working, sellable pack

1. In YuhunBot, make a folder called **Onmyoji**.
2. Drop these `.macro.json` files into your macros folder. Open Onmyoji.
3. Capture the templates in `CAPTURE-GUIDE.md` — the "capture now" set is enough
   to start; the opportunistic ones can be filled in as you meet them.
4. Test each macro from its activity screen.
5. Folder `…` menu → **Export as pack…** → `onmyoji.wmbpack`.

## Important caveats

- **Start on the activity screen.** These macros repeat the *battle*; they do not
  navigate the menus for you.
- **A half-captured pack still runs.** Missing templates degrade to "not found"
  and are listed in the log at the start of every run — but note that an
  uncaptured `onmyoji_captcha.png` means the anti-ban guard is inactive.
- **NetEase bans third-party tools.** Run responsibly, keep human-like delays,
  and consider an alt account.
